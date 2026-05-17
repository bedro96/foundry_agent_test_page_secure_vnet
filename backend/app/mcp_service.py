"""MCP 클라이언트 서비스 — 외부 MCP 서버로의 도구 탐색 및 실행을 프록시합니다."""

# ── 표준 라이브러리 임포트 ──────────────────────────────────────────
from __future__ import annotations

import json       # JSON 직렬화/역직렬화
import logging    # 로깅 인프라
import time       # 고정밀 타이밍 측정 (monotonic clock)
from dataclasses import dataclass, field  # 데이터 클래스 선언용 데코레이터
from typing import Any, cast              # 타입 힌트 유틸리티

# ── 서드파티 라이브러리 임포트 ──────────────────────────────────────
import httpx  # 비동기 HTTP 클라이언트 (JSON-RPC 요청 전송용)

# 모듈 전용 로거 — 이 모듈의 모든 로그 메시지에 사용됩니다
logger = logging.getLogger(__name__)


@dataclass
class McpTiming:
    """MCP 작업의 타이밍 분석.

    모든 값은 밀리초 단위입니다. ``server_execution_ms``는 MCP 서버가
    인식된 타이밍 헤더 (``x-execution-time``, ``x-response-time``,
    또는 ``server-timing``)를 포함하는 경우에만 채워집니다.
    """

    total_ms: float = 0.0                    # 전체 작업 소요 시간 (밀리초)
    initialize_ms: float = 0.0               # 초기화 핸드셰이크 소요 시간 (밀리초)
    list_tools_ms: float = 0.0               # 도구 목록 조회 소요 시간 (밀리초)
    tool_call_ms: float = 0.0                # 도구 호출 소요 시간 (밀리초)
    server_execution_ms: float | None = None  # 서버 측 실행 시간 (헤더에서 추출, 없으면 None)

    def to_dict(self) -> dict[str, float | None]:
        """제로 값 단계를 생략하고 JSON 안전 딕셔너리로 직렬화합니다."""
        # 항상 포함되는 전체 소요 시간
        d: dict[str, float | None] = {"total_ms": round(self.total_ms, 2)}
        if self.initialize_ms:  # 초기화 단계가 기록된 경우만 포함
            d["initialize_ms"] = round(self.initialize_ms, 2)
        if self.list_tools_ms:  # 도구 목록 조회 단계가 기록된 경우만 포함
            d["list_tools_ms"] = round(self.list_tools_ms, 2)
        if self.tool_call_ms:   # 도구 호출 단계가 기록된 경우만 포함
            d["tool_call_ms"] = round(self.tool_call_ms, 2)
        # 서버 실행 시간은 None일 수 있으므로 항상 포함 (존재 여부 확인용)
        d["server_execution_ms"] = (
            round(self.server_execution_ms, 2) if self.server_execution_ms is not None else None
        )
        return d


@dataclass
class McpConnectResult:
    """연결 (초기화 + 도구 목록 조회) 작업의 결과."""

    tools: list[dict[str, Any]] = field(default_factory=list)   # 서버에서 반환된 도구 목록
    timing: McpTiming = field(default_factory=McpTiming)       # 연결 과정의 타이밍 분석


@dataclass
class McpCallResult:
    """도구 호출의 결과."""

    result: Any = None                                          # 도구 실행 결과 데이터
    timing: McpTiming = field(default_factory=McpTiming)       # 호출 과정의 타이밍 분석


def _extract_server_timing(resp: httpx.Response) -> float | None:
    """HTTP 응답 헤더에서 서버 측 실행 시간을 추출합니다.

    ``x-execution-time``, ``x-response-time``, W3C ``server-timing``
    헤더를 확인합니다. 밀리초 또는 ``None``을 반환합니다.
    """
    # 우선 x-execution-time, x-response-time 커스텀 헤더를 확인합니다
    for header in ("x-execution-time", "x-response-time"):
        value = resp.headers.get(header)  # 헤더 값 조회 (없으면 None)
        if value:
            try:
                ms = float(value)  # 문자열을 밀리초 숫자로 변환
                # 휴리스틱: 값이 초 단위(< 1000이고 소수점이 있는 경우)처럼
                # 보이면 ms로 변환합니다. 대부분의 헤더는 ms를 직접 보고합니다.
                # 참고: 대부분의 MCP 서버는 ms 단위를 사용하므로 추가 변환 없이 반환합니다
                return ms
            except (ValueError, TypeError):
                continue  # 파싱 실패 시 다음 헤더로 진행

    # W3C Server-Timing 표준 헤더에서 dur= 값을 추출합니다
    server_timing = resp.headers.get("server-timing")
    if server_timing:
        # 쉼표로 구분된 각 메트릭 항목을 순회합니다
        for part in server_timing.split(","):
            if "dur=" in part:  # dur= 키워드가 포함된 항목만 처리
                try:
                    # dur= 뒤의 숫자 값을 추출합니다 (세미콜론 이전까지)
                    dur_str = part.split("dur=")[1].split(";")[0].strip()
                    return float(dur_str)
                except (ValueError, IndexError):
                    continue  # 파싱 실패 시 다음 메트릭 항목으로 진행
    return None  # 어떤 헤더에서도 서버 실행 시간을 찾지 못함


class McpClient:
    """스트리밍 가능한 HTTP를 통한 JSON-RPC 2.0 경량 MCP 클라이언트.

    Attributes:
        server_url: 원격 MCP 서버의 기본 URL (후행 슬래시 제거됨).
        headers: 생성 시 구성된 인증 헤더를 포함하여 모든 요청과 함께
            전송되는 기본 HTTP 헤더.
    """

    def __init__(
        self,
        server_url: str,
        auth_type: str = "none",
        auth_header: str = "",
        auth_value: str = "",
    ) -> None:
        """MCP 클라이언트를 초기화합니다.

        Args:
            server_url: MCP 서버의 기본 URL (예: ``https://mcp.example.com``).
            auth_type: 인증 방식 — ``"none"`` 또는 ``"api_key"``.
            auth_header: API 키 인증에 사용되는 HTTP 헤더 이름
                (예: ``"x-api-key"``). *auth_type*이 ``"none"``이면 무시됩니다.
            auth_value: 인증 헤더의 값. *auth_type*이 ``"none"``이면
                무시됩니다.
        """
        self.server_url = str(server_url).rstrip("/")  # 후행 슬래시를 제거한 MCP 서버 URL
        # 모든 요청에 포함될 기본 HTTP 헤더를 구성합니다
        self.headers: dict[str, str] = {
            "Content-Type": "application/json",             # 요청 본문 형식: JSON
            "Accept": "application/json, text/event-stream",  # 응답 형식: JSON 또는 SSE 스트림
        }
        # API 키 인증이 설정된 경우 커스텀 인증 헤더를 추가합니다
        if auth_type == "api_key" and auth_header and auth_value:
            self.headers[auth_header] = auth_value  # 사용자 지정 인증 헤더 삽입
        logger.info(
            "McpClient initialized: server_url=%s, auth_type=%s",
            self.server_url,
            auth_type,
        )

    def _jsonrpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        req_id: int = 1,
    ) -> dict[str, Any]:
        """JSON-RPC 2.0 요청 페이로드를 구성합니다.

        Args:
            method: JSON-RPC 메서드 이름 (예: ``"initialize"``).
            params: 선택적 메서드 매개변수 딕셔너리.
            req_id: 응답 상관관계를 위한 정수 요청 식별자.

        Returns:
            JSON-RPC 2.0 요청 형식에 부합하는 딕셔너리.
        """
        # JSON-RPC 2.0 요청 페이로드를 구성합니다
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": req_id}
        if params:  # 매개변수가 제공된 경우에만 params 필드를 추가합니다
            payload["params"] = params
        return payload

    async def initialize(self) -> tuple[dict[str, Any], dict[str, str]]:
        """MCP 서버에 초기화 핸드셰이크를 전송합니다.

        Returns:
            (서버_기능_딕셔너리, 세션_헤더) 튜플. *세션_헤더*는 서버가
            제공한 경우 ``mcp-session-id``를 포함합니다.
        """
        logger.info("MCP initialize() starting: server_url=%s", self.server_url)
        async with httpx.AsyncClient(timeout=30.0, max_redirects=0) as client:
            result = await self._initialize_with_client(client)
            logger.info("MCP initialize() completed successfully: server_url=%s", self.server_url)
            return result

    async def list_tools(self) -> McpConnectResult:
        """MCP 서버에서 초기화 + 도구 목록을 조회합니다.

        Returns:
            도구 목록과 타이밍 분석이 포함된 ``McpConnectResult``.
        """
        logger.info("MCP list_tools() starting: server_url=%s", self.server_url)
        timing = McpTiming()          # 타이밍 분석 객체를 초기화합니다
        total_start = time.monotonic()  # 전체 작업의 시작 시각을 기록합니다

        # 비동기 HTTP 클라이언트를 생성합니다 (30초 타임아웃, 리다이렉트 비허용)
        async with httpx.AsyncClient(timeout=30.0, max_redirects=0) as client:
            # ── 1단계: 초기화 핸드셰이크 ──
            init_start = time.monotonic()  # 초기화 단계 시작 시각
            _, session_headers = await self._initialize_with_client(client)
            timing.initialize_ms = (time.monotonic() - init_start) * 1000  # 초기화 소요 시간 계산

            # ── 2단계: 초기화 완료 알림 전송 ──
            notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}  # 초기화 완료 통지 페이로드
            await client.post(self.server_url, json=notif, headers=session_headers)
            logger.debug("MCP initialized notification sent: server_url=%s", self.server_url)

            # ── 3단계: 도구 목록 조회 요청 ──
            payload = self._jsonrpc("tools/list", req_id=2)  # tools/list JSON-RPC 페이로드 생성
            list_start = time.monotonic()  # 도구 목록 조회 시작 시각
            resp = await client.post(self.server_url, json=payload, headers=session_headers)
            timing.list_tools_ms = (time.monotonic() - list_start) * 1000  # 도구 목록 조회 소요 시간 계산
            timing.server_execution_ms = _extract_server_timing(resp)  # 서버 측 실행 시간 추출

            # ── 4단계: 응답 파싱 및 타이밍 집계 ──
            resp.raise_for_status()  # HTTP 오류 상태 시 예외 발생
            result = self._parse_response(resp)  # JSON-RPC 응답에서 result 추출
            tools = cast(list[dict[str, Any]], result.get("tools", []))  # 도구 목록 추출

            timing.total_ms = (time.monotonic() - total_start) * 1000  # 전체 소요 시간 계산
            logger.info(
                "MCP list_tools() completed: server_url=%s, tool_count=%d, tool_names=%s, timing=%s",
                self.server_url,
                len(tools),
                [t.get("name", "unknown") for t in tools],
                timing.to_dict(),
            )
            return McpConnectResult(tools=tools, timing=timing)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> McpCallResult:
        """초기화 + 특정 도구를 호출합니다.

        Args:
            tool_name: 호출할 MCP 도구 이름.
            arguments: 도구에 전달할 키워드 인수.

        Returns:
            도구 출력과 타이밍 분석이 포함된 ``McpCallResult``.
        """
        logger.info(
            "MCP call_tool() starting: server_url=%s, tool_name=%s, argument_keys=%s",
            self.server_url,
            tool_name,
            list(arguments.keys()) if arguments else [],
        )
        timing = McpTiming()          # 타이밍 분석 객체를 초기화합니다
        total_start = time.monotonic()  # 전체 작업의 시작 시각을 기록합니다

        # 비동기 HTTP 클라이언트를 생성합니다 (60초 타임아웃, 도구 실행은 시간이 걸릴 수 있음)
        async with httpx.AsyncClient(timeout=60.0, max_redirects=0) as client:
            # ── 1단계: 초기화 핸드셰이크 ──
            init_start = time.monotonic()  # 초기화 단계 시작 시각
            _, session_headers = await self._initialize_with_client(client)
            timing.initialize_ms = (time.monotonic() - init_start) * 1000  # 초기화 소요 시간 계산

            # ── 2단계: 초기화 완료 알림 전송 ──
            notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}  # 초기화 완료 통지 페이로드
            await client.post(self.server_url, json=notif, headers=session_headers)

            # ── 3단계: 도구 호출 요청 구성 ──
            payload = self._jsonrpc(
                "tools/call",
                {
                    "name": tool_name,        # 호출할 도구 이름
                    "arguments": arguments,   # 도구에 전달할 인수 딕셔너리
                },
                req_id=3,  # 요청 식별자 (initialize=1, tools/list=2, tools/call=3)
            )
            # ── 4단계: 도구 호출 실행 및 타이밍 측정 ──
            call_start = time.monotonic()  # 도구 호출 시작 시각
            resp = await client.post(self.server_url, json=payload, headers=session_headers)
            timing.tool_call_ms = (time.monotonic() - call_start) * 1000  # 도구 호출 소요 시간 계산
            timing.server_execution_ms = _extract_server_timing(resp)  # 서버 측 실행 시간 추출

            # ── 5단계: 응답 파싱 및 타이밍 집계 ──
            resp.raise_for_status()  # HTTP 오류 상태 시 예외 발생
            result = self._parse_response(resp)  # JSON-RPC 응답에서 result 추출

            timing.total_ms = (time.monotonic() - total_start) * 1000  # 전체 소요 시간 계산
            logger.info(
                "MCP call_tool() completed: server_url=%s, tool_name=%s, timing=%s",
                self.server_url,
                tool_name,
                timing.to_dict(),
            )
            return McpCallResult(result=result, timing=timing)

    async def _initialize_with_client(
        self,
        client: httpx.AsyncClient,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """기존 HTTP 클라이언트를 사용하여 초기화 핸드셰이크를 전송합니다.

        Args:
            client: 요청에 재사용할 사전 구성된 ``httpx.AsyncClient``,
                호출 간 세션 헤더 전파를 허용합니다.

        Returns:
            (서버_기능_딕셔너리, 세션_헤더) 튜플. *세션_헤더*는
            서버가 제공한 경우 ``mcp-session-id``가 추가된
            기본 헤더의 복사본입니다.
        """

        logger.debug("MCP _initialize_with_client() sending handshake: server_url=%s", self.server_url)
        # MCP 프로토콜 초기화 핸드셰이크 페이로드를 구성합니다
        payload = self._jsonrpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",  # MCP 프로토콜 버전
                "capabilities": {},                # 클라이언트 지원 기능 (현재 없음)
                "clientInfo": {"name": "ai-chat-portal", "version": "1.0.0"},  # 클라이언트 식별 정보
            },
        )
        # 초기화 요청을 MCP 서버로 전송합니다
        resp = await client.post(self.server_url, json=payload, headers=self.headers)
        resp.raise_for_status()  # HTTP 오류 상태 시 예외 발생

        # 기본 헤더를 복사하여 세션 헤더를 생성합니다
        session_headers = dict(self.headers)
        # 서버가 세션 ID를 제공한 경우 후속 요청에 포함시킵니다
        session_id = resp.headers.get("mcp-session-id")  # 세션 ID 추출
        if session_id:
            session_headers["mcp-session-id"] = session_id  # 세션 헤더에 ID 추가
            logger.info("MCP session established: server_url=%s, session_id=%s", self.server_url, session_id)
        else:
            logger.debug("MCP handshake completed without session id: server_url=%s", self.server_url)
        # 파싱된 서버 기능 딕셔너리와 세션 헤더를 반환합니다
        return self._parse_response(resp), session_headers

    def _parse_response(self, resp: httpx.Response) -> dict[str, Any]:
        """순수 JSON 및 SSE 형식을 모두 처리하여 JSON-RPC 응답을 파싱합니다.

        Args:
            resp: MCP 서버로부터 수신한 원시 ``httpx.Response``.

        Returns:
            JSON-RPC 응답에서 추출된 ``result`` 딕셔너리.

        Raises:
            RuntimeError: 응답에 JSON-RPC 오류 객체가 포함되어 있거나
                SSE 스트림에서 유효한 ``data:`` 라인을 찾지 못한 경우.
        """
        # 응답의 Content-Type 헤더를 확인하여 파싱 전략을 결정합니다
        content_type = resp.headers.get("content-type", "")  # Content-Type 헤더 값
        text = resp.text.strip()  # 응답 본문 (양쪽 공백 제거)
        logger.debug(
            "MCP _parse_response(): status=%d, content_type=%s, body_length=%d",
            resp.status_code,
            content_type,
            len(text),
        )

        # ── SSE (Server-Sent Events) 형식 응답 파싱 분기 ──
        if "text/event-stream" in content_type:
            # 마지막 data: 라인부터 역순으로 검색합니다 (최종 결과가 뒤에 위치)
            for line in reversed(text.splitlines()):
                stripped = line.strip()
                if not stripped.startswith("data:"):  # data: 접두사가 없으면 건너뜁니다
                    continue
                # data: 접두사 이후의 JSON 페이로드를 파싱합니다
                data = cast(dict[str, Any], json.loads(stripped[5:].strip()))
                if "result" in data:  # 성공 응답인 경우 result 반환
                    return cast(dict[str, Any], data["result"])
                if "error" in data:   # 오류 응답인 경우 예외 발생
                    logger.error("MCP server returned error: %s", data["error"])
                    raise RuntimeError(f"MCP error: {data['error']}")
                continue  # result도 error도 없는 data 라인은 건너뜁니다
            # 유효한 data: 라인을 찾지 못한 경우 예외 발생
            raise RuntimeError("No valid SSE data found in response")

        # ── 일반 JSON 형식 응답 파싱 분기 ──
        data = cast(dict[str, Any], resp.json())  # 응답 본문을 JSON으로 파싱합니다
        if "result" in data:  # 성공 응답인 경우 result 반환
            return cast(dict[str, Any], data["result"])
        if "error" in data:   # 오류 응답인 경우 예외 발생
            logger.error("MCP server returned error: %s", data["error"])
            raise RuntimeError(f"MCP error: {data['error']}")
        return data  # result/error 키가 없는 경우 전체 데이터를 그대로 반환합니다

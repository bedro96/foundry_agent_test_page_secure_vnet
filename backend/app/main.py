"""FastAPI 애플리케이션 진입점 및 라우트 정의 모듈.

채팅 스트리밍, MCP 검증, 사용자 인증, 관리자 사용자 관리,
대화 CRUD, 음성 전사 등 모든 HTTP 엔드포인트를 정의합니다.
CORS, API 키 인증, 액세스 로깅 미들웨어를 구성하고,
서버 시작 시 데이터베이스 테이블을 자동 생성합니다.
"""

# ── 표준 라이브러리 ────────────────────────────────────────────────────────────
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

# ── 서드파티 패키지 ────────────────────────────────────────────────────────────
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from httpx import HTTPError

# ── 로컬 애플리케이션 모듈 ─────────────────────────────────────────────────────
from app.agent import AzureAIFoundryAgent  # Azure AI Foundry 에이전트 구현체
from app.agent_framework import AgentOrchestrator  # 에이전트 오케스트레이션 프레임워크
from app.auth import APIKeyAuthMiddleware  # API 키 기반 인증 미들웨어
from app.auth_service import (  # 사용자 인증 및 JWT 관련 서비스 함수들
    create_jwt_token,
    create_user,
    decode_jwt_token,
    delete_user,
    get_all_users,
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
    update_user,
    verify_password,
)
from app.config import get_settings  # 환경변수 기반 설정 로더
from app.database import SessionLocal, check_connection, get_engine  # SQLAlchemy DB 세션 및 엔진
from app.db_models import Base, Conversation, Message  # ORM 모델 정의
from app.logging import AccessLogMiddleware, configure_logging  # 로깅 설정 및 액세스 로그 미들웨어
from app.mcp_service import McpClient  # MCP 프로토콜 클라이언트
from app.models import (  # Pydantic 요청/응답 스키마 모델들
    AdminUpdateUserRequest,
    AdminUserResponse,
    AuthResponse,
    ChatRequest,
    ChatStreamEvent,
    ConversationDetail,
    ConversationSummary,
    HealthResponse,
    HealthStatusResponse,
    LoginRequest,
    McpConnectRequest,
    McpExecuteRequest,
    MessageDetail,
    PaginatedConversations,
    SaveConversationRequest,
    SignupRequest,
    TokenAuthResponse,
    TranscriptionRequest,
    TranscriptionResponse,
)
from app.speech import AzureSpeechTranscriber  # Azure Speech 음성 전사 서비스
from app.telemetry import configure_telemetry  # OpenTelemetry 텔레메트리 설정

# ── 모듈 수준 초기화 ───────────────────────────────────────────────────────────

# 애플리케이션 설정을 환경변수에서 로드합니다
settings = get_settings()

# 텔레메트리는 다른 Azure SDK 클라이언트보다 먼저 초기화되어야 합니다.
# SDK가 os.environ의 트레이싱 환경변수를 클라이언트 생성 시점에 읽기 때문입니다.
# ENABLE_TELEMETRY가 False이면 텔레메트리 초기화를 완전히 건너뜁니다.
if settings.enable_telemetry:
    telemetry_ok = configure_telemetry(settings)  # OpenTelemetry 트레이싱 설정 결과 (True/False)
else:
    telemetry_ok = False

logger = configure_logging(settings)  # 구조화된 로거 인스턴스 생성
logger.info("Logging initialized: APP_ENV=%s", settings.app_env)
if telemetry_ok:
    logger.info("GenAI 텔레메트리 트레이싱이 활성화되었습니다")
else:
    logger.info("GenAI 텔레메트리 트레이싱이 비활성화 상태입니다")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작 시 MySQL 테이블을 자동 생성합니다 (멱등성 보장)."""
    try:
        engine = get_engine()
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables verified/created successfully")
    except Exception as exc:
        logger.warning("Database table auto-creation skipped: %s", exc)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)  # FastAPI 애플리케이션 인스턴스 생성
app.add_middleware(APIKeyAuthMiddleware, settings=settings)  # 프로덕션 환경 API 키 인증 미들웨어 등록
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",       # 로컬 프론트엔드 개발 서버 (기본 포트)
        "http://localhost:3001",       # 로컬 프론트엔드 개발 서버 (대체 포트)
        "https://lgit-chat-frontend.mangofield-57a3b9f0.koreacentral.azurecontainerapps.io",  # Azure Container Apps 프로덕션 프론트엔드
    ],
    allow_origin_regex=r"https://.*\.azurecontainerapps\.io",  # 모든 Azure Container Apps 하위 도메인 허용 (스테이징/리비전 포함)
    allow_credentials=True,   # 쿠키 및 인증 헤더 전달 허용
    allow_methods=["*"],      # 모든 HTTP 메서드 허용 (GET, POST, PUT, DELETE 등)
    allow_headers=["*"],      # 모든 요청 헤더 허용 (Authorization, Content-Type 등)
)
app.add_middleware(AccessLogMiddleware, log_keepalive=settings.log_keepalive)  # 요청/응답 액세스 로깅 미들웨어
# 기본 AI 에이전트를 포함한 오케스트레이터 초기화 (채팅 스트리밍 처리)
orchestrator = AgentOrchestrator(default_agent=AzureAIFoundryAgent(settings=settings))
# Azure Speech Services를 사용한 음성 전사기 초기화
speech_transcriber = AzureSpeechTranscriber(settings=settings)
logger.info("Application initialized successfully")


def _format_sse(payload: ChatStreamEvent) -> str:
    """채팅 스트림 이벤트를 Server-Sent Events 프레임으로 포맷합니다.

    Args:
        payload: 직렬화할 채팅 스트림 이벤트.

    Returns:
        이벤트 타입과 JSON 데이터가 포함된 SSE 형식 문자열.
    """
    return f"event: {payload.event}\ndata: {payload.model_dump_json()}\n\n"


def _extract_latest_user_prompt(request: ChatRequest) -> str:
    """로깅 목적으로 가장 최근의 사용자 프롬프트 텍스트를 추출합니다."""
    # 메시지 목록을 역순으로 순회하여 가장 최근 사용자 메시지를 찾습니다
    for message in reversed(request.messages):
        # 사용자 역할이 아닌 메시지는 건너뜁니다 (assistant, system 등)
        if message.role != "user":
            continue
        content = message.content
        # 단순 문자열 콘텐츠인 경우 공백 제거 후 반환합니다
        if isinstance(content, str) and content.strip():
            return content.strip()
        # 멀티모달 콘텐츠(리스트)인 경우 텍스트 파트만 추출하여 결합합니다
        if isinstance(content, list):
            texts = [part.text for part in content if hasattr(part, "text") and part.text.strip()]
            if texts:
                return " ".join(texts)
    # 사용자 메시지를 찾지 못한 경우 빈 문자열을 반환합니다
    return ""


def _summarize_request(request: ChatRequest) -> dict[str, Any]:
    """SSE 경계 로깅을 위한 콘텐츠 안전 요청 요약을 반환합니다.

    사용자 생성 콘텐츠를 노출하지 않고 메타데이터(역할별 메시지 수,
    대화 ID 존재 여부)를 추출합니다.

    Args:
        request: 메시지와 메타데이터를 포함하는 수신 채팅 요청.

    Returns:
        구조화된 로깅에 적합한 conversation_id, 역할별 메시지 수,
        메타데이터 키 수를 포함하는 딕셔너리.
    """

    role_counts = Counter(message.role for message in request.messages)
    return {
        "conversation_id": request.conversation_id,
        "conversation_id_present": bool(request.conversation_id),
        "message_count": len(request.messages),
        "system_message_count": role_counts.get("system", 0),
        "user_message_count": role_counts.get("user", 0),
        "assistant_message_count": role_counts.get("assistant", 0),
        "metadata_key_count": len(request.metadata or {}),
    }


def _summarize_stream_event(
    payload: ChatStreamEvent,
    *,
    event_index: int,
    sse_frame_length: int,
) -> dict[str, Any]:
    """스트리밍된 SSE 이벤트에 대한 콘텐츠 안전 요약을 반환합니다.

    실제 페이로드 콘텐츠를 로깅하지 않고 이벤트의 구조적
    메타데이터를 캡처합니다.

    Args:
        payload: 요약할 SSE 이벤트 페이로드.
        event_index: 스트림 내에서 이 이벤트의 1-기반 순서 위치.
        sse_frame_length: 렌더링된 SSE 프레임의 바이트 길이.

    Returns:
        구조화된 로깅을 위한 이벤트 타입, 인덱스, 필드 이름,
        데이터 길이, SSE 프레임 크기를 포함하는 딕셔너리.
    """

    return {
        "event_index": event_index,
        "event": payload.event,
        "conversation_id": payload.conversation_id,
        "conversation_id_present": bool(payload.conversation_id),
        "payload_fields": sorted(payload.model_dump().keys()),
        "data_length": len(payload.data),
        "sse_frame_length": sse_frame_length,
    }


def _summarize_stream_result(
    *,
    request_summary: dict[str, Any],
    event_counts: Counter[str],
    last_event: str | None,
    final_conversation_id: str | None,
    terminal_result_length: int | None,
    status: str,
) -> dict[str, Any]:
    """페이로드 내용을 노출하지 않는 최종 스트림 요약을 반환합니다.

    스트림 종료 로깅을 위한 스트림 수준의 통계를 집계합니다.

    Args:
        request_summary: ``_summarize_request``에서 생성된 콘텐츠
            안전 요청 요약.
        event_counts: 스트림 동안 이벤트 타입 이름과 발생 횟수를
            매핑하는 카운터.
        last_event: 마지막으로 생성된 이벤트의 타입, 이벤트가
            생성되지 않은 경우 ``None``.
        final_conversation_id: 마지막 이벤트가 전달한 대화 ID,
            또는 원래 요청의 대화 ID.
        terminal_result_length: ``done`` 또는 ``error`` 이벤트
            데이터의 문자 길이, 아직 도달하지 않은 경우 ``None``.
        status: 사람이 읽을 수 있는 스트림 결과 레이블
            (예: ``"completed"``, ``"failed"``, ``"ended"``).

    Returns:
        상태, 대화 ID, 전체 및 타입별 이벤트 수, 터미널 결과
        길이를 포함하는 딕셔너리.
    """

    return {
        "status": status,
        "request_conversation_id": request_summary["conversation_id"],
        "final_conversation_id": final_conversation_id,
        "event_count": sum(event_counts.values()),
        "event_counts": dict(event_counts),
        "last_event": last_event,
        "terminal_result_length": terminal_result_length,
    }


async def _event_stream(request: ChatRequest) -> AsyncIterator[str]:
    """채팅 응답을 SSE 프레임으로 스트리밍하는 비동기 제너레이터.

    오케스트레이터의 ``stream_chat`` 메서드에 위임하고, 생성된 각
    에이전트 이벤트를 SSE 형식 문자열로 래핑합니다. 스트림
    수명 주기(시작, 이벤트별, 완료, 실패)는 콘텐츠 안전 요약으로
    로깅됩니다.

    Args:
        request: 대화 이력이 포함된 수신 채팅 요청.

    Yields:
        ``StreamingResponse``에 사용할 수 있는 SSE 형식 문자열.

    Raises:
        Exception: 실패 요약을 로깅한 후 오케스트레이터에서 발생한
            모든 예외를 다시 발생시킵니다.
    """
    # ── 초기화 단계: 요청 메타데이터를 요약하고 스트림 상태 변수를 설정합니다 ──
    request_summary = _summarize_request(request)  # 콘텐츠 안전 요청 요약 생성
    user_prompt = _extract_latest_user_prompt(request)  # 로깅용 최근 사용자 프롬프트 추출
    logger.info(
        "SSE stream initialization started: %s, user_prompt=%s",
        request_summary,
        user_prompt,
    )
    event_counts: Counter[str] = Counter()  # 이벤트 타입별 발생 횟수 추적 카운터
    final_conversation_id = request.conversation_id  # 최종 대화 ID (스트림 중 업데이트 가능)
    last_event: str | None = None  # 마지막으로 생성된 이벤트 타입
    terminal_result_length: int | None = None  # 종료 이벤트(done/error) 데이터 길이
    try:
        # ── 스트리밍 루프 단계: 오케스트레이터에서 이벤트를 수신하여 SSE 프레임으로 변환합니다 ──
        async for event in orchestrator.stream_chat(request):
            # 에이전트 이벤트를 SSE 페이로드 객체로 래핑합니다
            payload = ChatStreamEvent(
                event=event.event,  # type: ignore
                data=event.data,
                conversation_id=event.conversation_id,
            )
            event_counts[payload.event] += 1  # 이벤트 타입별 카운트 증가
            last_event = payload.event  # 마지막 이벤트 타입 갱신
            final_conversation_id = payload.conversation_id or final_conversation_id  # 대화 ID 갱신
            # 종료 이벤트(done/error)의 데이터 길이를 기록합니다
            if payload.event in {"done", "error"}:
                terminal_result_length = len(payload.data)
            sse_frame = _format_sse(payload)  # SSE 형식 문자열로 변환
            logger.info(
                "SSE event yielded: %s",
                _summarize_stream_event(
                    payload,
                    event_index=sum(event_counts.values()),
                    sse_frame_length=len(sse_frame),
                ),
            )
            yield sse_frame
        # ── 완료 단계: 스트림이 정상적으로 종료되었음을 로깅합니다 ──
        logger.info(
            "SSE stream completed successfully: %s",
            _summarize_stream_result(
                request_summary=request_summary,
                event_counts=event_counts,
                last_event=last_event,
                final_conversation_id=final_conversation_id,
                terminal_result_length=terminal_result_length,
                status="completed",
            ),
        )
    except Exception:
        # ── 오류 단계: 스트림 중 예외 발생 시 실패 요약을 로깅합니다 ──
        logger.exception(
            "SSE stream failed: %s",
            _summarize_stream_result(
                request_summary=request_summary,
                event_counts=event_counts,
                last_event=last_event,
                final_conversation_id=final_conversation_id,
                terminal_result_length=terminal_result_length,
                status="failed",
            ),
        )
        raise
    finally:
        # ── 정리 단계: 성공/실패 여부와 관계없이 최종 스트림 상태를 로깅합니다 ──
        logger.info(
            "SSE stream ended: %s",
            _summarize_stream_result(
                request_summary=request_summary,
                event_counts=event_counts,
                last_event=last_event,
                final_conversation_id=final_conversation_id,
                terminal_result_length=terminal_result_length,
                status="ended",
            ),
        )


@app.get("/", response_class=JSONResponse)
async def index() -> dict[str, str]:
    """기본 애플리케이션 식별 정보를 반환합니다.

    **GET /**

    Returns:
        ``name``과 ``environment`` 키를 포함하는 JSON 객체.
    """
    logger.debug("index() called")
    result = {"name": settings.app_name or "", "environment": settings.app_env or ""}
    logger.info("index() responded successfully")
    return result


@app.get("/health/ready", response_model=HealthResponse)
async def health() -> HealthResponse:
    """컨테이너 오케스트레이터를 위한 준비 상태 프로브.

    **GET /health/ready**

    Returns:
        애플리케이션 이름과 환경이 포함된 ``HealthResponse``.
    """
    if settings.log_keepalive:
        logger.debug("health() called")
    response = HealthResponse(app_name=settings.app_name or "", environment=settings.app_env or "")
    if settings.log_keepalive:
        logger.info("health() responded successfully")
    return response


@app.get("/health/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    """컨테이너 오케스트레이터를 위한 활성 상태 프로브.

    **GET /health/live**

    Returns:
        프로세스가 살아있음을 확인하는 ``HealthResponse``.
    """
    if settings.log_keepalive:
        logger.debug("health() called")
    response = HealthResponse(app_name=settings.app_name or "", environment=settings.app_env or "")
    if settings.log_keepalive:
        logger.info("health() responded successfully")
    return response


@app.get("/health/status", response_model=HealthStatusResponse)
async def health_status() -> HealthStatusResponse:
    """프런트엔드 상태 배지를 위한 시스템 연결 상태 확인.

    **GET /health/status**

    Returns:
        백엔드 활성 상태와 데이터베이스 연결 상태를 포함하는 ``HealthStatusResponse``.
    """
    db_ok = False
    try:
        db_ok = check_connection()
    except Exception:
        db_ok = False
    return HealthStatusResponse(backend=True, db=db_ok)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """AI 채팅 응답을 Server-Sent Events로 스트리밍합니다.

    **POST /api/chat/stream**

    대화 이력을 수신하고, 각 SSE 프레임에 ``ChatStreamEvent``가
    포함된 ``text/event-stream`` 응답을 반환합니다.

    Args:
        request: 대화 메시지, 선택적 대화 ID, 선택적 메타데이터를
            포함하는 채팅 요청.

    Returns:
        ``media_type="text/event-stream"``인 ``StreamingResponse``.
    """
    request_summary = _summarize_request(request)
    user_prompt = _extract_latest_user_prompt(request)
    logger.info(
        "chat_stream() request received: conversation_id=%s, user_prompt=%s, summary=%s",
        request.conversation_id,
        user_prompt,
        request_summary,
    )
    response = StreamingResponse(_event_stream(request), media_type="text/event-stream")
    logger.info("chat_stream() streaming response initialized: conversation_id=%s", request.conversation_id)
    return response


@app.post("/api/mcp/connect")
async def mcp_connect(req: McpConnectRequest) -> dict[str, Any]:
    """MCP 서버에 연결하고 사용 가능한 도구 목록을 조회합니다.

    **POST /api/mcp/connect**

    제공된 인증 방식을 사용하여 지정된 MCP 서버에 연결을 설정하고
    도구 카탈로그를 가져옵니다.

    Args:
        req: 서버 URL, 인증 타입, 선택적 자격 증명을 포함하는
            연결 매개변수.

    Returns:
        도구 설명자 딕셔너리 목록이 포함된 ``tools`` 키를 가진
        딕셔너리.

    Raises:
        HTTPException: 전송 계층이 실패(``HTTPError``)하거나
            서버가 파싱할 수 없는 응답을 반환한 경우 502.
    """

    logger.info(
        "mcp_connect() request received: server_url=%s, auth_type=%s",
        req.server_url,
        req.auth_type,
    )
    try:
        client = McpClient(
            server_url=str(req.server_url),
            auth_type=req.auth_type,
            auth_header=req.auth_header,
            auth_value=req.auth_value,
        )
        connect_result = await client.list_tools()
        logger.info(
            "mcp_connect() succeeded: server_url=%s, tool_count=%d, timing=%s",
            req.server_url,
            len(connect_result.tools),
            connect_result.timing.to_dict(),
        )
        return {"tools": connect_result.tools, "timing": connect_result.timing.to_dict()}
    except HTTPError as exc:
        logger.exception("MCP connect transport failed for server=%s", req.server_url)
        raise HTTPException(status_code=502, detail="Unable to connect to the MCP server") from exc
    except Exception as exc:
        logger.exception("MCP connect failed for server=%s", req.server_url)
        raise HTTPException(status_code=502, detail="MCP server returned an invalid response") from exc


@app.post("/api/mcp/execute")
async def mcp_execute(req: McpExecuteRequest) -> dict[str, Any]:
    """MCP 서버에서 도구를 실행하고 결과를 반환합니다.

    **POST /api/mcp/execute**

    지정된 MCP 서버에 연결하고, 제공된 인자로 명명된 도구를 호출한
    후 원시 결과를 반환합니다.

    Args:
        req: 서버 URL, 인증 정보, 도구 이름, 도구 인자를 포함하는
            실행 매개변수.

    Returns:
        도구의 출력 페이로드가 포함된 ``result`` 키를 가진
        딕셔너리.

    Raises:
        HTTPException: 전송 계층이 실패(``HTTPError``)하거나
            서버가 파싱할 수 없는 응답을 반환한 경우 502.
    """

    logger.info(
        "mcp_execute() request received: server_url=%s, tool_name=%s, argument_keys=%s",
        req.server_url,
        req.tool_name,
        list(req.arguments.keys()) if req.arguments else [],
    )
    try:
        client = McpClient(
            server_url=str(req.server_url),
            auth_type=req.auth_type,
            auth_header=req.auth_header,
            auth_value=req.auth_value,
        )
        call_result = await client.call_tool(req.tool_name, req.arguments)
        logger.info(
            "mcp_execute() succeeded: server_url=%s, tool_name=%s, timing=%s",
            req.server_url,
            req.tool_name,
            call_result.timing.to_dict(),
        )
        return {"result": call_result.result, "timing": call_result.timing.to_dict()}
    except HTTPError as exc:
        logger.exception("MCP execute transport failed for server=%s tool=%s", req.server_url, req.tool_name)
        raise HTTPException(status_code=502, detail="Unable to connect to the MCP server") from exc
    except Exception as exc:
        logger.exception("MCP execute failed for server=%s tool=%s", req.server_url, req.tool_name)
        raise HTTPException(status_code=502, detail="MCP server returned an invalid response") from exc


@app.post("/api/auth/signup", response_model=AuthResponse)
async def auth_signup(request: SignupRequest) -> AuthResponse:
    """새 사용자 계정을 등록합니다.

    **POST /api/auth/signup**

    이메일과 사용자명이 이미 사용 중이지 않은지 확인한 후 새 사용자
    레코드를 생성합니다.

    Args:
        request: 사용자명, 이메일, 비밀번호, 감사 로깅을 위한
            원본 클라이언트 IP를 포함하는 회원가입 페이로드.

    Returns:
        성공 메시지와 생성된 사용자의 id, username, email, role이
        포함된 ``AuthResponse``.

    Raises:
        HTTPException: 이메일 또는 사용자명이 이미 등록된 경우
            400.
        HTTPException: 예기치 않은 데이터베이스 또는 서버 오류 시
            500.
    """

    logger.info("auth_signup() from client_ip=%s email=%s", request.client_ip, request.email)
    try:
        # 단계 1: 데이터베이스 세션을 생성합니다
        db = SessionLocal()
        try:
            # 단계 2: 이메일 중복 검증 — 동일 이메일이 이미 등록되어 있는지 확인합니다
            if get_user_by_email(db, request.email):
                logger.warning(
                    "auth_signup() duplicate email from client_ip=%s email=%s",
                    request.client_ip, request.email,
                )
                raise HTTPException(status_code=400, detail="User with this email already exists")
            # 단계 3: 사용자명 중복 검증 — 동일 사용자명이 이미 등록되어 있는지 확인합니다
            if get_user_by_username(db, request.username):
                logger.warning(
                    "auth_signup() duplicate username from client_ip=%s username=%s",
                    request.client_ip, request.username,
                )
                raise HTTPException(status_code=400, detail="User with this username already exists")

            # 단계 4: 새 사용자 레코드를 생성합니다 (비밀번호는 해싱되어 저장)
            user = create_user(db, request.username, request.email, request.password)
            logger.info("auth_signup() user created: id=%s client_ip=%s", user.id, request.client_ip)
            # 단계 5: 생성된 사용자 정보를 응답으로 반환합니다
            return AuthResponse(
                message="User created successfully",
                user={"id": user.id, "username": user.username, "email": user.email, "role": user.role},
            )
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("auth_signup() failed from client_ip=%s: %s", request.client_ip, error)
        raise HTTPException(status_code=500, detail="Internal server error") from error


@app.post("/api/auth/login", response_model=TokenAuthResponse)
async def auth_login(request: LoginRequest) -> TokenAuthResponse:
    """사용자를 인증하고 JWT 토큰을 반환합니다.

    **POST /api/auth/login**

    제공된 이메일/비밀번호 조합을 검증하고, 계정이 활성 상태인지
    확인한 후 서명된 JWT를 발급합니다.

    Args:
        request: 이메일, 비밀번호, 감사 로깅을 위한 원본
            클라이언트 IP를 포함하는 로그인 페이로드.

    Returns:
        성공 메시지, 사용자 상세 정보, 서명된 JWT 액세스 토큰이
        포함된 ``TokenAuthResponse``.

    Raises:
        HTTPException: 이메일을 찾을 수 없거나 비밀번호가
            일치하지 않는 경우 401.
        HTTPException: 계정이 비활성화된 경우 403.
        HTTPException: 예기치 않은 서버 오류 시 500.
    """

    logger.info("auth_login() from client_ip=%s email=%s", request.client_ip, request.email)
    try:
        # 단계 1: 데이터베이스 세션을 생성합니다
        db = SessionLocal()
        try:
            # 단계 2: 이메일로 사용자를 조회합니다
            user = get_user_by_email(db, request.email)
            # 단계 3: 사용자 존재 여부 및 비밀번호 해시 유효성을 확인합니다
            if not user or not user.password_hash:
                logger.warning(
                    "auth_login() invalid credentials from client_ip=%s email=%s",
                    request.client_ip, request.email,
                )
                raise HTTPException(status_code=401, detail="Invalid email or password")

            # 단계 4: 입력된 비밀번호와 저장된 해시를 비교하여 인증합니다
            if not verify_password(request.password, user.password_hash):
                logger.warning(
                    "auth_login() wrong password from client_ip=%s email=%s",
                    request.client_ip, request.email,
                )
                raise HTTPException(status_code=401, detail="Invalid email or password")

            # 단계 5: 계정 활성화 상태를 확인합니다 (비활성 계정은 로그인 차단)
            if not user.is_active:
                logger.warning(
                    "auth_login() disabled account from client_ip=%s email=%s",
                    request.client_ip, request.email,
                )
                raise HTTPException(status_code=403, detail="Account is disabled")

            # 단계 6: 인증 성공 — 사용자 정보를 포함한 JWT 토큰을 생성합니다
            token = create_jwt_token(user.id, user.email, user.role)
            logger.info("auth_login() successful for user_id=%s client_ip=%s", user.id, request.client_ip)
            # 단계 7: JWT 토큰과 사용자 정보를 응답으로 반환합니다
            return TokenAuthResponse(
                message="Login successful",
                user={"id": user.id, "username": user.username, "email": user.email, "role": user.role},
                token=token,
            )
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("auth_login() failed from client_ip=%s: %s", request.client_ip, error)
        raise HTTPException(status_code=500, detail="Internal server error") from error


# ── 관리자 의존성 ─────────────────────────────────────────────────────────────
# 관리자 전용 엔드포인트에 대한 역할 기반 접근 제어(RBAC) 의존성 함수


async def require_admin(authorization: str = Header(None)) -> dict:
    """JWT Bearer 토큰을 통해 호출자가 관리자인지 확인합니다.

    관리자 전용 엔드포인트에서 FastAPI 의존성으로 사용하기 위한
    함수입니다.

    Args:
        authorization: HTTP ``Authorization`` 헤더 값,
            ``Bearer <token>`` 형식이어야 합니다.

    Returns:
        최소한 ``user_id``와 ``role`` 클레임을 포함하는 디코딩된
        JWT 페이로드 딕셔너리.

    Raises:
        HTTPException: 헤더가 누락되었거나 형식이 잘못된 경우
            401.
        HTTPException: 토큰은 유효하지만 역할이 ``"admin"``이
            아닌 경우 403.
    """

    logger.debug("require_admin() checking authorization header")
    # Authorization 헤더의 존재 여부와 Bearer 형식을 검증합니다
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("require_admin() rejected: missing or invalid authorization header")
        raise HTTPException(status_code=401, detail="Not authenticated")
    # Bearer 접두어를 제거하고 순수 JWT 토큰을 추출합니다
    token = authorization.split(" ", 1)[1]
    # JWT 토큰을 디코딩하여 페이로드(user_id, role 등)를 얻습니다
    payload = decode_jwt_token(token)
    # 토큰이 유효하고 역할이 admin인지 확인합니다 (관리자가 아니면 403 거부)
    if not payload or payload.get("role") != "admin":
        logger.warning(
            "require_admin() rejected: insufficient role, payload_role=%s",
            payload.get("role") if payload else None,
        )
        raise HTTPException(status_code=403, detail="Admin access required")
    logger.info("require_admin() authorized: user_id=%s, role=%s", payload.get("user_id"), payload.get("role"))
    return payload


# ── 관리자 사용자 관리 ─────────────────────────────────────────────────────────


@app.get("/api/admin/users", response_model=list[AdminUserResponse])
async def admin_list_users(caller: dict = Depends(require_admin)) -> list[AdminUserResponse]:
    """등록된 모든 사용자를 반환합니다 (관리자 전용).

    **GET /api/admin/users**

    Args:
        caller: ``require_admin`` 의존성에 의해 주입된 인증된
            관리자의 JWT 페이로드.

    Returns:
        시스템의 모든 사용자를 나타내는
        ``AdminUserResponse`` 객체 목록.
    """

    logger.info("admin_list_users() request received: caller_user_id=%s", caller.get("user_id"))
    db = SessionLocal()
    try:
        users = get_all_users(db)
        logger.info("admin_list_users() returning %d users", len(users))
        return [
            AdminUserResponse(
                id=u.id,
                username=u.username,
                email=u.email or "",
                role=u.role,
                is_active=u.is_active,
                created_at=u.created_at.isoformat() if u.created_at else "",
            )
            for u in users
        ]
    finally:
        db.close()


@app.put("/api/admin/users/{user_id}", response_model=AdminUserResponse)
async def admin_update_user(
    user_id: str,
    body: AdminUpdateUserRequest,
    caller: dict = Depends(require_admin),
) -> AdminUserResponse:
    """사용자의 이메일, 비밀번호 또는 역할을 수정합니다 (관리자 전용).

    **PUT /api/admin/users/{user_id}**

    요청 본문에 포함된 필드만 수정되며, 생략된 필드는 변경되지
    않습니다.

    Args:
        user_id: 대상 사용자의 고유 식별자 (경로 매개변수).
        body: 선택적 ``email``, ``password``, ``role`` 필드를
            포함하는 ``AdminUpdateUserRequest``.
        caller: ``require_admin`` 의존성에 의해 주입된 인증된
            관리자의 JWT 페이로드.

    Returns:
        업데이트된 사용자 상태를 반영하는
        ``AdminUserResponse``.

    Raises:
        HTTPException: 제공된 역할이 ``"user"`` 또는
            ``"admin"``이 아닌 경우 400.
        HTTPException: 해당 ID의 사용자가 존재하지 않는 경우
            404.
        HTTPException: 예기치 않은 서버 오류 시 500.
    """

    logger.info(
        "admin_update_user() request received: target_user_id=%s, caller_user_id=%s",
        user_id,
        caller.get("user_id"),
    )
    db = SessionLocal()
    try:
        user = get_user_by_id(db, user_id)
        if not user:
            logger.warning("admin_update_user() user not found: user_id=%s", user_id)
            raise HTTPException(status_code=404, detail="User not found")

        updates: dict[str, str | int] = {}
        if body.email is not None:
            updates["email"] = body.email
        if body.password is not None:
            updates["password"] = body.password
        if body.role is not None:
            if body.role not in ("user", "admin"):
                raise HTTPException(status_code=400, detail="Role must be 'user' or 'admin'")
            updates["role"] = body.role
        if body.is_active is not None:
            if body.is_active not in (0, 1):
                raise HTTPException(status_code=400, detail="is_active must be 0 or 1")
            updates["is_active"] = body.is_active

        if updates:
            logger.info("admin_update_user() applying updates: user_id=%s, fields=%s", user_id, list(updates.keys()))
            user = update_user(db, user, **updates)
            logger.info("admin_update_user() update applied successfully: user_id=%s", user_id)

        return AdminUserResponse(
            id=user.id,
            username=user.username,
            email=user.email or "",
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at.isoformat() if user.created_at else "",
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("admin_update_user() failed: %s", error)
        raise HTTPException(status_code=500, detail="Internal server error") from error
    finally:
        db.close()


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: str, caller: dict = Depends(require_admin)) -> dict[str, str]:
    """ID로 사용자를 삭제합니다 (관리자 전용).

    **DELETE /api/admin/users/{user_id}**

    호출자는 자신의 계정을 삭제할 수 없습니다.

    Args:
        user_id: 대상 사용자의 고유 식별자 (경로 매개변수).
        caller: ``require_admin`` 의존성에 의해 주입된 인증된
            관리자의 JWT 페이로드.

    Returns:
        삭제를 확인하는 ``message`` 키를 가진 딕셔너리.

    Raises:
        HTTPException: 호출자가 자기 자신을 삭제하려는 경우
            400.
        HTTPException: 해당 ID의 사용자가 존재하지 않는 경우
            404.
        HTTPException: 예기치 않은 서버 오류 시 500.
    """

    logger.info(
        "admin_delete_user() request received: target_user_id=%s, caller_user_id=%s",
        user_id,
        caller.get("user_id"),
    )
    if user_id == caller.get("user_id"):
        logger.warning("admin_delete_user() rejected: cannot delete self, user_id=%s", user_id)
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    db = SessionLocal()
    try:
        user = get_user_by_id(db, user_id)
        if not user:
            logger.warning("admin_delete_user() user not found: user_id=%s", user_id)
            raise HTTPException(status_code=404, detail="User not found")
        delete_user(db, user)
        logger.info("admin_delete_user() user deleted successfully: user_id=%s, username=%s", user_id, user.username)
        return {"message": "User deleted"}
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("admin_delete_user() failed: %s", error)
        raise HTTPException(status_code=500, detail="Internal server error") from error
    finally:
        db.close()


# ── JWT 인증 헬퍼 ─────────────────────────────────────────────────────────────


async def get_current_user_id(authorization: str = Header(None)) -> str:
    """Authorization 헤더에서 JWT를 검증하고 user_id를 추출합니다.

    Args:
        authorization: HTTP ``Authorization`` 헤더 값 (``Bearer <token>`` 형식).

    Returns:
        JWT 페이로드에 포함된 ``user_id`` 문자열.

    Raises:
        HTTPException: 401 — 토큰이 없거나 유효하지 않은 경우.
    """
    # Authorization 헤더의 존재 여부와 Bearer 형식을 검증합니다
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    # Bearer 접두어를 분리하여 순수 JWT 토큰 문자열을 추출합니다
    token = authorization.split(" ", 1)[1]
    # JWT 토큰을 디코딩하고 서명 및 만료를 검증합니다
    payload = decode_jwt_token(token)
    # 디코딩 실패 시 (만료, 위변조 등) 401 인증 오류를 반환합니다
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    # 페이로드에서 user_id 클레임을 추출하여 반환합니다
    return payload["user_id"]


# ── 대화 관리 API ─────────────────────────────────────────────────────────────


@app.get("/api/conversations", response_model=PaginatedConversations)
async def list_conversations(
    user_id: str = Depends(get_current_user_id),
    page: int = 1,
    page_size: int = 10,
    from_date: str | None = None,
    to_date: str | None = None,
) -> PaginatedConversations:
    """인증된 사용자의 대화 목록을 페이지네이션하여 반환합니다.

    **GET /api/conversations**

    Args:
        user_id: JWT에서 추출한 사용자 ID.
        page: 페이지 번호 (기본값 1).
        page_size: 페이지당 항목 수 (기본값 10).
        from_date: 시작 날짜 필터 (YYYY-MM-DD).
        to_date: 종료 날짜 필터 (YYYY-MM-DD).

    Returns:
        ``PaginatedConversations`` (items, total, page, page_size).
    """
    logger.info(
        "list_conversations() user_id=%s page=%d page_size=%d from=%s to=%s",
        user_id, page, page_size, from_date, to_date,
    )
    db = SessionLocal()
    try:
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import or_

        # 단계 1: 기본 쿼리 구성 — 해당 사용자의 active 및 NULL 상태 대화만 조회합니다
        # archived/deleted 상태의 대화는 제외합니다
        query = (
            db.query(Conversation)
            .filter(
                Conversation.user_id == user_id,
                or_(
                    Conversation.status == "active",
                    Conversation.status.is_(None),
                ),
            )
        )

        # 단계 2: 시작 날짜 필터 — YYYY-MM-DD 형식의 시작 날짜 이후 대화만 포함합니다
        if from_date:
            try:
                dt_from = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)  # UTC 기준 시작 시각
                query = query.filter(Conversation.created_at >= dt_from)
            except ValueError:
                pass  # 잘못된 날짜 형식은 무시합니다

        # 단계 3: 종료 날짜 필터 — YYYY-MM-DD 형식의 종료 날짜까지 대화를 포함합니다
        if to_date:
            try:
                dt_to = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)  # UTC 기준 종료 시각
                # 종료 날짜의 다음 날 00:00까지 포함 (해당 날짜의 모든 시간대 포함)
                dt_to = dt_to + timedelta(days=1)
                query = query.filter(Conversation.created_at < dt_to)
            except ValueError:
                pass  # 잘못된 날짜 형식은 무시합니다

        # 단계 4: 페이지네이션 — 전체 개수를 조회하고 요청된 페이지의 결과를 가져옵니다
        total = query.count()  # 필터 조건에 맞는 전체 대화 수
        conversations = (
            query.order_by(Conversation.created_at.desc())  # 최신 대화가 먼저 오도록 정렬
            .offset((max(page, 1) - 1) * page_size)  # 페이지 오프셋 계산 (1-기반 페이지 번호)
            .limit(page_size)  # 페이지당 항목 수 제한
            .all()
        )

        # 단계 5: 응답 구성 — 각 대화에 대한 메시지 수를 포함한 요약 목록을 생성합니다
        items = []
        for conv in conversations:
            msg_count = db.query(Message).filter(  # 해당 대화의 메시지 수를 조회합니다
                Message.conversation_id == conv.id
            ).count()
            items.append(
                ConversationSummary(
                    id=conv.id,
                    title=conv.title,
                    azure_conversation_id=conv.azure_conversation_id,
                    created_at=conv.created_at.isoformat() if conv.created_at else "",
                    message_count=msg_count,
                )
            )
        logger.info(
            "list_conversations() returning %d/%d conversations (page %d)",
            len(items), total, page,
        )
        return PaginatedConversations(
            items=items, total=total, page=page, page_size=page_size,
        )
    finally:
        db.close()


@app.get("/api/conversations/{conversation_id}/messages", response_model=ConversationDetail)
async def get_conversation_messages(
    conversation_id: str,
    user_id: str = Depends(get_current_user_id),
) -> ConversationDetail:
    """대화의 메시지 목록을 반환합니다.

    **GET /api/conversations/{conversation_id}/messages**

    Args:
        conversation_id: 조회할 대화의 UUID.
        user_id: JWT에서 추출한 사용자 ID.

    Returns:
        메시지가 포함된 ``ConversationDetail``.

    Raises:
        HTTPException: 404 — 대화를 찾을 수 없거나 권한이 없는 경우.
    """
    logger.info("get_conversation_messages() conversation_id=%s, user_id=%s", conversation_id, user_id)
    db = SessionLocal()
    try:
        conv = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .first()
        )
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        messages = (
            db.query(Message)
            .filter(Message.conversation_id == conv.id)
            .order_by(Message.created_at.asc())
            .all()
        )
        return ConversationDetail(
            id=conv.id,
            title=conv.title,
            azure_conversation_id=conv.azure_conversation_id,
            created_at=conv.created_at.isoformat() if conv.created_at else "",
            messages=[
                MessageDetail(
                    id=m.id,
                    role=m.role,
                    content=m.content,
                    created_at=m.created_at.isoformat() if m.created_at else "",
                )
                for m in messages
            ],
        )
    finally:
        db.close()


@app.patch("/api/conversations/{conversation_id}/hide")
async def hide_conversation(
    conversation_id: str,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """대화를 숨깁니다 (status='archived'). DB에서 삭제하지 않습니다.

    **PATCH /api/conversations/{conversation_id}/hide**

    Args:
        conversation_id: 숨길 대화의 UUID.
        user_id: JWT에서 추출한 사용자 ID.

    Returns:
        성공 메시지.

    Raises:
        HTTPException: 404 — 대화를 찾을 수 없거나 권한이 없는 경우.
    """
    logger.info(
        "hide_conversation() conversation_id=%s, user_id=%s",
        conversation_id, user_id,
    )
    db = SessionLocal()
    try:
        conv = (
            db.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
            .first()
        )
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conv.status = "archived"
        db.commit()
        logger.info("hide_conversation() archived conversation_id=%s", conversation_id)
        return {"status": "ok", "message": "Conversation hidden"}
    except HTTPException:
        raise
    except Exception as error:
        db.rollback()
        logger.exception("hide_conversation() failed: %s", error)
        raise HTTPException(status_code=500, detail="Failed to hide conversation") from error
    finally:
        db.close()


@app.post("/api/conversations", response_model=ConversationDetail, status_code=201)
async def save_conversation(
    body: SaveConversationRequest,
    user_id: str = Depends(get_current_user_id),
) -> ConversationDetail:
    """대화를 저장합니다 (azure_conversation_id 기준 upsert).

    **POST /api/conversations**

    동일한 azure_conversation_id가 이미 존재하면 기존 대화를 업데이트하고,
    없으면 새로 생성합니다. 감사 목적으로 DB 레코드를 보존합니다.

    Args:
        body: 대화 제목, Azure conversation ID, 메시지 목록을 포함한 요청.
        user_id: JWT에서 추출한 사용자 ID.

    Returns:
        저장된 대화의 ``ConversationDetail``.

    Raises:
        HTTPException: 500 — 저장 중 오류 발생 시.
    """
    logger.info(
        "save_conversation() user_id=%s, title=%s, message_count=%d, azure_conv_id=%s",
        user_id, body.title, len(body.messages), body.conversation_id,
    )
    db = SessionLocal()
    try:
        # 단계 1: 기존 대화 조회 — azure_conversation_id로 동일 대화가 이미 존재하는지 확인합니다
        existing_conv = None
        if body.conversation_id:
            existing_conv = (
                db.query(Conversation)
                .filter(
                    Conversation.azure_conversation_id == body.conversation_id,
                    Conversation.user_id == user_id,
                )
                .first()
            )

        if existing_conv:
            # 단계 2a: 기존 대화 업데이트 (Upsert) — 제목을 갱신하고 기존 메시지를 삭제 후 재생성합니다
            logger.info(
                "save_conversation() upsert: updating existing conv_id=%s",
                existing_conv.id,
            )
            existing_conv.title = body.title or existing_conv.title  # 새 제목이 있으면 갱신
            existing_conv.status = "active"  # 숨겨진 대화를 다시 활성화합니다
            # 기존 메시지를 모두 삭제합니다 (새 메시지 목록으로 교체)
            db.query(Message).filter(
                Message.conversation_id == existing_conv.id
            ).delete()
            conv = existing_conv
        else:
            # 단계 2b: 새 대화 생성 — 새로운 Conversation 레코드를 데이터베이스에 추가합니다
            conv = Conversation(
                user_id=user_id,
                title=body.title,
                azure_conversation_id=body.conversation_id,
            )
            db.add(conv)
            db.flush()  # ID 자동 생성을 위해 즉시 플러시합니다

        # 단계 3: 메시지 저장 — 요청의 모든 메시지를 새 Message 레코드로 생성합니다
        created_messages: list[Message] = []
        for msg in body.messages:
            m = Message(
                conversation_id=conv.id,
                role=msg.get("role", "user"),
                content=msg.get("content", ""),
            )
            db.add(m)
            created_messages.append(m)

        # 단계 4: 트랜잭션 커밋 — 모든 변경사항을 데이터베이스에 반영합니다
        db.commit()
        db.refresh(conv)  # 커밋 후 생성된 타임스탬프 등을 갱신합니다
        for m in created_messages:
            db.refresh(m)  # 각 메시지의 자동 생성 필드를 갱신합니다

        logger.info("save_conversation() saved conversation_id=%s", conv.id)
        return ConversationDetail(
            id=conv.id,
            title=conv.title,
            azure_conversation_id=conv.azure_conversation_id,
            created_at=conv.created_at.isoformat() if conv.created_at else "",
            messages=[
                MessageDetail(
                    id=m.id,
                    role=m.role,
                    content=m.content,
                    created_at=m.created_at.isoformat() if m.created_at else "",
                )
                for m in created_messages
            ],
        )
    except Exception as error:
        db.rollback()
        logger.exception("save_conversation() failed: %s", error)
        raise HTTPException(status_code=500, detail="Failed to save conversation") from error
    finally:
        db.close()


@app.post("/api/speech/transcribe", response_model=TranscriptionResponse)
async def speech_transcribe(request: TranscriptionRequest) -> TranscriptionResponse:
    """Azure Speech Services를 사용하여 오디오를 텍스트로 변환합니다.

    **POST /api/speech/transcribe**

    base64로 인코딩된 오디오 페이로드를 디코딩하고, 필요 시 WAV로
    변환한 후 Azure Speech 배치 전사에 제출합니다.

    Args:
        request: base64 오디오 데이터, MIME 타입, 선택적 파일명,
            대상 언어를 포함하는 ``TranscriptionRequest``.

    Returns:
        전사된 텍스트와 사용된 언어가 포함된
        ``TranscriptionResponse``.

    Raises:
        HTTPException: 오디오를 디코딩할 수 없거나 전사 서비스가
            오류를 반환한 경우 400.
    """
    logger.info(
        "speech_transcribe() request received: mime_type=%s, file_name=%s, language=%s, audio_base64_length=%d",
        request.mime_type,
        request.file_name,
        request.language,
        len(request.audio_base64) if request.audio_base64 else 0,
    )
    try:
        audio_bytes = speech_transcriber.decode_base64_audio(request.audio_base64)
        logger.info("speech_transcribe() audio decoded: size_bytes=%d", len(audio_bytes))
        transcript = await speech_transcriber.transcribe_audio_bytes(
            audio_bytes,
            mime_type=request.mime_type,
            file_name=request.file_name,
            language=request.language,
        )
    except RuntimeError as error:
        logger.warning("speech_transcribe() failed: %s", error)
        raise HTTPException(status_code=400, detail=str(error)) from error

    response = TranscriptionResponse(text=transcript, language=request.language)
    logger.info(
        "speech_transcribe() completed successfully: transcription_text=%s, language=%s",
        transcript,
        request.language,
    )
    return response



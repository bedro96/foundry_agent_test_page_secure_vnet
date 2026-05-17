"""structlog을 사용한 구조화된 로깅 설정.

``APP_ENV``에 기반하여 프로세스 전체 로깅을 설정하는
``configure_logging``을 제공합니다 (백엔드 ``.env`` 파일에서).

*  **프로덕션** — INFO 레벨, 콘솔 **및** 파일에 JSON 출력.
*  **개발** — DEBUG 레벨, 추가 호출 위치 정보 (module, lineno)와 함께
   콘솔 **및** 파일에 JSON 출력.

파일 로그는 ``logs/app_log_YYYYMMDD.log``에 일별 로테이션으로 기록됩니다.
"""

# ──────────────────────────────────────────────────
# 표준 라이브러리 임포트
# ──────────────────────────────────────────────────
from __future__ import annotations

import json  # 요청 본문(JSON) 파싱에 사용
import logging  # 파이썬 기본 로깅 프레임워크
import logging.handlers  # TimedRotatingFileHandler 등 핸들러 모음
import os  # 디렉터리 생성 등 OS 유틸리티
import sys  # stdout 스트림 참조용
import time  # 요청 처리 시간 측정 (monotonic clock)
from collections.abc import Awaitable, Callable  # 비동기 콜백 타입 힌트
from datetime import datetime  # 로그 파일명에 날짜 포매팅

# ──────────────────────────────────────────────────
# 서드파티 라이브러리 임포트
# ──────────────────────────────────────────────────
import structlog  # 구조화된 로깅 라이브러리 (JSON 출력 지원)
from fastapi import Request  # FastAPI 요청 객체
from starlette.middleware.base import BaseHTTPMiddleware  # 미들웨어 기반 클래스
from starlette.responses import Response  # HTTP 응답 객체
from structlog.stdlib import ProcessorFormatter  # stdlib 로거와 structlog 연동 포매터

# ──────────────────────────────────────────────────
# 프로젝트 내부 모듈 임포트
# ──────────────────────────────────────────────────
from app.config import Settings  # noqa: F401 — backward-compat re-export

# 파일 핸들러에 사용되는 로그 포맷 문자열
# 형식: [시각] | 로그레벨 | 로거이름 | 모듈명:줄번호 | 메시지
FILE_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | %(module)s:%(lineno)d | %(message)s"
)


class HealthLogFilter(logging.Filter):
    """헬스 체크 엔드포인트에 대한 uvicorn 접근 로그를 억제하는 필터.

    Kubernetes, Azure Container Apps 등의 오케스트레이터는 /health/live 및
    /health/ready를 주기적으로 호출하여 대량의 반복 로그를 생성합니다.
    이 필터는 해당 노이즈를 제거하여 실제 비즈니스 로그만 남기도록 합니다.
    ``log_keepalive=True``이면 필터링 없이 모든 로그를 통과시킵니다.
    """

    def __init__(self, log_keepalive: bool):
        """필터를 초기화합니다.

        Args:
            log_keepalive: False이면 헬스 엔드포인트 로그가 억제됩니다.
        """
        super().__init__()
        self.log_keepalive = log_keepalive  # True: 헬스 로그 유지, False: 억제

    def filter(self, record: logging.LogRecord) -> bool:
        """로그 레코드를 필터링합니다.

        Args:
            record: 필터링할 로그 레코드.

        Returns:
            레코드를 억제해야 하면 ``False``, 그렇지 않으면 ``True``.
        """
        if not self.log_keepalive:
            message = record.getMessage()  # 로그 레코드에서 실제 메시지 문자열을 추출
            # 헬스 체크 경로가 포함된 메시지는 억제합니다
            if "/health/live" in message or "/health/ready" in message:
                return False
        return True


class AccessLogMiddleware(BaseHTTPMiddleware):
    """uvicorn의 plain-text 접근 로그를 대체하는 구조화된 JSON 접근 로그 미들웨어.

    풍부한 컨텍스트 필드와 함께 모든 HTTP 요청/응답을 로깅하여
    Log Analytics에서 직접 쿼리할 수 있도록 합니다.

    로깅되는 필드:
        - client_ip: 클라이언트 IP 주소
        - method: HTTP 메서드 (GET, POST 등)
        - path: 요청 경로
        - status_code: 응답 상태 코드
        - duration_ms: 요청 처리 소요 시간 (밀리초)
        - user_agent: 클라이언트 User-Agent 헤더
        - query: 쿼리 문자열 (있는 경우)
        - email: 인증 요청 시 이메일 (감사 로깅용)
    """

    # 헬스 체크 경로 집합 — 이 경로들은 오케스트레이터(K8s, ACA)가
    # 주기적으로 호출하므로, 설정에 따라 로그에서 제외할 수 있습니다
    _HEALTH_PATHS = {"/health/live", "/health/ready"}

    def __init__(self, app: object, *, log_keepalive: bool = True) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._log_keepalive = log_keepalive  # 헬스 체크 로그 포함 여부 플래그
        self._slog = structlog.get_logger("access")  # 접근 로그 전용 structlog 로거

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """요청/응답을 가로채고 구조화된 JSON 접근 로그 라인을 발행합니다."""
        # 1단계: 요청 경로를 추출합니다
        path = request.url.path

        # 2단계: 구성된 경우 헬스 엔드포인트 건너뛰기 (불필요한 로그 노이즈 방지)
        if not self._log_keepalive and path in self._HEALTH_PATHS:
            return await call_next(request)

        # 3단계: 요청 시작 시각을 기록합니다 (monotonic clock으로 정확한 경과 시간 측정)
        start = time.monotonic()
        # 4단계: 로그에 포함할 요청 메타데이터를 수집합니다
        client_ip = request.client.host if request.client else "unknown"  # 클라이언트 IP 주소
        method = request.method  # HTTP 메서드 (GET, POST, PUT 등)
        query = str(request.url.query) if request.url.query else ""  # URL 쿼리 문자열
        user_agent = request.headers.get("user-agent", "")  # 브라우저/클라이언트 정보

        # 5단계: 감사 로깅을 위해 인증 요청 본문에서 이메일 추출
        email: str | None = None
        if path.startswith("/api/auth/") and method == "POST":
            try:
                body_bytes = await request.body()  # 요청 본문을 바이트로 읽기
                body_json = json.loads(body_bytes)  # JSON으로 파싱
                email = body_json.get("email")  # 이메일 필드 추출
            except Exception:
                pass  # 파싱 실패 시 무시 — 로깅이 요청 처리를 방해하면 안 됩니다

        # 6단계: 기본 상태 코드를 500으로 설정 (예외 발생 시 서버 오류로 기록)
        status_code = 500
        try:
            # 7단계: 다음 미들웨어 또는 라우트 핸들러를 호출하여 실제 응답을 받습니다
            response = await call_next(request)
            status_code = response.status_code  # 실제 응답 상태 코드로 갱신
            return response
        except Exception:
            raise  # 예외를 다시 발생시켜 상위 핸들러에서 처리하도록 합니다
        finally:
            # 8단계: 응답 완료 후 경과 시간을 밀리초 단위로 계산합니다
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            # 9단계: 로그 데이터 딕셔너리를 구성합니다
            log_data: dict[str, object] = {
                "client_ip": client_ip,       # 클라이언트 IP
                "method": method,             # HTTP 메서드
                "path": path,                 # 요청 경로
                "status_code": status_code,   # 응답 상태 코드
                "duration_ms": duration_ms,   # 처리 소요 시간 (ms)
                "user_agent": user_agent,     # 사용자 에이전트 문자열
            }
            if query:
                log_data["query"] = query  # 쿼리 문자열이 있으면 추가
            if email:
                log_data["email"] = email  # 이메일이 추출되었으면 감사 로그에 추가

            # 10단계: 상태 코드에 따라 적절한 로그 레벨로 기록합니다
            if status_code >= 500:
                self._slog.error("http_request", **log_data)    # 서버 오류 — ERROR 레벨
            elif status_code >= 400:
                self._slog.warning("http_request", **log_data)  # 클라이언트 오류 — WARNING 레벨
            else:
                self._slog.info("http_request", **log_data)     # 정상 응답 — INFO 레벨


def configure_logging(settings: Settings) -> logging.Logger:
    """``settings.app_env``에 기반하여 프로세스 전체 로깅을 구성합니다.

    Args:
        settings: 환경 (프로덕션 vs. 개발), 로그 레벨 및
            로거 이름을 결정하는 데 사용되는 애플리케이션 설정.

    Returns:
        사용 준비가 완료된 애플리케이션별 ``logging.Logger`` 인스턴스.
    """

    # 환경에 따른 로그 레벨 결정: 개발 환경은 DEBUG, 프로덕션은 INFO
    is_development = settings.app_env != "production"
    level = logging.DEBUG if is_development else logging.INFO  # 로그 출력 레벨

    # 루트 로거를 초기화합니다 — 기존 핸들러를 제거하고 레벨을 설정
    root_logger = logging.getLogger()
    root_logger.handlers.clear()  # 중복 핸들러 방지를 위해 기존 핸들러 모두 제거
    root_logger.setLevel(level)

    # ─── 섹션 1: 일별 로테이션 파일 핸들러 ─────────────────────
    # 로그 파일을 일별로 생성하여 디스크 관리를 용이하게 합니다
    log_dir = "logs"  # 로그 파일이 저장될 디렉터리
    os.makedirs(log_dir, exist_ok=True)  # 디렉터리가 없으면 생성

    # 오늘 날짜 기반 로그 파일 경로 생성 (예: logs/app_log_20250101.log)
    log_filename = os.path.join(
        log_dir, f"app_log_{datetime.now().strftime('%Y%m%d')}.log"
    )
    # 일별 로테이션 파일 핸들러를 생성합니다 (자정마다 새 로그 파일 생성)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_filename,
        when="midnight",     # 자정에 로테이션
        interval=1,          # 1일 간격
        backupCount=0,       # 백업 파일 수 제한 없음 (외부 정리 정책 사용)
        encoding="utf-8",    # 한국어 등 유니코드 지원을 위한 UTF-8 인코딩
    )
    file_handler.suffix = "%Y%m%d"  # 로테이션된 파일의 접미사 형식
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt="[%X]"))  # 로그 포맷 적용
    root_logger.addHandler(file_handler)  # 루트 로거에 파일 핸들러 추가

    # ─── 섹션 2: structlog 공유 프로세서 체인 ─────────────────
    # structlog 로거와 외부(stdlib) 로그 레코드 모두에서 사용되는 프로세서.
    # filter_by_level은 structlog 자체 파이프라인에서만 안전하므로,
    # 이를 생략하는 foreign_pre_chain용 별도 목록을 유지합니다.
    common_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,             # contextvars에 바인딩된 키-값을 이벤트에 병합
        structlog.stdlib.add_logger_name,                    # 로거 이름(logger)을 이벤트 딕셔너리에 추가
        structlog.stdlib.add_log_level,                      # 로그 레벨(level)을 이벤트 딕셔너리에 추가
        structlog.stdlib.PositionalArgumentsFormatter(),     # 위치 인자를 문자열로 포매팅
        structlog.processors.TimeStamper(fmt="iso"),         # ISO 8601 형식의 타임스탬프 추가
        structlog.processors.StackInfoRenderer(),            # 스택 정보를 문자열로 렌더링
        structlog.processors.format_exc_info,                # 예외 정보를 포매팅하여 이벤트에 추가
        structlog.processors.UnicodeDecoder(),               # 바이트 문자열을 유니코드로 디코딩
    ]

    # 개발 환경에서는 호출 위치 정보 (모듈명, 줄번호)를 추가하여 디버깅을 용이하게 합니다
    if is_development:
        common_processors.insert(
            1,  # merge_contextvars 다음 위치에 삽입
            structlog.processors.CallsiteParameterAdder(
                [
                    structlog.processors.CallsiteParameter.MODULE,   # 호출된 모듈명
                    structlog.processors.CallsiteParameter.LINENO,   # 호출된 줄 번호
                ]
            ),
        )

    # structlog 전역 설정: 프로세서 체인, 로거 팩토리, 래퍼 클래스를 구성합니다
    structlog.configure(
        processors=[structlog.stdlib.filter_by_level]   # 레벨 미달 이벤트를 사전 필터링
        + common_processors                             # 공통 프로세서 체인 적용
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],  # stdlib 포매터로 전달하기 위한 래핑
        logger_factory=structlog.stdlib.LoggerFactory(),    # stdlib 로거를 백엔드로 사용
        wrapper_class=structlog.stdlib.BoundLogger,         # 바인딩된 로거 래퍼 클래스
        cache_logger_on_first_use=True,                    # 첫 사용 시 로거를 캐싱하여 성능 향상
    )

    # ─── 섹션 3: 콘솔 핸들러 — structlog을 통한 JSON 출력 ────
    # stdout으로 JSON 형식의 로그를 출력하여 컨테이너 환경에서 수집이 용이하도록 합니다
    console_formatter = ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),  # 최종 출력을 JSON 문자열로 렌더링
        foreign_pre_chain=common_processors,            # stdlib 로거의 레코드에도 동일한 프로세서 적용
    )
    console_handler = logging.StreamHandler(sys.stdout)  # stdout으로 출력하는 핸들러
    console_handler.setLevel(level)  # 환경에 따른 로그 레벨 적용
    console_handler.setFormatter(console_formatter)  # JSON 포매터 연결
    root_logger.addHandler(console_handler)  # 루트 로거에 콘솔 핸들러 추가

    # ─── 섹션 4: 서드파티 로거 레벨 억제 ─────────────────────
    # 과도하게 상세한 서드파티 로거를 억제하여 로그 노이즈를 줄입니다
    for name in (
        "uvicorn",                                          # uvicorn 웹 서버
        "uvicorn.error",                                    # uvicorn 에러 로거
        "httpx",                                            # HTTP 클라이언트 라이브러리
        "azure",                                            # Azure SDK 루트 로거
        "azure.core",                                       # Azure Core 라이브러리
        "azure.identity",                                   # Azure 인증 라이브러리
        "azure.core.pipeline.transport",                    # Azure HTTP 전송 계층
        "azure.core.pipeline.policies.http_logging_policy", # Azure HTTP 로깅 정책
        "azure.monitor.opentelemetry.export",               # Azure Monitor 텔레메트리 내보내기
    ):
        logging.getLogger(name).setLevel(level)  # 앱과 동일한 레벨로 설정

    # ─── 섹션 5: uvicorn 접근 로그 재구성 ────────────────────
    # uvicorn.access 핸들러를 제거하여 plain-text 출력 방지;
    # propagate=True로 설정하여 잔여 메시지가 root의 JSON formatter를 사용하도록 함
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers.clear()  # 기본 핸들러 제거 (plain-text 방지)
    uvicorn_access.propagate = True  # 루트 로거로 전파하여 JSON 포맷 사용
    uvicorn_access.setLevel(level)

    # ─── 섹션 6: 헬스 체크 로그 필터링 적용 ──────────────────
    # log_keepalive가 False일 때 헬스 체크 요청 로그를 필터링합니다
    if not settings.log_keepalive:
        uvicorn_access.addFilter(HealthLogFilter(settings.log_keepalive))

    # ─── 섹션 7: 애플리케이션 전용 로거 생성 및 반환 ─────────
    app_logger = logging.getLogger(settings.app_name)  # 앱 이름으로 전용 로거 생성
    app_logger.setLevel(level)
    app_logger.propagate = True  # 루트 로거의 핸들러도 함께 사용
    # 로깅 설정 완료를 디버그 레벨로 기록합니다
    app_logger.debug(
        "logging configured",
        extra={"app_env": settings.app_env, "level": logging.getLevelName(level)},
    )
    return app_logger

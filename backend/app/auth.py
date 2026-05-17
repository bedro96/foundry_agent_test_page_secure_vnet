"""API 키 인증 미들웨어 모듈.

프로덕션 환경에서 ``x-api-key`` 헤더를 검증하는 Starlette 미들웨어를 제공합니다.
프론트엔드에서 전송하는 API 키를 검증하여 무단 접근을 차단합니다.
비프로덕션 환경(development)에서는 인증을 건너뛰어 개발 편의성을 제공합니다.
"""

# 표준 라이브러리 임포트
import logging
from collections.abc import Awaitable, Callable  # 비동기 콜백 타입 힌트

# FastAPI/Starlette 임포트
from fastapi import Request  # HTTP 요청 객체
from starlette.middleware.base import BaseHTTPMiddleware  # 미들웨어 기본 클래스
from starlette.responses import JSONResponse, Response  # HTTP 응답 객체

# 애플리케이션 설정
from app.config import Settings

# 이 모듈의 로거 인스턴스 (인증 이벤트 추적용)
logger = logging.getLogger(__name__)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """``x-api-key`` 헤더 인증을 적용하는 Starlette 미들웨어.

    **프로덕션** (``APP_ENV=production``)에서 ``/api/*``에 대한 모든 요청은
    (``/api/auth/`` 및 ``/api/mcp/`` 제외) 유효한 API 키를 포함해야 합니다.
    비프로덕션 환경에서는 검사를 완전히 건너뜁니다.
    """

    def __init__(self, app, settings: Settings) -> None:
        """미들웨어를 초기화합니다.

        Args:
            app: 래핑할 ASGI 애플리케이션.
            settings: ``app_env`` 및 ``backend_api_key``를 읽는 데 사용되는
                애플리케이션 설정 인스턴스.
        """
        super().__init__(app)
        self._settings = settings  # 애플리케이션 설정 (app_env, backend_api_key 참조)
        # 인증 검사를 건너뛰는 경로 목록 (공개 엔드포인트)
        self._excluded_paths = {"/", "/health", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """수신 요청을 API 키 게이트를 통해 처리합니다.

        Args:
            request: 수신된 Starlette/FastAPI 요청.
            call_next: 요청을 다음 미들웨어 또는 라우트 핸들러로
                전달하는 콜백.

        Returns:
            ``Response`` — 성공 시 업스트림 응답 또는
            인증 실패 시 401/503 ``JSONResponse``.
        """
        logger.debug("Auth dispatch: method=%s path=%s", request.method, request.url.path)
        # CORS 프리플라이트(OPTIONS) 요청은 인증 없이 통과 — CORSMiddleware가 응답 처리
        if request.method == "OPTIONS":
            logger.debug("OPTIONS preflight request, passing through for CORS handling")
            return await call_next(request)

        # 공개 경로, 비-API 경로, 인증/MCP 경로는 인증 검사 제외
        if (
            request.url.path in self._excluded_paths
            or not request.url.path.startswith("/api")
            or request.url.path.startswith("/api/auth/")
            or request.url.path.startswith("/api/mcp/")
        ):
            logger.debug("Path excluded from auth check, passing through: %s", request.url.path)
            return await call_next(request)

        # 비프로덕션 환경에서는 API 키 인증을 건너뜀 (개발 편의성)
        if self._settings.app_env != "production":
            logger.debug(
                "Non-production environment (%s), skipping API key auth", self._settings.app_env
            )
            return await call_next(request)

        # 프로덕션에서 API 키가 설정되지 않은 경우 모든 요청 거부 (503)
        expected_api_key = self._settings.backend_api_key
        if not expected_api_key:
            logger.error(
                "APP_ENV=production but BACKEND_API_KEY is not configured — rejecting all API requests"
            )
            return JSONResponse(
                status_code=503,
                content={"detail": "API key authentication is not configured on the server."},
            )

        # 요청 헤더에서 x-api-key 값을 추출하여 기대값과 비교
        received_api_key = request.headers.get("x-api-key")
        if received_api_key == expected_api_key:
            # API 키 일치 — 요청을 다음 미들웨어/핸들러로 전달
            logger.info("API key validated successfully for path=%s", request.url.path)
            return await call_next(request)

        # API 키 불일치 또는 누락 — 401 Unauthorized 응답
        logger.warning("Invalid or missing API key for path=%s", request.url.path)
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key."},
        )

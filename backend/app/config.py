"""백엔드 애플리케이션 설정 모듈.

환경 변수와 ``.env`` 파일에서 Pydantic Settings를 통해
애플리케이션 구성을 로드하고 검증합니다. ``get_settings()``로
프로세스 전체에서 캐시된 싱글톤 설정 인스턴스를 제공합니다.
"""

# 표준 라이브러리 임포트
import logging
from functools import lru_cache  # 싱글톤 캐싱을 위한 데코레이터
from pathlib import Path  # 파일 경로 처리를 위한 유틸리티

# 서드파티 라이브러리 임포트
from dotenv import load_dotenv  # .env 파일에서 환경 변수 로드
from pydantic import AliasChoices, Field, field_validator  # 데이터 검증 및 필드 정의
from pydantic_settings import BaseSettings, SettingsConfigDict  # 환경 변수 기반 설정 관리

# BACKEND_DIR: backend/ 디렉터리의 절대 경로 (이 파일의 상위 2단계)
BACKEND_DIR = Path(__file__).resolve().parents[1]
# ENV_FILE: .env 파일의 전체 경로 (backend/.env)
ENV_FILE = BACKEND_DIR / ".env"

# .env 파일에서 환경 변수를 프로세스 환경에 로드 (기존 값 덮어쓰기)
load_dotenv(dotenv_path=ENV_FILE, override=True)

# 이 모듈의 로거 인스턴스 (설정 로드 상태 추적용)
logger = logging.getLogger(__name__)


def _log_env_file_status() -> None:
    """설정된 백엔드 .env 파일이 존재하는지 로깅합니다."""

    if ENV_FILE.exists():
        logger.debug("Environment file found at %s", ENV_FILE)
        return
    logger.warning(
        "Environment file not found at %s; continuing with process environment variables only",
        ENV_FILE,
    )



class Settings(BaseSettings):
    """환경 변수에서 로드되는 애플리케이션 설정.

    Attributes:
        app_name: 로그 및 헬스 응답에 사용되는 사람이 읽을 수 있는 서비스 식별자.
        app_env: 런타임 환경 (``"production"`` 또는 ``"development"``);
            인증 적용 및 로그 상세도를 제어합니다.
        backend_api_key: 프로덕션에서 ``/api/*`` 경로의 ``x-api-key`` 헤더
            인증을 위한 공유 비밀키.
        jwt_secret: 로그인 시 발급되는 JWT 토큰의 HMAC 서명 키.
        jwt_expiry_hours: 발급된 JWT 토큰의 유효 기간 (시간 단위).
        azure_ai_project_endpoint: Azure AI Foundry 프로젝트 엔드포인트 URL.
        azure_tenant_id: 서비스 주체 인증을 위한 Microsoft Entra ID 테넌트.
        azure_client_id: 서비스 주체 애플리케이션 (클라이언트) ID.
        azure_client_secret: 서비스 주체 클라이언트 비밀키.
        azure_speech_endpoint: 음성 변환을 위한 Azure Speech Services 엔드포인트.
        azure_speech_language: 음성 인식을 위한 BCP-47 언어 태그.
        backend_public_url: 이 백엔드의 공개적으로 접근 가능한 기본 URL.
        azure_ai_model: AI 에이전트가 사용하는 모델 배포 이름.
        azure_ai_agent_name: Azure Foundry에서 AI 에이전트의 표시 이름.
        azure_ai_agent_instructions: 에이전트의 시스템 프롬프트 지침.
        bing_grounding_connection_name: Bing 검색 그라운딩을 위한 Foundry 연결 이름.
        browser_automation_project_connection_id: 브라우저 자동화 도구를 위한
            Foundry 연결 ID.
        request_timeout_seconds: 업스트림 호출의 기본 HTTP 요청 타임아웃.
        enable_genai_tracing: GenAI 트레이싱 활성화 여부. true이면 LLM 호출에
            대한 OpenTelemetry 스팬이 자동 생성됩니다.
        capture_genai_message_content: 트레이스에 실제 프롬프트/응답 내용 포함 여부.
            프로덕션에서는 개인정보 보호를 위해 False 권장.
        mysql_host: MySQL 서버 호스트 이름.
        mysql_port: MySQL 서버 TCP 포트.
        mysql_db: MySQL 데이터베이스 / 스키마 이름.
        mysql_user: MySQL 로그인 사용자.
        mysql_password: MySQL 로그인 비밀번호.
        mysql_ssl_mode: SSL 적용 수준 (``"required"``, ``"preferred"``,
            ``"disabled"``).
        mysql_pool_size: SQLAlchemy 연결 풀 크기.
        mysql_charset: MySQL 연결에 사용되는 문자 집합.
        mysql_connect_timeout: 소켓 수준 연결 타임아웃 (초 단위).
    """

    app_name: str | None = None  # 자동 생성: AZURE_AI_AGENT_NAME + "_backend"
    app_env: str = Field(default="Production", validation_alias="APP_ENV")
    log_keepalive: bool = Field(
        default=True,
        validation_alias="LOG_KEEPALIVE",
    )  # False로 설정 시 /health/live, /health/ready 로그 억제

    @field_validator("app_env", mode="after")
    @classmethod
    def _normalize_app_env(cls, value: str) -> str:
        """APP_ENV를 소문자로 정규화하여 대소문자 구분 없이 비교합니다.

        Args:
            value: Pydantic 변환 후 ``APP_ENV``의 원시 값.

        Returns:
            소문자로 변환되고 공백이 제거된 환경 이름.
        """
        return value.strip().lower()
    backend_api_key: str | None = Field(
        default=None,
        validation_alias="BACKEND_API_KEY",
    )  # 프로덕션에서 /api/* 요청 인증을 위한 API 키; auth.py 미들웨어에서 사용
    jwt_secret: str = Field(
        default="change-me-in-production",
        validation_alias="JWT_SECRET",
    )  # JWT 토큰 서명을 위한 HMAC 비밀키; 예: "s3cret-k3y"
    jwt_expiry_hours: int = Field(
        default=24,
        validation_alias="JWT_EXPIRY_HOURS",
    )  # 토큰 유효 기간 (시간 단위); auth_service.create_jwt_token에서 사용
    azure_ai_project_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AZURE_AI_PROJECT_ENDPOINT", "AZURE_OPENAI_PROJECT_ENDPOINT"),
    )  # Azure AI Foundry 프로젝트 URL; agent_service에서 AI 클라이언트 생성에 사용
    azure_tenant_id: str | None = Field(
        default=None,
        validation_alias="AZURE_TENANT_ID",
    )  # 서비스 주체 인증을 위한 Entra ID 테넌트; 예: "72f988bf-..."
    azure_client_id: str | None = Field(
        default=None,
        validation_alias="AZURE_CLIENT_ID",
    )  # Azure 인증을 위한 서비스 주체 앱 ID
    azure_client_secret: str | None = Field(
        default=None,
        validation_alias="AZURE_CLIENT_SECRET",
    )  # Azure 인증을 위한 서비스 주체 비밀키
    azure_speech_endpoint: str | None = Field(
        default=None,
        validation_alias="AZURE_SPEECH_ENDPOINT",
    )  # 음성 변환을 위한 Azure Speech 엔드포인트; 토큰 발급에 사용
    azure_speech_region: str | None = Field(
        default=None,
        validation_alias="AZURE_SPEECH_REGION",
    )  # Azure Speech 리소스의 리전 코드; 리전 엔드포인트 URL 구성에 사용
    azure_speech_language: str = Field(
        default="ko-KR",
        validation_alias="AZURE_SPEECH_LANGUAGE",
    )  # 음성 인식을 위한 BCP-47 언어 코드; 예: "en-US", "ko-KR"
    backend_public_url: str | None = Field(
        default=None,
        validation_alias="BACKEND_PUBLIC_URL",
    )  # 이 백엔드의 공개 URL; 웹훅 콜백에 사용
    azure_ai_model: str = Field(
        default="gpt-4o",
        validation_alias=AliasChoices("AZURE_AI_MODEL_DEPLOYMENT_NAME", "AZURE_AI_MODEL", "MODEL_DEPLOYMENT_NAME"),
    )  # Azure AI Foundry의 모델 배포 이름; 예: "gpt-4o"
    azure_ai_agent_name: str = Field(
        default="lgit-chat-agent",
        validation_alias="AZURE_AI_AGENT_NAME",
    )  # Azure Foundry에서 AI 에이전트의 표시 이름
    azure_ai_agent_instructions: str = Field(
        default="You are a helpful AI Chat bot assistant.",
        validation_alias="AZURE_AI_AGENT_INSTRUCTIONS",
    )  # 에이전트 생성 시 전송되는 시스템 프롬프트 지침
    bing_grounding_connection_name: str | None = Field(
        default=None,
        validation_alias="BING_GROUNDING_CONNECTION_NAME",
    )  # Bing 검색 그라운딩 도구를 위한 Foundry 연결 이름
    browser_automation_project_connection_id: str | None = Field(
        default=None,
        validation_alias="BROWSER_AUTOMATION_PROJECT_CONNECTION_ID",
    )  # 브라우저 자동화 도구를 위한 Foundry 연결 ID
    request_timeout_seconds: float = Field(
        default=60.0,
        validation_alias="REQUEST_TIMEOUT_SECONDS",
    )  # 업스트림 요청의 기본 HTTP 타임아웃; 예: 60.0

    # ── 텔레메트리 설정 ─────────────────────────────────────────────────────
    enable_telemetry: bool = Field(
        default=True,
        validation_alias="ENABLE_TELEMETRY",
    )  # 텔레메트리 마스터 스위치; False 시 모든 OpenTelemetry 초기화를 건너뜁니다
    enable_genai_tracing: bool = Field(
        default=True,
        validation_alias="AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING",
    )  # GenAI 트레이싱 활성화 여부; true 시 LLM 호출 스팬을 자동 생성
    capture_genai_message_content: bool = Field(
        default=True,
        validation_alias="OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
    )  # 트레이스에 실제 메시지 내용 포함 여부; 프로덕션에서는 false 권장

    # MySQL 연결 설정
    mysql_host: str | None = Field(
        default=None,
        validation_alias="MYSQL_HOST",
    )  # MySQL 서버 호스트 이름; 예: "mydb.mysql.database.azure.com"
    mysql_port: int = Field(
        default=3306,
        validation_alias="MYSQL_PORT",
    )  # MySQL TCP 포트; 기본값 3306
    mysql_db: str | None = Field(
        default=None,
        validation_alias="MYSQL_DB",
    )  # MySQL 데이터베이스/스키마 이름; 예: "chatdb"
    mysql_user: str | None = Field(
        default=None,
        validation_alias="MYSQL_USER",
    )  # MySQL 로그인 사용자; 예: "adminuser"
    mysql_password: str | None = Field(
        default=None,
        validation_alias="MYSQL_PASSWORD",
    )  # MySQL 로그인 비밀번호
    mysql_ssl_mode: str = Field(
        default="required",
        validation_alias="MYSQL_SSL_MODE",
    )  # SSL 적용 수준: "required", "preferred", 또는 "disabled"
    mysql_pool_size: int = Field(
        default=5,
        validation_alias="MYSQL_POOL_SIZE",
    )  # SQLAlchemy 연결 풀 크기; 예상 동시성에 따라 조정
    mysql_charset: str = Field(
        default="utf8mb4",
        validation_alias="MYSQL_CHARSET",
    )  # MySQL 연결 문자 집합; "utf8mb4"는 전체 유니코드 지원
    mysql_connect_timeout: int = Field(
        default=10,
        validation_alias="MYSQL_CONNECT_TIMEOUT",
    )  # 소켓 수준 연결 타임아웃 (초 단위)

    # Pydantic Settings 모델 구성: .env 파일 경로, 인코딩, 정의되지 않은 추가 필드 무시
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),  # 환경 변수를 읽을 .env 파일 경로
        env_file_encoding="utf-8",  # .env 파일 인코딩 (한국어 지원을 위해 UTF-8)
        extra="ignore",  # .env에 정의되었지만 Settings에 없는 변수는 무시
    )

    def model_post_init(self, __context: object) -> None:
        """app_name이 미설정이면 AZURE_AI_AGENT_NAME + '_backend'로 자동 생성."""
        if not self.app_name:
            object.__setattr__(self, "app_name", f"{self.azure_ai_agent_name}_backend")

    @field_validator(
        "backend_api_key",
        "azure_ai_project_endpoint",
        "azure_tenant_id",
        "azure_client_id",
        "azure_client_secret",
        "azure_speech_endpoint",
        "backend_public_url",
        "bing_grounding_connection_name",
        "browser_automation_project_connection_id",
        "mysql_host",
        "mysql_db",
        "mysql_user",
        "mysql_password",
        mode="before",
    )
    @classmethod
    def _normalize_optional_strings(cls, value: str | None) -> str | None:
        """빈 선택적 환경 변수를 미설정으로 처리합니다.

        Args:
            value: 환경에서 가져온 원시 문자열 값 또는 ``None``.

        Returns:
            비어 있지 않은 경우 공백이 제거된 문자열, 그렇지 않으면 ``None``.
        """

        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """프로세스 수명 동안 캐시된 설정 객체를 반환합니다.

    Returns:
        첫 번째 호출 시 생성되고 이후 모든 호출에서
        ``@lru_cache``를 통해 캐시되는 싱글톤 ``Settings`` 인스턴스.
    """

    logger.debug("Loading application settings from %s", ENV_FILE)
    _log_env_file_status()
    settings = Settings()
    logger.info("Application settings loaded successfully")
    return settings

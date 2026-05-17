"""OpenTelemetry 기반 GenAI 텔레메트리 초기화 모듈.

Azure AI Foundry 에이전트의 실행 추적을 위해 OpenTelemetry를 구성하고,
Application Insights로 트레이스 데이터를 전송합니다.

주요 기능:
    - Azure Monitor (Application Insights)에 트레이스 데이터 자동 전송
    - AIProjectInstrumentor를 통한 에이전트 호출 자동 계측
    - GenAI 트레이싱을 위한 환경변수 자동 설정
"""

# ── 표준 라이브러리 임포트 ──────────────────────────────────────────────────
import logging
import os

# ── 프로젝트 내부 모듈 임포트 ───────────────────────────────────────────────
from app.config import Settings

logger = logging.getLogger(__name__)

# 텔레메트리 초기화 상태 추적 플래그
# 이 모듈 수준 변수는 configure_telemetry()가 중복 실행되지 않도록 보호하는 가드 역할을 합니다.
_telemetry_initialized = False  # 초기화 전에는 False, configure_telemetry() 성공 시 True로 전환


def configure_telemetry(settings: Settings) -> bool:
    """애플리케이션 시작 시 GenAI 텔레메트리 트레이싱을 초기화합니다.

    Azure AI Foundry 프로젝트에서 Application Insights 연결 문자열을 가져와
    Azure Monitor 익스포터를 설정하고, AIProjectInstrumentor로 에이전트
    호출을 자동 계측합니다.

    이 함수는 애플리케이션 수명주기 중 **한 번만** 호출되어야 합니다.
    중복 호출 시 기존 설정을 유지하고 무시합니다.

    Args:
        settings: 텔레메트리 관련 환경변수가 포함된 애플리케이션 설정 객체.

    Returns:
        텔레메트리가 정상적으로 초기화되었으면 True, 그렇지 않으면 False.
    """
    global _telemetry_initialized  # noqa: PLW0603  # 모듈 수준 플래그를 함수 내에서 변경하기 위해 global 선언

    # 이미 초기화된 경우 중복 설정을 방지하고 즉시 반환합니다
    if _telemetry_initialized:
        logger.info("텔레메트리가 이미 초기화되어 있습니다. 중복 호출을 무시합니다.")
        return True

    # 설정에서 GenAI 트레이싱 활성화 여부를 확인합니다
    if not settings.enable_genai_tracing:
        logger.info("GenAI 트레이싱이 비활성화되어 있습니다 (AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=false)")
        return False

    # ── 1단계: SDK가 인식할 수 있도록 환경변수를 os.environ에 설정 ──────────
    # Azure AI SDK는 런타임에 os.environ을 읽어 트레이싱 동작을 결정하므로,
    # Settings 값을 실제 환경변수로 반영해야 합니다.
    os.environ["AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING"] = "true"  # GenAI 트레이싱 활성화 플래그
    if settings.capture_genai_message_content:
        # 프롬프트/응답 본문까지 캡처하여 디버깅에 활용할 수 있도록 설정합니다
        os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "true"
    else:
        # 메시지 본문 캡처를 비활성화하여 민감 정보 노출을 방지합니다
        os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"
    logger.info("GenAI 트레이싱 환경변수가 os.environ에 설정되었습니다")

    # ── 2단계: azure.core.settings에 OpenTelemetry 추적 구현 등록 ──────────
    # Azure SDK 전체에서 트레이싱 백엔드로 OpenTelemetry를 사용하도록 지정합니다.
    # 이 설정이 없으면 SDK 내부의 span 생성이 동작하지 않습니다.
    try:
        # Azure Core 라이브러리의 전역 설정 객체를 가져옵니다
        from azure.core.settings import settings as azure_core_settings
        azure_core_settings.tracing_implementation = "opentelemetry"  # 추적 백엔드를 OpenTelemetry로 지정
        logger.info("azure.core.settings.tracing_implementation = 'opentelemetry' 설정 완료")
    except Exception as exc:
        logger.warning("azure.core.settings 설정 실패: %s", exc)

    # ── 3단계: Foundry 프로젝트에서 Application Insights 연결 문자열 가져오기 ─
    # AIProjectClient의 telemetry API는 동기 전용이므로 동기 클라이언트를 사용합니다.
    # 연결 문자열은 Azure Monitor 익스포터가 트레이스를 전송할 대상을 결정합니다.
    app_insights_connection_string: str | None = None  # Application Insights 연결 문자열 (초기값 None)
    # 프로젝트 엔드포인트가 없으면 연결 문자열을 가져올 수 없으므로 조기 반환합니다
    if not settings.azure_ai_project_endpoint:
        logger.warning(
            "AZURE_AI_PROJECT_ENDPOINT가 설정되지 않아 "
            "Application Insights 연결 문자열을 가져올 수 없습니다"
        )
        return False

    try:
        # ── Azure AI 프로젝트 클라이언트 및 자격 증명 라이브러리를 지연 임포트합니다 ──
        from azure.ai.projects import AIProjectClient
        from azure.identity import ClientSecretCredential, DefaultAzureCredential

        # 동기 자격 증명 생성
        # 서비스 프린시펄(tenant/client/secret)이 모두 제공된 경우 ClientSecretCredential을 사용하고,
        # 그렇지 않으면 Managed Identity, Azure CLI 등을 자동 탐색하는 DefaultAzureCredential로 폴백합니다.
        if settings.azure_tenant_id and settings.azure_client_id and settings.azure_client_secret:
            # 서비스 프린시펄 기반 인증: 명시적 자격 증명으로 Azure에 인증합니다
            credential = ClientSecretCredential(
                tenant_id=settings.azure_tenant_id,       # Azure AD 테넌트 ID
                client_id=settings.azure_client_id,       # 서비스 프린시펄 클라이언트 ID
                client_secret=settings.azure_client_secret,  # 서비스 프린시펄 비밀 키
            )
        else:
            # 기본 자격 증명 체인: 환경변수 → Managed Identity → Azure CLI 순으로 시도합니다
            credential = DefaultAzureCredential()

        # Foundry 프로젝트 엔드포인트와 자격 증명으로 동기 클라이언트를 생성합니다
        project_client = AIProjectClient(
            endpoint=settings.azure_ai_project_endpoint,  # Foundry 프로젝트 엔드포인트 URL
            credential=credential,  # 위에서 생성한 Azure 자격 증명 객체
        )

        # Application Insights 연결 문자열을 Foundry 프로젝트 설정에서 동적으로 가져옵니다
        app_insights_connection_string = project_client.telemetry.get_application_insights_connection_string()
        logger.info("Application Insights 연결 문자열을 성공적으로 가져왔습니다")

        # 동기 자격 증명 객체의 내부 HTTP 세션을 명시적으로 정리합니다
        credential.close()

    except Exception as exc:
        logger.error("Application Insights 연결 문자열 가져오기 실패: %s", exc)
        return False

    # 연결 문자열이 빈 값인 경우 트레이스 전송 대상이 없으므로 텔레메트리를 건너뜁니다
    if not app_insights_connection_string:
        logger.warning("Application Insights 연결 문자열이 비어 있습니다. 텔레메트리를 건너뜁니다.")
        return False

    # ── 4단계: Azure Monitor 구성 (트레이스를 Application Insights로 전송) ───
    # configure_azure_monitor()는 OpenTelemetry TracerProvider에 Azure Monitor
    # 익스포터를 등록하여, 이후 생성되는 모든 span이 Application Insights로 전송되도록 합니다.
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor  # Azure Monitor OTEL 통합 라이브러리
        configure_azure_monitor(connection_string=app_insights_connection_string)  # 연결 문자열로 익스포터 초기화
        logger.info("Azure Monitor가 Application Insights에 연결되었습니다")
    except Exception as exc:
        logger.error("Azure Monitor 구성 실패: %s", exc)
        return False

    # ── 5단계: AIProjectInstrumentor로 에이전트 호출 자동 계측 ──────────────
    # Instrumentor는 Foundry 에이전트의 run/stream 호출에 자동으로 span을 삽입하여
    # 각 에이전트 실행의 지연 시간, 토큰 사용량, 오류 등을 추적할 수 있게 합니다.
    try:
        from azure.ai.projects.telemetry import AIProjectInstrumentor  # Foundry 전용 자동 계측기
        AIProjectInstrumentor().instrument()  # 현재 TracerProvider에 계측기를 등록합니다
        logger.info("AIProjectInstrumentor 계측이 활성화되었습니다")
    except Exception as exc:
        logger.error("AIProjectInstrumentor 계측 실패: %s", exc)
        return False

    # ── 6단계: NonRecordingSpan에 .attributes 속성 추가 (근본 원인 수정) ────────
    # [왜 필요한가]
    # azure-ai-projects SDK 내부에서 span.span_instance.attributes를 직접 접근하는 코드가 있습니다.
    # 그런데 SDK가 is_recording을 괄호 없이 호출(bound method → 항상 truthy)하는 버그 때문에,
    # 녹화 중이 아닌 NonRecordingSpan에서도 .attributes에 접근하는 경로가 실행됩니다.
    # NonRecordingSpan 클래스에는 기본적으로 .attributes 속성이 존재하지 않아
    # AttributeError가 발생하므로, 빈 dict를 반환하는 property를 동적으로 추가(monkey-patch)하여
    # SDK의 런타임 오류를 방지합니다. 이는 SDK가 수정될 때까지의 임시 해결책입니다.
    try:
        from opentelemetry.trace import NonRecordingSpan as _NRS  # OpenTelemetry의 비녹화 span 클래스

        # 이미 .attributes가 존재하면 패치를 건너뛰어 기존 동작을 보존합니다
        if not hasattr(_NRS, "attributes"):
            _NRS.attributes = property(lambda self: {})  # type: ignore[attr-defined]  # 빈 dict를 반환하는 읽기 전용 속성 추가
            logger.info("NonRecordingSpan에 .attributes 속성을 추가했습니다 (빈 dict 반환)")
        else:
            logger.info("NonRecordingSpan에 이미 .attributes 속성이 존재합니다")
    except Exception as exc:
        logger.warning("NonRecordingSpan 패치 실패 (무시): %s", exc)

    # 모든 단계가 성공적으로 완료되었으므로 초기화 플래그를 True로 설정합니다
    _telemetry_initialized = True
    logger.info(
        "GenAI 텔레메트리 초기화 완료: "
        "트레이싱=%s, 메시지내용캡처=%s",
        settings.enable_genai_tracing,
        settings.capture_genai_message_content,
    )
    return True


def is_telemetry_enabled() -> bool:
    """텔레메트리가 성공적으로 초기화되었는지 여부를 반환합니다.

    다른 모듈에서 텔레메트리 관련 로직을 조건부로 실행할 때 이 함수를 사용합니다.

    Returns:
        텔레메트리가 활성화되어 있으면 True.
    """
    return _telemetry_initialized  # 모듈 수준 플래그를 그대로 반환

"""Azure AI Projects 응답 스트리밍을 기반으로 하는 Azure AI Foundry 에이전트 통합."""

# ── 표준 라이브러리 ──────────────────────────────────────────────
import hashlib
import json
import logging
import time
import warnings
from collections.abc import AsyncIterator
from typing import Any

# ── Azure SDK ────────────────────────────────────────────────────
from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import (
    ApproximateLocation,
    BingGroundingSearchConfiguration,
    BingGroundingSearchToolParameters,
    BingGroundingTool,
    BrowserAutomationPreviewTool,
    BrowserAutomationToolConnectionParameters,
    BrowserAutomationToolParameters,
    PromptAgentDefinition,
    WebSearchPreviewTool,
)
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
from azure.identity import CredentialUnavailableError
from azure.identity.aio import ClientSecretCredential, DefaultAzureCredential

# ── OpenAI SDK ───────────────────────────────────────────────────
from openai import BadRequestError as OpenAIBadRequestError

# ── OpenTelemetry (분산 추적) ────────────────────────────────────
from opentelemetry import trace

# ── 로컬 모듈 ────────────────────────────────────────────────────
from app.agent_framework.base import AgentEvent, BaseAgent
from app.config import Settings
from app.models import ChatRequest

logger = logging.getLogger(__name__)
_AGENT_CONFIG_HASH_KEY = "agent_config_hash"  # 에이전트 구성 해시를 메타데이터에 저장할 때 사용하는 키 (드리프트 감지용)
_AGENT_CONFIG_KIND = "prompt"  # 에이전트 종류: 프롬프트 기반 에이전트 (PromptAgentDefinition의 kind 값)

# GenAI 트레이싱용 트레이서 — 텔레메트리 모듈에서 OpenTelemetry가 초기화된 후 사용됩니다.
_tracer = trace.get_tracer(__name__)  # 이 모듈의 모든 OpenTelemetry 스팬 생성에 사용되는 트레이서 인스턴스


def _safe_serialize(obj: Any) -> Any:
    """로깅을 위해 SDK 객체의 JSON 직렬화 가능한 표현을 반환합니다.

    ``model_dump()``, ``as_dict()``, ``dict()``, ``vars()`` 순으로
    직렬화를 시도하며, 마지막 수단으로 ``repr()``를 사용합니다.

    Azure SDK의 Pydantic 모델은 ``bing_grounding``, ``memory_search``
    등 커스텀 도구 타입에 대해 직렬화 경고를 발생시키므로 이를 억제합니다.

    Args:
        obj: 직렬화할 임의의 Python 객체.

    Returns:
        JSON 안전 표현 (str, int, float, bool, list, dict 또는
        repr 문자열).
    """

    # 1단계: 이미 JSON 안전한 기본 타입이면 그대로 반환합니다
    if obj is None or isinstance(obj, (str, int, float, bool, list, dict)):
        return obj
    # 2단계: Pydantic v2 모델 — model_dump()를 시도합니다 (Azure SDK 경고 억제)
    if hasattr(obj, "model_dump"):
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Pydantic serializer warnings",
                    category=UserWarning,
                )
                return obj.model_dump()
        except Exception:  # pragma: no cover - defensive serializer fallback
            pass
    # 3단계: Azure SDK 모델 — as_dict()를 시도합니다
    if hasattr(obj, "as_dict"):
        try:
            return obj.as_dict()
        except Exception:  # pragma: no cover - defensive serializer fallback
            pass
    # 4단계: Pydantic v1 모델 — dict()를 시도합니다
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:  # pragma: no cover - defensive serializer fallback
            pass
    # 5단계: 일반 Python 객체 — vars()로 __dict__ 추출을 시도합니다
    try:
        return vars(obj)
    except TypeError:  # pragma: no cover - defensive serializer fallback
        # 최후 수단: repr() 문자열로 변환합니다
        return repr(obj)


def _extract_latest_user_input(request: ChatRequest) -> str:
    """요청 페이로드에서 가장 최근 사용자 메시지를 일반 문자열로 반환합니다.

    메시지를 역순으로 순회하여 가장 최근 사용자 메시지를 찾고,
    일반 문자열 및 멀티모달 콘텐츠 형식 모두에서 텍스트를 추출합니다.

    Args:
        request: 대화 메시지가 포함된 수신 채팅 요청.

    Returns:
        가장 최근 비어있지 않은 사용자 메시지의 트리밍된 텍스트.

    Raises:
        RuntimeError: 요청에서 비어있지 않은 사용자 메시지를 찾을 수 없는 경우.
    """

    for message in reversed(request.messages):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            if content.strip():
                return content.strip()
        elif isinstance(content, list):
            texts = [part.text for part in content if hasattr(part, "text") and part.text.strip()]
            if texts:
                return " ".join(texts)
    raise RuntimeError("Chat request must include at least one non-empty user message.")


def _normalize_content_parts_for_responses(content: list[Any]) -> list[dict[str, Any]]:
    """허용된 콘텐츠 파트 변형을 Responses API 입력 스키마로 변환합니다.

    각 파트를 직렬화하고 Azure AI Responses API가 수용하는
    ``input_text`` 또는 ``input_image`` 항목으로 매핑합니다.

    Args:
        content: 수신 채팅 요청의 콘텐츠 파트 객체 목록
            (text, image_url 등).

    Returns:
        Responses API 입력 스키마를 준수하는 정규화된 딕셔너리 목록으로,
        각각 ``type`` 키와 관련 데이터를 포함합니다.

    Raises:
        RuntimeError: 유효한 정규화 항목을 생성하는 파트가 없는 경우.
    """

    normalized: list[dict[str, Any]] = []  # 정규화된 결과 파트를 저장하는 목록
    for part in content:
        serialized = _safe_serialize(part)  # 각 파트를 딕셔너리로 직렬화합니다
        if not isinstance(serialized, dict):
            continue

        part_type = serialized.get("type")  # 파트의 타입을 확인합니다

        # 텍스트 콘텐츠 처리: "input_text" 또는 "text" 타입을 Responses API의 "input_text"로 변환
        if part_type in {"input_text", "text"}:
            text = serialized.get("text")
            if isinstance(text, str) and text.strip():
                normalized.append({"type": "input_text", "text": text.strip()})
            continue

        # 이미지 콘텐츠 처리: "input_image" 또는 "image_url" 타입을 Responses API의 "input_image"로 변환
        if part_type in {"input_image", "image_url"}:
            image_url = serialized.get("image_url")
            # image_url이 중첩 딕셔너리인 경우 내부 url 값을 추출합니다
            if isinstance(image_url, dict):
                image_url = image_url.get("url")
            if isinstance(image_url, str) and image_url.strip():
                normalized.append(
                    {
                        "type": "input_image",
                        "image_url": image_url,
                        "detail": serialized.get("detail") or "auto",  # 이미지 상세 수준 (기본값: auto)
                    }
                )

    # 유효한 파트가 없으면 오류를 발생시킵니다
    if not normalized:
        raise RuntimeError("Chat request must include at least one non-empty user message.")

    return normalized


def _content_is_multimodal(content: Any) -> bool:
    """콘텐츠에 이미지와 같은 비텍스트 파트가 포함된 경우 True를 반환합니다.

    Args:
        content: 문자열 또는 콘텐츠 파트 객체 목록일 수 있는
            메시지 콘텐츠.

    Returns:
        *content*가 이미지 파트를 하나 이상 포함하는 목록이면 ``True``;
        그렇지 않으면 ``False``.
    """

    if not isinstance(content, list):
        return False
    for part in content:
        serialized = _safe_serialize(part)
        if isinstance(serialized, dict) and serialized.get("type") in {"input_image", "image_url"}:
            return True
    return False


def _extract_text_from_multimodal(content: list[Any]) -> str:
    """멀티모달 콘텐츠 목록에서 텍스트 파트만 추출합니다.

    Args:
        content: 텍스트 및/또는 이미지 항목을 포함할 수 있는
            콘텐츠 파트 객체 목록.

    Returns:
        모든 텍스트 파트를 공백으로 연결한 단일 문자열, 또는
        텍스트 파트가 없는 경우 리터럴 ``"Image attached."``.
    """

    texts: list[str] = []
    for part in content:
        serialized = _safe_serialize(part)
        if not isinstance(serialized, dict):
            continue
        if serialized.get("type") in {"input_text", "text"}:
            text = serialized.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    return " ".join(texts) if texts else "Image attached."


def _extract_latest_user_content(request: ChatRequest) -> Any:
    """Responses API가 기대하는 스키마로 가장 최근 사용자 메시지를 반환합니다.

    일반 문자열 메시지의 경우 트리밍된 문자열을 직접 반환합니다.
    멀티모달(목록) 콘텐츠의 경우 ``_normalize_content_parts_for_responses``를
    통해 파트를 정규화합니다.

    Args:
        request: 대화 메시지가 포함된 수신 채팅 요청.

    Returns:
        텍스트 전용 메시지의 경우 문자열, 멀티모달 메시지의 경우
        정규화된 콘텐츠 파트 딕셔너리 목록.

    Raises:
        RuntimeError: 요청에서 비어있지 않은 사용자 메시지를 찾을 수 없는 경우.
    """

    for message in reversed(request.messages):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            stripped = content.strip()
            if stripped:
                return stripped
        elif isinstance(content, list):
            return _normalize_content_parts_for_responses(content)
    raise RuntimeError("Chat request must include at least one non-empty user message.")


def _is_content_part_list(value: Any) -> bool:
    """목록이 최상위 응답 항목 목록이 아닌 사용자 콘텐츠 목록인 경우 True를 반환합니다.

    목록의 모든 요소가 ``type``이 인식된 콘텐츠 파트 유형
    (``input_text``, ``input_image``, ``text``, ``image_url``) 중 하나인
    딕셔너리로 직렬화되는지 확인합니다.

    Args:
        value: 검사할 값; 임의의 타입일 수 있습니다.

    Returns:
        *value*가 인식된 콘텐츠 파트 딕셔너리로만 구성된 비어있지 않은
        목록이면 ``True``; 그렇지 않으면 ``False``.
    """

    if not isinstance(value, list) or not value:
        return False

    allowed_part_types = {"input_text", "input_image", "text", "image_url"}
    for item in value:
        serialized = _safe_serialize(item)
        if not isinstance(serialized, dict):
            return False
        if serialized.get("type") not in allowed_part_types:
            return False
    return True


def _prepare_response_input(user_input: Any | None) -> Any | None:
    """사용자 콘텐츠를 responses.create에 필요한 최상위 입력 형태로 변환합니다.

    입력이 콘텐츠 파트 목록인 경우 메시지 엔벨로프로 감싸고,
    그렇지 않으면 그대로 전달합니다.

    Args:
        user_input: 채팅 요청에서 추출한 사용자 콘텐츠, 또는 새 입력을
            보내지 않아야 할 때 ``None``.

    Returns:
        *user_input*이 콘텐츠 파트 목록인 경우 단일 ``message`` 딕셔너리를
        포함하는 목록, 다른 타입의 경우 원래 *user_input*, *user_input*이
        ``None``인 경우 ``None``.
    """

    if user_input is None:
        return None

    if _is_content_part_list(user_input):
        return [{"type": "message", "role": "user", "content": user_input}]

    return user_input


def _build_response_instructions(request: ChatRequest) -> str | None:
    """시스템 메시지가 제공된 경우 응답별 지시사항으로 결합합니다.

    Args:
        request: ``role == "system"`` 항목을 검색할 메시지가 포함된
            수신 채팅 요청.

    Returns:
        모든 시스템 메시지 텍스트를 이중 줄바꿈으로 연결한 문자열,
        또는 시스템 메시지가 없는 경우 ``None``.
    """

    instructions = []
    for message in request.messages:
        if message.role != "system":
            continue
        content = message.content
        if isinstance(content, str) and content.strip():
            instructions.append(content.strip())
    return "\n\n".join(instructions) or None


def _build_response_kwargs(
    *,
    conversation_id: str,
    extra_agent: dict[str, str],
    response_instructions: str | None,
    user_input: Any | None,
) -> dict[str, Any]:
    """초기 대화 메시지를 중복하지 않고 responses.create 페이로드를 구성합니다.

    대화 참조, 에이전트 참조, 선택적 지시사항, 선택적 사용자 입력을
    포함하여 ``openai_client.responses.create``에 전달할 키워드 인자
    딕셔너리를 조립합니다.

    Args:
        conversation_id: Azure AI 대화 식별자.
        extra_agent: ``extra_body`` 페이로드에 사용할 에이전트 참조 딕셔너리
            (``type``, ``name``, 선택적으로 ``version``).
        response_instructions: 선택적 응답별 시스템 지시사항.
        user_input: 입력으로 포함할 선택적 사용자 콘텐츠; 사용자 턴이
            이미 대화에 기록된 경우 ``None``.

    Returns:
        ``responses.create(**kwargs)``에 언패킹하기 적합한 딕셔너리.
    """

    kwargs: dict[str, Any] = {
        "conversation": conversation_id,
        "extra_body": {"agent_reference": extra_agent},
        "stream": True,
    }
    if response_instructions:
        kwargs["instructions"] = response_instructions
    prepared_input = _prepare_response_input(user_input)
    if prepared_input:
        kwargs["input"] = prepared_input
    return kwargs


def _extract_annotation_messages(part: Any) -> list[str]:
    """URL 인용 어노테이션을 사람이 읽을 수 있는 상태 메시지로 추출합니다.

    직렬화된 콘텐츠 파트 내의 ``annotations`` 목록을 검사하고
    각 ``url_citation`` 항목을 ``"Source: ..."`` 문자열로 변환합니다.

    Args:
        part: 인용 어노테이션을 포함할 수 있는 콘텐츠 파트 SDK 객체.

    Returns:
        형식화된 인용 문자열 목록. *part*에 ``url_citation``
        어노테이션이 없으면 빈 목록.
    """

    annotations = _safe_serialize(part)
    if not isinstance(annotations, dict):
        return []

    messages: list[str] = []
    for annotation in annotations.get("annotations", []):
        annotation_type = annotation.get("type") if isinstance(annotation, dict) else getattr(annotation, "type", None)
        if annotation_type != "url_citation":
            continue
        title = annotation.get("title") if isinstance(annotation, dict) else getattr(annotation, "title", None)
        url = annotation.get("url") if isinstance(annotation, dict) else getattr(annotation, "url", None)
        if title and url:
            messages.append(f"Source: {title} - {url}")
        elif url:
            messages.append(f"Source: {url}")
    return messages


def _extract_output_item_messages(item: Any) -> list[str]:
    """텍스트 델타가 발생하지 않았을 때 완료된 출력 항목에서 어시스턴트 텍스트를 추출합니다.

    ``message`` 타입 출력 항목의 ``content`` 목록을 순회하며
    ``output_text`` 파트에서 텍스트를 수집합니다.

    Args:
        item: 완료된 응답 항목을 나타내는 SDK 출력 항목 객체.

    Returns:
        출력 항목의 콘텐츠에서 발견된 비어있지 않은 텍스트 문자열 목록.
        항목이 ``message`` 타입이 아니거나 텍스트 파트가 없으면 빈 목록.
    """

    serialized = _safe_serialize(item)
    if not isinstance(serialized, dict) or serialized.get("type") != "message":
        return []

    messages: list[str] = []
    for part in serialized.get("content", []):
        serialized_part = _safe_serialize(part)
        if not isinstance(serialized_part, dict):
            continue
        if serialized_part.get("type") != "output_text":
            continue
        text = serialized_part.get("text")
        if isinstance(text, str) and text.strip():
            messages.append(text)
    return messages


def _extract_output_item_text_parts(item: Any, output_index: int | None) -> list[tuple[set[str], str]]:
    """파트별 중복 제거 키와 함께 완료된 출력 텍스트 파트를 추출합니다.

    반환되는 각 튜플은 안정적인 식별자 키 집합과 해당 텍스트를 쌍으로 합니다.
    호출자는 이 키를 사용하여 델타 및 터미널 이벤트 간에 동일한 텍스트가
    두 번 이상 발생하지 않도록 합니다.

    Args:
        item: ``message`` 타입으로 예상되는 SDK 출력 항목 객체.
        output_index: 응답 스트림에서 이 출력 항목의 0부터 시작하는
            위치, 또는 사용 불가 시 ``None``.

    Returns:
        ``(dedupe_keys, text)`` 튜플 목록. 항목이 ``message`` 타입이
        아니거나 ``output_text`` 파트가 없으면 빈 목록.
    """

    serialized = _safe_serialize(item)
    if not isinstance(serialized, dict) or serialized.get("type") != "message":
        return []

    item_id = serialized.get("id")
    text_parts: list[tuple[set[str], str]] = []
    for part_index, part in enumerate(serialized.get("content", [])):
        serialized_part = _safe_serialize(part)
        if not isinstance(serialized_part, dict):
            continue
        if serialized_part.get("type") != "output_text":
            continue
        text = serialized_part.get("text")
        if not isinstance(text, str) or not text.strip():
            continue

        part_keys: set[str] = set()
        if item_id:
            part_keys.add(f"item:{item_id}:content:{part_index}")
        if output_index is not None:
            part_keys.add(f"content:{output_index}:{part_index}")
        text_parts.append((part_keys, text))

    return text_parts


def _collect_response_text_keys(item: Any) -> set[str]:
    """텍스트 델타를 터미널 이벤트에 연결하는 안정적인 식별자를 수집합니다.

    키는 ``item_id``, ``output_index``, ``content_index``, 그리고
    사용 가능한 경우 중첩된 ``item.id``에서 파생됩니다. 이를 통해
    호출자는 터미널(``done``) 이벤트가 이미 델타 이벤트를 통해
    스트리밍된 텍스트를 다루는지 감지할 수 있습니다.

    Args:
        item: 선택적 ``item_id``, ``output_index``, ``content_index``,
            ``item`` 속성을 가진 SDK 스트림 이벤트 객체.

    Returns:
        이 이벤트의 텍스트 부분을 고유하게 식별하는 문자열 키 집합.
        식별 속성이 없으면 빈 집합일 수 있습니다.
    """

    keys: set[str] = set()
    item_id = getattr(item, "item_id", None)
    if item_id:
        keys.add(str(item_id))
        keys.add(f"item:{item_id}")

    output_index = getattr(item, "output_index", None)
    content_index = getattr(item, "content_index", None)
    if output_index is not None and content_index is not None:
        keys.add(f"content:{output_index}:{content_index}")

    output_item = getattr(item, "item", None)
    output_item_id = getattr(output_item, "id", None)
    if output_item_id:
        keys.add(str(output_item_id))
        keys.add(f"item:{output_item_id}")

    return keys


def _format_mcp_approval_message(item: Any) -> str | None:
    """MCP 승인 요청에 대한 사용자 대면 상태 메시지를 반환합니다.

    Args:
        item: ``mcp_approval_request``일 수 있는 SDK 출력 항목 객체.

    Returns:
        승인 요청을 설명하는 사람이 읽을 수 있는 상태 문자열, 또는
        항목이 MCP 승인 요청이 아닌 경우 ``None``.
    """

    serialized = _safe_serialize(item)
    if not isinstance(serialized, dict) or serialized.get("type") != "mcp_approval_request":
        return None

    tool_name = serialized.get("name") or "unknown tool"
    server_label = serialized.get("server_label")
    if isinstance(server_label, str) and server_label.strip():
        return f"Tool approval requested for {tool_name} on {server_label}. Auto-approving and continuing..."
    return f"Tool approval requested for {tool_name}. Auto-approving and continuing..."


def _format_activity_status(item: Any, *, completed: bool = False) -> str | None:
    """비승인 도구 활동에 대한 사용자 대면 상태 메시지를 반환합니다.

    ``mcp_call`` 및 ``memory_search_call`` 항목 타입을 처리하며,
    진행 중 및 완료 상태 모두에 대한 메시지를 생성합니다.

    Args:
        item: 도구 활동을 설명하는 SDK 출력 항목 객체.
        completed: ``True``이면 상태 메시지의 완료 변형을 반환하고,
            ``False``이면 진행 중 변형을 반환합니다.

    Returns:
        사람이 읽을 수 있는 상태 문자열, 또는 항목 타입이 인식된
        도구 활동 타입이 아닌 경우 ``None``.
    """

    serialized = _safe_serialize(item)
    if not isinstance(serialized, dict):
        return None

    item_type = serialized.get("type")
    if item_type == "mcp_call":
        tool_name = serialized.get("name") or "unknown tool"
        server_label = serialized.get("server_label")
        status = serialized.get("status")
        error = serialized.get("error")
        tool_label = (
            f"{tool_name} on {server_label}"
            if isinstance(server_label, str) and server_label.strip()
            else str(tool_name)
        )
        if status == "failed":
            if isinstance(error, str) and error.strip():
                return f"Tool {tool_label} failed: {error.strip()}"
            return f"Tool {tool_label} failed."
        if completed:
            return f"Tool {tool_label} completed."
        if isinstance(server_label, str) and server_label.strip():
            return f"Calling tool {tool_name} on {server_label}..."
        return f"Calling tool {tool_name}..."

    if item_type == "memory_search_call":
        return "Memory lookup completed." if completed else "Searching conversation memory..."

    return None


def _build_mcp_approval_input(approval_request_ids: list[str]) -> list[dict[str, Any]]:
    """Responses API용 승인 응답 입력 항목을 구성합니다.

    Args:
        approval_request_ids: 자동 승인할 MCP 승인 요청 식별자 목록.

    Returns:
        각 요청 ID에 대해 ``approve``를 ``True``로 설정하는
        ``mcp_approval_response`` 딕셔너리 목록.
    """

    return [
        {
            "type": "mcp_approval_response",
            "approval_request_id": approval_request_id,
            "approve": True,
        }
        for approval_request_id in approval_request_ids
    ]


def _format_unexpected_error(exc: Exception) -> str:
    """구체적인 실패 신호를 보존하는 간결한 사용자 대면 오류를 반환합니다.

    Args:
        exc: 예기치 않은 실패를 야기한 예외.

    Returns:
        예외 타입과 메시지의 최대 300자를 포함하는
        형식화된 오류 문자열.
    """

    detail = str(exc).strip()
    if detail:
        return (
            "Azure AI Foundry request failed unexpectedly. "
            f"{type(exc).__name__}: {detail[:300]}"
        )
    return (
        "Azure AI Foundry request failed unexpectedly. "
        f"{type(exc).__name__}."
    )


def _format_bad_request_error(exc: OpenAIBadRequestError) -> str:
    """거부된 Azure AI 요청에 대한 간결한 사용자 대면 오류를 반환합니다.

    Args:
        exc: OpenAI 클라이언트가 발생시킨 ``BadRequestError``.

    Returns:
        거부 상세 정보의 최대 300자를 포함하는 형식화된 오류 문자열,
        또는 상세 정보가 비어있을 때 일반적인 재시도 메시지.
    """

    detail = str(exc).strip()
    if detail:
        return f"Azure AI request was rejected. {detail[:300]}"
    return "Azure AI request was rejected. Please try sending your message again."


def _summarize_request(request: ChatRequest) -> dict[str, Any]:
    """수명주기 로깅을 위한 안전한 요청 요약을 반환합니다.

    실제 메시지 텍스트를 포함하지 않고 역할별 메시지 수와
    최신 사용자 입력의 길이를 계산하여 로그 출력을
    콘텐츠 안전하게 유지합니다.

    Args:
        request: 요약할 수신 채팅 요청.

    Returns:
        ``conversation_id``, ``message_count``,
        ``system_message_count``, ``user_message_count``,
        ``assistant_message_count``, ``has_metadata``,
        ``latest_user_input_length`` 키를 가진 딕셔너리.
    """

    system_messages = sum(1 for message in request.messages if message.role == "system")
    user_messages = sum(1 for message in request.messages if message.role == "user")
    assistant_messages = sum(1 for message in request.messages if message.role == "assistant")
    latest_user_input = ""
    for message in reversed(request.messages):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str) and content.strip():
            latest_user_input = content.strip()
            break
        elif isinstance(content, list):
            texts = [part.text for part in content if hasattr(part, "text") and part.text.strip()]
            if texts:
                latest_user_input = " ".join(texts)
                break
    return {
        "conversation_id": request.conversation_id,
        "message_count": len(request.messages),
        "system_message_count": system_messages,
        "user_message_count": user_messages,
        "assistant_message_count": assistant_messages,
        "has_metadata": bool(request.metadata),
        "latest_user_input_length": len(latest_user_input),
    }


class AzureAIFoundryAgent(BaseAgent):
    """Azure AI Projects 프롬프트 에이전트로부터 채팅 응답을 스트리밍합니다."""

    def __init__(self, settings: Settings) -> None:
        """애플리케이션 설정으로 에이전트를 초기화합니다.

        Args:
            settings: Azure AI 프로젝트 엔드포인트, 에이전트 이름, 모델,
                자격 증명 세부 정보를 제공하는 애플리케이션 구성.
        """
        self._settings = settings  # Azure AI 프로젝트 엔드포인트, 에이전트 이름, 모델, 자격 증명 등 전체 설정을 보관

    async def stream(self, request: ChatRequest) -> AsyncIterator[AgentEvent]:
        """Azure AI Projects 응답을 리포지토리 SSE 이벤트 계약으로 스트리밍합니다.

        전체 수명주기를 조율합니다: 자격 증명 생성, 프로젝트 클라이언트
        초기화, 에이전트 해석, 대화 관리, Responses API 출력을
        ``AgentEvent`` 인스턴스로 스트리밍.

        Args:
            request: 사용자 메시지, 선택적 대화 ID, 메타데이터가
                포함된 수신 채팅 요청.

        Yields:
            AgentEvent: ``status``, ``message``, ``error``, ``done`` 타입의
                SSE 호환 이벤트.

        Raises:
            RuntimeError: 구성 검증 또는 사용자 메시지 누락으로 인해 전파됨.
            CredentialUnavailableError: Azure 자격 증명이 구성되지 않은 경우.
            ClientAuthenticationError: Azure 인증이 실패한 경우.
            HttpResponseError: Azure AI Foundry 요청이 실패한 경우.
            OpenAIBadRequestError: 업스트림 API에 의해 요청이 거부된 경우.
        """

        conversation_id = request.conversation_id  # 기존 대화 ID를 요청에서 추출합니다 (없으면 None)
        logger.info("Azure AI request started: %s", _summarize_request(request))
        # 요청에서 최신 사용자 메시지의 텍스트와 전체 콘텐츠를 추출합니다
        latest_user_input = _extract_latest_user_input(request)  # 로깅용 텍스트 문자열
        latest_user_content = _extract_latest_user_content(request)  # API 전송용 콘텐츠 (문자열 또는 멀티모달 목록)
        logger.info(
            "Azure AI user prompt: conversation_id=%s, prompt=%s",
            conversation_id,
            latest_user_input,
        )
        # ── 1단계: 연결 시작 상태 이벤트 발행 ──
        yield AgentEvent(event="status", data="Connecting to Azure AI Foundry...", conversation_id=conversation_id)

        # GenAI 트레이싱: 채팅 요청에 대한 OpenTelemetry 스팬을 생성합니다.
        # async generator에서는 with 블록으로 스팬을 감쌀 수 없으므로,
        # 수동으로 스팬을 시작하고 종료합니다.
        # use_span()으로 현재 컨텍스트에 설정하여 자식 스팬이 올바르게 중첩됩니다.
        span = _tracer.start_span(
            f"invoke_agent {self._settings.azure_ai_agent_name}",
            attributes={
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.system": "az.ai.agents",
                "gen_ai.provider.name": "microsoft.foundry",
                "gen_ai.agent.name": self._settings.azure_ai_agent_name,
                "gen_ai.request.model": self._settings.azure_ai_model,
                "gen_ai.conversation.id": conversation_id or "",
                "message_count": len(request.messages),
            },
        )
        # 스팬을 현재 컨텍스트로 설정하여 하위 스팬들이 이 스팬 아래에 중첩됩니다.
        span_ctx = trace.use_span(span, end_on_exit=False)

        credential: ClientSecretCredential | DefaultAzureCredential | None = None  # Azure 자격 증명 객체 (finally에서 정리)
        stream_succeeded = False  # 스트림 성공 여부 플래그 — done 이벤트 발행 결정에 사용
        completion_state = "failed"  # GenAI 트레이싱에 기록할 최종 상태 ("complete" 또는 "failed")
        mcp_tool_spans: dict[str, trace.Span] = {}  # MCP 도구 호출별 OpenTelemetry 스팬 추적 (키: 출력 항목 ID)
        try:
            span_ctx.__enter__()  # 수동으로 스팬 컨텍스트 활성화
            # ── 2단계: Azure AI 구성 검증 및 자격 증명 생성 ──
            logger.info("Validating Azure AI configuration before credential creation")
            credential = self._build_credential()  # 서비스 주체 또는 기본 자격 증명을 생성합니다
            logger.info("Azure credential created successfully for tenant/client configuration")
            # ── 3단계: Azure AI 프로젝트 클라이언트 생성 ──
            logger.info("Creating Azure AI project client")
            async with AIProjectClient(
                endpoint=self._settings.azure_ai_project_endpoint,
                credential=credential,
            ) as project_client:
                logger.info("Azure AI project client created successfully")
                # ── 4단계: OpenAI 호환 클라이언트 생성 ──
                logger.info("Creating OpenAI client from Azure AI project client")
                async with project_client.get_openai_client(
                    timeout=self._settings.request_timeout_seconds
                ) as openai_client:
                    logger.info(
                        "OpenAI client ready, timeout_seconds=%s",
                        self._settings.request_timeout_seconds,
                    )

                    # ── 5단계: 에이전트 해석 — 이름으로 에이전트를 조회하고 버전 드리프트를 감지합니다 ──
                    # GenAI 트레이싱: 에이전트 조회/생성 스팬
                    with _tracer.start_as_current_span(
                        "resolve-agent",
                        attributes={
                            "gen_ai.agent.name": self._settings.azure_ai_agent_name,
                            "gen_ai.provider.name": "microsoft.foundry",
                        },
                    ) as agent_span:
                        agent = await self._resolve_agent(project_client)
                        if agent_span.is_recording():
                            agent_span.set_attribute("gen_ai.agent.id", str(getattr(agent, "id", "")))
                            agent_span.set_attribute("gen_ai.agent.version", str(getattr(agent, "version", "unknown")))

                    # ── 6단계: 대화 관리 — 기존 대화 재사용 또는 새 대화 생성 ──
                    # GenAI 트레이싱: 대화 생성/조회 스팬
                    with _tracer.start_as_current_span(
                        "ensure-conversation",
                        attributes={
                            "gen_ai.agent.name": self._settings.azure_ai_agent_name,
                            "gen_ai.conversation.id": conversation_id or "",
                        },
                    ) as conv_span:
                        conversation_id, created_now = await self._ensure_conversation(
                            openai_client=openai_client,
                            request=request,
                            latest_user_content=latest_user_content,
                        )
                        if conv_span.is_recording():
                            conv_span.set_attribute("gen_ai.conversation.id", conversation_id or "")
                            conv_span.set_attribute("created_new", created_now)

                    # ── 7단계: 에이전트 참조 페이로드 구성 (Responses API용) ──
                    extra_agent = await self._build_agent_reference(project_client, agent)

                    if created_now:
                        # ── 8a단계: 새 대화 생성 후 — 대화 ID를 즉시 발행합니다 ──
                        # 생성된 대화 ID를 즉시 발행하여 응답 스트림이
                        # 이후 오류로 종료되더라도 프론트엔드가
                        # 이를 유지할 수 있도록 합니다.
                        # 최신 사용자 턴은 생성 과정에서 이미 대화에
                        # 기록되었으므로, 여기서 입력을 다시 보내면
                        # Foundry에서 동일한 메시지가 중복됩니다.
                        yield AgentEvent(
                            event="status",
                            data="Azure AI conversation ready.",
                            conversation_id=conversation_id,
                        )
                        # 사용자 턴은 이미 대화에 기록되었으므로 입력을 다시 보내지 않습니다
                        user_input_for_response = None
                    else:
                        # ── 8b단계: 기존 대화 재사용 — 최신 사용자 콘텐츠를 응답 입력에 포함합니다 ──
                        user_input_for_response = latest_user_content

                    # ── 9단계: Responses API 호출 페이로드를 조립합니다 ──
                    response_kwargs = _build_response_kwargs(
                        conversation_id=conversation_id,
                        extra_agent=extra_agent,
                        response_instructions=_build_response_instructions(request),
                        user_input=user_input_for_response,
                    )

                    logger.info(
                        "Starting Azure AI response stream, conversation_id=%s, agent_name=%s,"
                        " new_conversation=%s, includes_input=%s, has_instructions=%s",
                        conversation_id,
                        getattr(agent, "name", None),
                        created_now,
                        "input" in response_kwargs,
                        "instructions" in response_kwargs,
                    )

                    # ── 10단계: MCP 자동 승인 루프를 포함한 응답 스트리밍 ──
                    approval_round = 0  # 현재 MCP 승인 라운드 번호
                    response_instructions = _build_response_instructions(request)  # 시스템 메시지 기반 지시사항
                    auto_approved_request_ids: set[str] = set()  # 이미 자동 승인한 요청 ID (중복 승인 방지)

                    while True:
                        # 스트림을 시도합니다; 대화에 이전 턴의 미처리 MCP 승인이
                        # 남아있으면 API가 400을 반환합니다. 이 경우 새 대화로
                        # 초기화하고 한 번 재시도합니다.
                        # 이전 턴의 미처리 MCP 승인이 남아 있으면 400 오류가 발생하므로,
                        # 새 대화로 초기화하고 한 번 재시도합니다.
                        try:
                            #     f"reinvoke_agent {self._settings.azure_ai_agent_name}",
                            #     attributes={
                            #         "gen_ai.operation.name": "reinvoke_agent",
                            #         "gen_ai.system": "az.ai.agents",
                            #         "gen_ai.provider.name": "microsoft.foundry",
                            #         "gen_ai.agent.name": self._settings.azure_ai_agent_name,
                            #         "gen_ai.request.model": self._settings.azure_ai_model,
                            #         "gen_ai.conversation.id": conversation_id or "",
                            #         "message_count": len(request.messages),
                            #     },
                            # ) as reinvoke_span:
                            #     if reinvoke_span.is_recording():
                            #         reinvoke_span.set_attribute("reinvoke_round", approval_round)
                            # Responses API 스트리밍 응답을 생성합니다
                            resp_result = await openai_client.responses.create(**response_kwargs)
                        except OpenAIBadRequestError as exc:
                            # MCP 승인 상태 불일치 오류 — 대화를 초기화하여 복구합니다
                            if "MCP approval requests do not have an approval" in str(exc):
                                logger.warning(
                                    "Stale MCP approval in conversation %s; resetting to new conversation for retry.",
                                    conversation_id,
                                )
                                yield AgentEvent(
                                    event="status",
                                    data="Reconnecting (tool approval state reset)...",
                                    conversation_id=conversation_id,
                                )
                                # 새 대화로 전환하여 MCP 승인 상태를 초기화합니다
                                conversation_id, _ = await self._create_fresh_conversation(
                                    openai_client=openai_client,
                                    request=request,
                                    latest_user_content=latest_user_content,
                                )
                                # 새 대화 기반 응답 페이로드를 재구성합니다
                                response_kwargs = _build_response_kwargs(
                                )
                                resp_result = await openai_client.responses.create(**response_kwargs)
                            else:
                                raise

                        emitted_output_item_ids: set[str] = set()  # 이미 발행된 텍스트 부분의 중복 제거 키
                        mcp_tool_start_times: dict[str, float] = {}  # MCP 도구 호출 시작 시간 (키: 출력 항목 ID, 값: monotonic 타임스탬프)
                        mcp_tool_spans: dict[str, trace.Span] = {}  # MCP 도구 호출별 OpenTelemetry 스팬 (키: 출력 항목 ID)
                        pending_mcp_approvals: list[dict[str, str]] = []  # 대기 중인 MCP 승인 요청 목록
                        # ── 스트림 이벤트 순회: 각 항목을 SSE 이벤트로 변환합니다 ──
                        async for item in resp_result:
                            # MCP 승인 요청 항목을 감지하여 자동 승인 목록에 추가합니다
                            if getattr(item, "type", "") == "response.output_item.added":
                                output_item = getattr(item, "item", None)
                                if getattr(output_item, "type", None) == "mcp_approval_request":
                                    aid = getattr(output_item, "id", None)
                                    if aid:
                                        pending_mcp_approvals.append(
                                            {
                                                "id": aid,
                                                "message": _format_mcp_approval_message(output_item) or (
                                                    "Tool approval requested. Auto-approving and continuing..."
                                                ),
                                            }
                                        )
                                        logger.info(
                                            "MCP approval request captured for auto-approval: approval_id=%s, tool=%s",
                                            aid,
                                            getattr(output_item, "name", "unknown"),
                                        )
                            async for event in self._stream_events_from_item(
                                item,
                                conversation_id,
                                emitted_output_item_ids,
                                mcp_tool_start_times,
                                mcp_tool_spans,
                            ):
                                yield event

                        # ── MCP 승인 대기 항목이 없으면 스트리밍 루프를 종료합니다 ──
                        if not pending_mcp_approvals:
                            break

                        # ── 이미 승인한 요청의 재등장을 필터링합니다 ──
                        new_pending_mcp_approvals = [
                            entry
                            for entry in pending_mcp_approvals
                            if entry["id"] not in auto_approved_request_ids
                        ]
                        if not new_pending_mcp_approvals:
                            logger.warning(
                                "MCP approval request(s) repeated after auto-approval,"
                                " conversation_id=%s, approval_ids=%s",
                                conversation_id,
                                [entry["id"] for entry in pending_mcp_approvals],
                            )
                            break

                        # ── 새로운 MCP 승인 요청을 자동 승인하고 다음 라운드로 진행합니다 ──
                        approval_round += 1
                        approval_request_ids = [entry["id"] for entry in new_pending_mcp_approvals]
                        auto_approved_request_ids.update(approval_request_ids)
                        logger.info(
                            "Auto-approving %d MCP approval request(s) for conversation %s",
                            len(new_pending_mcp_approvals),
                            conversation_id,
                        )
                        response_kwargs = _build_response_kwargs(
                            conversation_id=conversation_id,
                            extra_agent=extra_agent,
                            response_instructions=response_instructions if approval_round == 0 else None,
                            user_input=_build_mcp_approval_input(approval_request_ids),
                        )

                    stream_succeeded = True  # 스트림이 정상 완료됨
                    completion_state = "complete"  # GenAI 트레이싱 최종 상태를 성공으로 설정
        # ── 예외 처리: 각 Azure 예외 유형별로 적절한 오류 이벤트를 발행합니다 ──
        except RuntimeError as exc:
            # 구성 오류 — 필수 환경 변수 누락 또는 사용자 메시지 없음
            logger.error("Azure AI configuration error: %s", exc)
            yield AgentEvent(event="error", data=str(exc), conversation_id=conversation_id)
            yield AgentEvent(event="done", data="failed", conversation_id=conversation_id)
        except CredentialUnavailableError as exc:
            # 자격 증명 미구성 — AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET 필요
            logger.error(
                "Azure credential unavailable for Foundry endpoint %s: %s",
                self._settings.azure_ai_project_endpoint,
                exc,
            )
            yield AgentEvent(
                event="error",
                data=(
                    "Azure AI Foundry authentication is not configured. "
                    "Set AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_CLIENT_SECRET."
                ),
                conversation_id=conversation_id,
            )
            yield AgentEvent(event="done", data="failed", conversation_id=conversation_id)
        except ClientAuthenticationError as exc:
            # 인증 실패 — 서비스 주체의 Foundry 프로젝트 접근 권한 검증 필요
            logger.error(
                "Azure authentication failed for Foundry endpoint %s: %s",
                self._settings.azure_ai_project_endpoint,
                exc,
            )
            yield AgentEvent(
                event="error",
                data=(
                    "Azure AI Foundry authentication failed. "
                    "Verify the configured service principal can access the Foundry project."
                ),
                conversation_id=conversation_id,
            )
            yield AgentEvent(event="done", data="failed", conversation_id=conversation_id)
        except ResourceNotFoundError as exc:
            # 리소스 미발견 — Bing 그라운딩 연결 이름 또는 브라우저 자동화 연결 ID 검증 필요
            logger.error("Azure resource lookup failed: %s", exc)
            yield AgentEvent(
                event="error",
                data=(
                    "Azure AI Foundry resource lookup failed. "
                    "Verify BING_GROUNDING_CONNECTION_NAME and any browser automation project connection ID."
                ),
                conversation_id=conversation_id,
            )
            yield AgentEvent(event="done", data="failed", conversation_id=conversation_id)
        except HttpResponseError as exc:
            # Azure HTTP 응답 오류 — 프로젝트 엔드포인트, 모델 배포, 에이전트 도구 구성 검증 필요
            logger.error(
                "Azure AI Foundry request failed for endpoint %s: %s",
                self._settings.azure_ai_project_endpoint,
                exc,
            )
            yield AgentEvent(
                event="error",
                data=(
                    "Azure AI Foundry request failed. "
                    "Verify the project endpoint, model deployment, and configured agent tools."
                ),
                conversation_id=conversation_id,
            )
            yield AgentEvent(event="done", data="failed", conversation_id=conversation_id)
        except OpenAIBadRequestError as exc:
            # 요청 거부 — 업스트림 API가 잘못된 요청을 거부함 (콘텐츠 정책 위반 등)
            logger.error("Azure AI bad request error: %s", exc)
            yield AgentEvent(
                event="error",
                data=_format_bad_request_error(exc),
                conversation_id=conversation_id,
            )
            yield AgentEvent(event="done", data="failed", conversation_id=conversation_id)
        except Exception as exc:  # pragma: no cover - defensive integration guard
            # 예기치 않은 오류 — 모든 미처리 예외에 대한 방어적 가드
            logger.exception("Unexpected Azure AI stream failure: %s", exc)
            yield AgentEvent(
                event="error",
                data=_format_unexpected_error(exc),
                conversation_id=conversation_id,
            )
            yield AgentEvent(event="done", data="failed", conversation_id=conversation_id)
        finally:
            # ── 정리 단계: 모든 미종료 리소스를 해제합니다 ──
            # GenAI 트레이싱: 미종료 도구 스팬 정리 (비정상 종료 시)
            for tool_span in mcp_tool_spans.values():
                try:
                    if tool_span.is_recording():
                        tool_span.set_status(trace.StatusCode.ERROR, "스트림 중단으로 미완료")
                    tool_span.end()
                except Exception:  # pragma: no cover
                    pass
            mcp_tool_spans.clear()  # 도구 스팬 추적 딕셔너리 초기화

            # GenAI 트레이싱: 메인 스팬에 최종 결과를 기록하고 종료합니다.
            if span.is_recording():
                span.set_attribute("gen_ai.completion_state", completion_state)
                span.set_attribute("gen_ai.conversation.id", conversation_id or "")
                if completion_state == "failed":
                    span.set_status(trace.StatusCode.ERROR, "채팅 스트림 실패")
                else:
                    span.set_status(trace.StatusCode.OK)
            span.end()

            # 스팬 컨텍스트 해제 (OpenTelemetry 컨텍스트 스택에서 제거)
            try:
                span_ctx.__exit__(None, None, None)
            except Exception:  # pragma: no cover
                pass

            if credential is not None:
                # Azure 자격 증명 객체의 HTTP 세션을 닫습니다
                logger.info("Closing Azure credential")
                await credential.close()
            logger.info(
                "Azure AI request finished, conversation_id=%s, result=%s",
                conversation_id,
                completion_state,
            )

        if stream_succeeded and conversation_id is not None:
            logger.info("Azure AI response stream completed, conversation_id=%s", conversation_id)
            yield AgentEvent(event="done", data="complete", conversation_id=conversation_id)

    def _build_credential(self) -> ClientSecretCredential | DefaultAzureCredential:
        """구성된 인증 입력에 맞는 Azure 자격 증명을 생성합니다.

        테넌트, 클라이언트, 시크릿이 모두 제공된 경우
        ``ClientSecretCredential``을 사용하고, 그렇지 않으면
        ``DefaultAzureCredential``로 폴백합니다.

        Returns:
            ``AIProjectClient``와 함께 사용할 준비가 된 비동기
            Azure 자격 증명 인스턴스.

        Raises:
            RuntimeError: 필수 프로젝트 설정이 누락되었거나 서비스
                주체 구성이 불완전한 경우.
        """

        # 1단계: 필수 프로젝트 설정이 존재하는지 검증합니다
        self._validate_required_project_settings()
        # 2단계: 서비스 주체 자격 증명 3종(테넌트, 클라이언트, 시크릿)이 모두 제공된 경우
        if (
            self._settings.azure_tenant_id
            and self._settings.azure_client_id
            and self._settings.azure_client_secret
        ):
            # 서비스 주체 기반 인증 — ClientSecretCredential을 사용합니다
            logger.info("Using ClientSecretCredential for Azure AI authentication")
            return ClientSecretCredential(
                tenant_id=self._settings.azure_tenant_id,
                client_id=self._settings.azure_client_id,
                client_secret=self._settings.azure_client_secret,
            )
        # 3단계: 서비스 주체가 없으면 DefaultAzureCredential로 폴백합니다
        # 관리형 ID, Azure CLI 또는 환경 자격 증명 체인을 통해
        # 인증하는 환경을 위해 DefaultAzureCredential으로 폴백합니다.
        logger.info("Using DefaultAzureCredential for Azure AI authentication")
        return DefaultAzureCredential()

    def _validate_required_project_settings(self) -> None:
        """필수 프로젝트 구성이 누락된 경우 명확한 오류를 발생시킵니다.

        ``AZURE_AI_PROJECT_ENDPOINT``,
        ``AZURE_AI_AGENT_NAME``, ``BING_GROUNDING_CONNECTION_NAME``이
        설정되어 있는지, 서비스 주체 자격 증명이 모두 존재하거나
        모두 부재한지 확인합니다.

        Raises:
            RuntimeError: 하나 이상의 필수 환경 변수가 누락되었거나
                서비스 주체 트리플릿이 불완전한 경우.
        """

        # 1단계: 필수 환경 변수 존재 여부를 확인합니다
        missing = [
            name
            for name, value in (
                ("AZURE_AI_PROJECT_ENDPOINT", self._settings.azure_ai_project_endpoint),  # Azure AI 프로젝트 엔드포인트 URL
                ("AZURE_AI_AGENT_NAME", self._settings.azure_ai_agent_name),  # 에이전트 이름
                ("BING_GROUNDING_CONNECTION_NAME", self._settings.bing_grounding_connection_name),  # Bing 그라운딩 연결 이름
            )
            if not value
        ]
        if missing:
            logger.error("Azure AI configuration validation failed, missing=%s", missing)
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
        # 2단계: 서비스 주체 자격 증명의 일관성을 검증합니다 (모두 존재하거나 모두 부재해야 함)
        service_principal_values = {
            "AZURE_TENANT_ID": self._settings.azure_tenant_id,  # Azure AD 테넌트 ID
            "AZURE_CLIENT_ID": self._settings.azure_client_id,  # 서비스 주체 클라이언트 ID
            "AZURE_CLIENT_SECRET": self._settings.azure_client_secret,  # 서비스 주체 클라이언트 시크릿
        }
        provided_credentials = [name for name, value in service_principal_values.items() if value]  # 제공된 자격 증명 목록
        # 일부만 제공된 경우 불완전한 구성 오류를 발생시킵니다
        if 0 < len(provided_credentials) < len(service_principal_values):
            missing_service_principal_values = [
                name for name, value in service_principal_values.items() if not value
            ]
            raise RuntimeError(
                "Incomplete Azure service principal configuration. Missing: "
                + ", ".join(missing_service_principal_values)
            )
        logger.info("Azure AI configuration validation succeeded")

    async def _resolve_agent(self, project_client: AIProjectClient):
        """구성된 에이전트를 가져오고 구성 드리프트가 감지되면 버전을 갱신합니다.

        이름으로 에이전트를 조회합니다. 최신 버전의 정의가 현재 설정과
        일치하면 재사용하고, 그렇지 않으면 새 버전을 생성합니다.

        Args:
            project_client: 인증된 ``AIProjectClient`` 인스턴스.

        Returns:
            기존 또는 새로 생성된 해석된 에이전트 버전 객체.
        """

        latest_version = None  # 기존 에이전트의 최신 버전 (없으면 None)
        try:
            # 1단계: 이름으로 기존 에이전트를 검색합니다
            logger.info("Searching for existing agent, agent_name=%s", self._settings.azure_ai_agent_name)
            await project_client.agents.get(agent_name=self._settings.azure_ai_agent_name)
            # 2단계: 최신 에이전트 버전을 가져옵니다
            latest_version = await self._get_latest_agent_version(project_client, self._settings.azure_ai_agent_name)
        except ResourceNotFoundError:
            # 에이전트가 존재하지 않으면 새 버전을 생성합니다
            logger.info(
                "Existing agent not found, creating new agent version, agent_name=%s",
                self._settings.azure_ai_agent_name,
            )

        # 3단계: 현재 설정에서 도구 목록과 에이전트 정의를 구성합니다
        tools = await self._build_tools(project_client)
        definition = self._build_prompt_agent_definition(tools)
        # 4단계: 비교를 위해 정의를 정규화하고 해시를 생성합니다
        normalized_definition = self._normalize_definition_for_comparison(definition)
        config_hash = self._build_agent_config_hash(normalized_definition)  # SHA-256 해시로 구성 변경 감지

        # 5단계: 기존 버전과 현재 설정을 비교하여 드리프트 여부를 확인합니다
        if latest_version is not None and self._agent_version_matches_expected(
            latest_version, normalized_definition, config_hash
        ):
            logger.info(
                "Reusing existing Azure AI agent version, agent_name=%s, version=%s",
                self._settings.azure_ai_agent_name,
                getattr(latest_version, "version", None),
            )
            return latest_version

        # 6단계: 기존 버전이 있지만 구성이 변경된 경우 — 드리프트 감지
        if latest_version is not None:
            logger.info(
                "Azure AI agent configuration drift detected; creating updated version, "
                "agent_name=%s, current_version=%s",
                self._settings.azure_ai_agent_name,
                getattr(latest_version, "version", None),
            )

        # 7단계: 새 에이전트 버전을 생성합니다 (신규 또는 드리프트 감지 시)
        return await self._create_agent_version(project_client, definition, config_hash)

    def _build_prompt_agent_definition(self, tools: list[Any]) -> PromptAgentDefinition:
        """이 애플리케이션의 정규 프롬프트 에이전트 정의를 구성합니다.

        Args:
            tools: 에이전트에 첨부할 도구 객체 목록 (Bing 그라운딩,
                웹 검색, 브라우저 자동화 등).

        Returns:
            애플리케이션의 모델, 지시사항, 도구로 구성된
            ``PromptAgentDefinition``.
        """

        return PromptAgentDefinition(
            kind=_AGENT_CONFIG_KIND,
            model=self._settings.azure_ai_model,
            instructions=self._settings.azure_ai_agent_instructions,
            tools=tools,
        )

    def _build_agent_config_hash(self, normalized_definition: dict[str, Any]) -> str:
        """이 백엔드가 제어하는 에이전트 필드에 대한 안정적인 해시를 생성합니다.

        Args:
            normalized_definition: 이 애플리케이션이 관리하는 필드만
                포함하는 ``_normalize_definition_for_comparison``이
                생성한 딕셔너리.

        Returns:
            JSON 직렬화된 정의의 16진수 인코딩 SHA-256 다이제스트.
        """

        encoded = json.dumps(normalized_definition, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _normalize_definition_for_comparison(self, definition: Any) -> dict[str, Any]:
        """에이전트 정의를 이 백엔드가 제어하는 안정적인 필드로 축소합니다.

        ``kind``, ``model``, ``instructions``, 정렬된 ``tools`` 목록을
        추출하여 SDK 직렬화 순서와 관계없이 두 정의를
        비교할 수 있게 합니다.

        Args:
            definition: 정규화할 에이전트 정의 객체 또는 딕셔너리.

        Returns:
            정규화된 ``kind``, ``model``, ``instructions``, ``tools``
            키만 포함하는 딕셔너리.
        """

        serialized = _safe_serialize(definition)
        if not isinstance(serialized, dict):
            return {}
        tools = serialized.get("tools") or []
        if isinstance(tools, list):
            tools = sorted(
                tools,
                key=lambda tool: json.dumps(_safe_serialize(tool), sort_keys=True),
            )
        return {
            "kind": serialized.get("kind"),
            "model": serialized.get("model"),
            "instructions": serialized.get("instructions"),
            "tools": tools,
        }

    def _agent_version_matches_expected(
        self,
        latest_version: Any,
        expected_definition: dict[str, Any],
        expected_config_hash: str,
    ) -> bool:
        """최신 원격 버전이 현재 설정과 이미 일치하면 True를 반환합니다.

        메타데이터 구성 해시로 먼저 비교하고, 폴백으로
        정규화된 정의 동등성을 확인합니다.

        Args:
            latest_version: Azure AI 프로젝트에서 가져온 가장
                최근 에이전트 버전 객체.
            expected_definition: 원하는 에이전트 구성을 나타내는
                정규화된 정의 딕셔너리.
            expected_config_hash: 예상 정의의 SHA-256 16진수
                다이제스트.

        Returns:
            원격 버전이 일치하면 ``True``; 그렇지 않으면 ``False``.
        """

        serialized_version = _safe_serialize(latest_version)
        if not isinstance(serialized_version, dict):
            return False

    # 메타데이터에서 구성 해시로 빠른 비교를 시도합니다
        metadata = serialized_version.get("metadata")
        if isinstance(metadata, dict) and metadata.get(_AGENT_CONFIG_HASH_KEY) == expected_config_hash:
            return True

        # 해시가 없거나 불일치하면 정규화된 정의의 동등성을 비교합니다 (폴백)
        current_definition = serialized_version.get("definition")
        if current_definition is None:
            return False

        return self._normalize_definition_for_comparison(
            current_definition
        ) == expected_definition

    async def _create_agent_version(
        self,
        project_client: AIProjectClient,
        definition: PromptAgentDefinition,
        config_hash: str,
    ):
        """구성된 텔레그램 봇 에이전트에 대한 관리형 프롬프트 에이전트 버전을 생성합니다.

        Args:
            project_client: 인증된 ``AIProjectClient`` 인스턴스.
            definition: 새 버전으로 등록할
                ``PromptAgentDefinition``.
            config_hash: 향후 조회 시 드리프트를 빠르게 감지할 수
                있도록 메타데이터에 저장하는 SHA-256 16진수 다이제스트.

        Returns:
            새로 생성된 에이전트 버전 객체.
        """

        tools = self._normalize_definition_for_comparison(definition).get("tools", [])
        logger.info(
            "Creating new Azure AI agent version, agent_name=%s, model=%s, tool_count=%d",
            self._settings.azure_ai_agent_name,
            self._settings.azure_ai_model,
            len(tools),
        )
        return await project_client.agents.create_version(
            agent_name=self._settings.azure_ai_agent_name,
            definition=definition,
            metadata={_AGENT_CONFIG_HASH_KEY: config_hash},
            description="Telegram bot backend agent",
        )

    async def _build_tools(self, project_client: AIProjectClient) -> list[Any]:
        """프롬프트 에이전트에 대한 구성된 도구 목록을 구성합니다.

        항상 Bing 그라운딩 및 웹 검색 도구를 포함합니다. 프로젝트
        연결 ID가 구성된 경우 선택적으로 브라우저 자동화 도구를
        추가합니다.

        Args:
            project_client: Bing 그라운딩 연결을 해석하는 데 사용하는
                인증된 ``AIProjectClient``.

        Returns:
            ``PromptAgentDefinition``에 첨부할 준비가 된
            도구 객체 목록.
        """

        logger.info(
            "Building Azure AI agent tools, bing_connection_name=%s, browser_automation_enabled=%s",
            self._settings.bing_grounding_connection_name,
            bool(self._settings.browser_automation_project_connection_id),
        )
        # 1단계: Bing 그라운딩 연결을 해석합니다
        bing_connection = await project_client.connections.get(self._settings.bing_grounding_connection_name)
        logger.info("Resolved Bing grounding connection successfully")
        # 2단계: 필수 도구를 구성합니다 — Bing 그라운딩 및 웹 검색
        tools: list[Any] = [
            # Bing 그라운딩 도구: 검색 결과를 에이전트 응답의 근거로 사용합니다
            BingGroundingTool(
                bing_grounding=BingGroundingSearchToolParameters(
                    search_configurations=[
                        BingGroundingSearchConfiguration(project_connection_id=bing_connection.id),
                    ]
                )
            ),
            # 웹 검색 프리뷰 도구: 사용자 위치 기반 웹 검색 (한국 서울로 설정)
            WebSearchPreviewTool(
                user_location=ApproximateLocation(country="KR", city="Seoul", region="Seoul"),
            ),
        ]

        # 3단계: 브라우저 자동화 도구를 선택적으로 추가합니다 (프로젝트 연결 ID가 구성된 경우)
        if self._settings.browser_automation_project_connection_id:
            tools.append(
                BrowserAutomationPreviewTool(
                    browser_automation_preview=BrowserAutomationToolParameters(
                        connection=BrowserAutomationToolConnectionParameters(
                            project_connection_id=self._settings.browser_automation_project_connection_id,
                        )
                    )
                )
            )
            logger.info(
                "Enabled browser automation tool for configured project connection"
            )
        else:
            logger.info("Browser automation tool disabled because no project connection ID is configured.")

        logger.info("Azure AI agent tools built successfully, tool_count=%d", len(tools))
        return tools

    async def _get_latest_agent_version(
        self, project_client: AIProjectClient, agent_name: str
    ) -> Any | None:
        """사용 가능한 경우 구성된 에이전트의 최신 버전을 반환합니다.

        Args:
            project_client: 인증된 ``AIProjectClient`` 인스턴스.
            agent_name: 조회할 등록된 에이전트 이름.

        Returns:
            최신 에이전트 버전 객체, 또는 버전이 존재하지 않으면
            ``None``.
        """

        async for version in project_client.agents.list_versions(agent_name=agent_name, order="desc", limit=1):
            return version
        return None

    async def _build_agent_reference(self, project_client: AIProjectClient, agent: Any) -> dict[str, str]:
        """Responses API가 기대하는 에이전트 참조 페이로드를 반환합니다.

        해석된 에이전트 객체에 ``version`` 속성이 없는 경우
        에이전트 버전 목록을 조회하여 폴백합니다.

        Args:
            project_client: 인증된 ``AIProjectClient`` 인스턴스.
            agent: 최소한 ``name`` 속성을 가진 해석된
                에이전트 객체.

        Returns:
            ``extra_body`` 페이로드에 적합한 ``type``, ``name``,
            선택적으로 ``version`` 키를 가진 딕셔너리.

        Raises:
            RuntimeError: 에이전트에 이름이 포함되지 않은 경우.
        """

        agent_name = getattr(agent, "name", None)
        if not agent_name:
            raise RuntimeError("Azure AI agent did not include a name.")

        agent_version = getattr(agent, "version", None)
        if agent_version is None:
            logger.info(
                "Agent version missing on resolved agent, listing latest version, agent_name=%s",
                agent_name,
            )
            async for version in project_client.agents.list_versions(agent_name=agent_name, order="desc", limit=1):
                agent_version = getattr(version, "version", None)
                if agent_version:
                    break

        extra_agent = {"type": "agent_reference", "name": agent_name}
        if agent_version:
            extra_agent["version"] = str(agent_version)
        logger.info(
            "Built Azure AI agent reference, agent_name=%s, version=%s",
            agent_name,
            extra_agent.get("version"),
        )
        return extra_agent

    async def _ensure_conversation(
        self,
        *,
        openai_client: Any,
        request: ChatRequest,
        latest_user_content: Any,
    ) -> tuple[str, bool]:
        """기존 대화 ID를 재사용하거나 새 대화를 한 번 생성합니다.

        Args:
            openai_client: Azure AI 프로젝트 클라이언트에서 얻은
                OpenAI 호환 클라이언트.
            request: 기존 ``conversation_id``를 포함할 수 있는
                수신 채팅 요청.
            latest_user_content: 새 대화를 생성해야 할 때 사용하는
                정규화된 최신 사용자 메시지 콘텐츠.

        Returns:
            ``(conversation_id, created_now)`` 튜플로, *created_now*는
            이 호출에서 새 대화가 생성된 경우 ``True``.
        """

        if request.conversation_id:
            logger.info("Reusing existing Azure AI conversation, conversation_id=%s", request.conversation_id)
            return request.conversation_id, False

        return await self._create_fresh_conversation(
            openai_client=openai_client,
            request=request,
            latest_user_content=latest_user_content,
        )

    async def _create_fresh_conversation(
        self,
        *,
        openai_client: Any,
        request: ChatRequest,
        latest_user_content: Any,
    ) -> tuple[str, bool]:
        """전체 최신 사용자 메시지로 항상 새 대화를 생성합니다.

        Args:
            openai_client: Azure AI 프로젝트 클라이언트에서 얻은
                OpenAI 호환 클라이언트.
            request: 수신 채팅 요청 (로깅 컨텍스트에 사용).
            latest_user_content: 새 대화를 시작할 때 사용할
                정규화된 최신 사용자 메시지 콘텐츠.

        Returns:
            새로 생성된 대화 ID를 나타내는
            ``(conversation_id, True)`` 튜플.
        """

        if _content_is_multimodal(latest_user_content):
            logger.info("Multimodal content detected; creating conversation with inline image content.")

        user_prompt_preview = ""
        if isinstance(latest_user_content, str):
            user_prompt_preview = latest_user_content
        elif isinstance(latest_user_content, list):
            user_prompt_preview = _extract_text_from_multimodal(latest_user_content)
        logger.info(
            "Creating new Azure AI conversation with user prompt: prompt=%s",
            user_prompt_preview,
        )
        conversation = await openai_client.conversations.create(
            items=[{"type": "message", "role": "user", "content": latest_user_content}],
        )
        logger.info("Created Azure AI conversation, conversation_id=%s", conversation.id)
        return conversation.id, True

    async def _stream_events_from_item(
        self,
        item: Any,
        conversation_id: str,
        emitted_output_item_ids: set[str],
        mcp_tool_start_times: dict[str, float] | None = None,
        mcp_tool_spans: dict[str, trace.Span] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """SDK 스트림 항목을 리포지토리의 SSE 이벤트 엔벨로프로 변환합니다.

        ``item.type``에 따라 디스패치하여 적절한 ``status``, ``message``
        또는 인용 이벤트를 발행하며, *emitted_output_item_ids*를 사용하여
        텍스트 중복 발행을 방지합니다.

        Args:
            item: Responses API의 단일 SDK 스트림 이벤트.
            conversation_id: 발행되는 모든 이벤트에 포함되는
                현재 대화 식별자.
            emitted_output_item_ids: 이미 발행된 텍스트 부분을 추적하는
                중복 제거 키의 가변 집합. 이벤트가 발행될 때
                내부에서 업데이트됩니다.
            mcp_tool_start_times: MCP 도구 호출 시작 시간을 추적하는
                딕셔너리. 키는 출력 항목 ID이며 값은 ``time.monotonic()``
                타임스탬프입니다.
            mcp_tool_spans: MCP 도구 호출에 대한 OpenTelemetry 스팬을
                추적하는 딕셔너리. 키는 출력 항목 ID이며 값은 스팬 객체입니다.

        Yields:
            AgentEvent: 스트림 항목에서 파생된 SSE 호환 이벤트.
        """
        if mcp_tool_start_times is None:
            mcp_tool_start_times = {}  # MCP 도구 시작 시간 추적 딕셔너리 초기화
        if mcp_tool_spans is None:
            mcp_tool_spans = {}  # MCP 도구 스팬 추적 딕셔너리 초기화

        item_type = getattr(item, "type", "")  # SDK 이벤트 타입을 추출합니다
        logger.info("Azure AI stream event received, conversation_id=%s, item_type=%s", conversation_id, item_type)
        # ── 이벤트 타입: response.created — 응답 스트림 시작 알림 ──
        if item_type == "response.created" and getattr(getattr(item, "response", None), "id", None):
            logger.info("Azure AI response created, response_id=%s", item.response.id)
            yield AgentEvent(event="status", data="Azure AI response started.", conversation_id=conversation_id)
            return

        # ── 이벤트 타입: response.output_text.delta — 텍스트 청크 스트리밍 (증분 전송) ──
        if item_type == "response.output_text.delta" and getattr(item, "delta", None):
            text_keys = _collect_response_text_keys(item)  # 중복 제거용 키를 수집합니다
            emitted_output_item_ids.update(text_keys)  # 발행된 텍스트 키를 기록합니다
            logger.debug(
                "Azure AI response delta received, conversation_id=%s, delta_length=%d, delta_text=%s",
                conversation_id,
                len(item.delta),
                item.delta,
            )
            yield AgentEvent(event="message", data=item.delta, conversation_id=conversation_id)
            return

        # ── 이벤트 타입: response.output_text / response.output_text.done — 완료된 텍스트 출력 ──
        if item_type in {"response.output_text", "response.output_text.done"} and getattr(item, "text", None):
            text_keys = _collect_response_text_keys(item)  # 중복 제거용 키를 수집합니다
            # 이미 델타로 발행된 텍스트인 경우 건너뜁니다
            if text_keys & emitted_output_item_ids:
                return
            logger.info(
                "Azure AI assistant response text: conversation_id=%s, item_type=%s, text_length=%d, text=%s",
                conversation_id,
                item_type,
                len(item.text),
                item.text,
            )
            if item_type == "response.output_text.done":
                # 터미널 텍스트 이벤트만 이 키를 표시하므로, 선행하는
                # 비완료 response.output_text 이벤트가 델타가 발행되지
                # 않았을 때 최종 done 페이로드를 억제하지 않습니다.
                emitted_output_item_ids.update(text_keys)
                yield AgentEvent(event="message", data=item.text, conversation_id=conversation_id)
            return

        # ── 이벤트 타입: response.output_item.added — 새 출력 항목 추가 (도구 호출 시작 등) ──
        if item_type == "response.output_item.added" and getattr(item, "item", None):
            # MCP 승인 요청 확인 — 승인 메시지가 있으면 상태 이벤트로 발행합니다
            approval_message = _format_mcp_approval_message(item.item)
            if approval_message:
                logger.info(
                    "Azure AI tool approval request: conversation_id=%s, message=%s",
                    conversation_id,
                    approval_message,
                )
                yield AgentEvent(event="status", data=approval_message, conversation_id=conversation_id)
                return
            # 비승인 도구 활동 메시지 생성 (mcp_call, memory_search_call 등)
            activity_message = _format_activity_status(item.item, completed=False)
            if activity_message:
                # MCP 도구 호출의 시작 시간 및 OpenTelemetry 스팬 추적을 시작합니다
                output_item_id = getattr(item.item, "id", None)  # 출력 항목의 고유 ID
                serialized_item = _safe_serialize(item.item)
                if isinstance(serialized_item, dict) and serialized_item.get("type") == "mcp_call" and output_item_id:
                    mcp_tool_start_times[output_item_id] = time.monotonic()  # 도구 호출 시작 시간 기록
                    tool_name = serialized_item.get("name") or "unknown_tool"  # 도구 이름 추출
                    server_label = serialized_item.get("server_label") or ""  # MCP 서버 레이블 추출
                    # GenAI 트레이싱: 도구 호출 스팬 시작
                    tool_span = _tracer.start_span(
                        f"tool-call:{tool_name}",
                        attributes={
                            "gen_ai.agent.name": self._settings.azure_ai_agent_name,
                            "gen_ai.provider.name": "microsoft.foundry",
                            "gen_ai.tool.name": tool_name,
                            "gen_ai.tool.type": "mcp_call",
                            "mcp.server_label": server_label,
                            "gen_ai.conversation.id": conversation_id or "",
                        },
                    )
                    mcp_tool_spans[output_item_id] = tool_span  # 스팬을 추적 딕셔너리에 저장
                elif isinstance(serialized_item, dict) and output_item_id:
                    # memory_search_call 등 기타 도구 호출 스팬 생성
                    tool_type = serialized_item.get("type") or "unknown"  # 도구 타입 추출
                    tool_span = _tracer.start_span(
                        f"tool-call:{tool_type}",
                        attributes={
                            "gen_ai.agent.name": self._settings.azure_ai_agent_name,
                            "gen_ai.provider.name": "microsoft.foundry",
                            "gen_ai.tool.type": tool_type,
                            "gen_ai.conversation.id": conversation_id or "",
                        },
                    )
                    mcp_tool_spans[output_item_id] = tool_span  # 스팬을 추적 딕셔너리에 저장
                logger.info(
                    "Azure AI tool activity started: conversation_id=%s, message=%s",
                    conversation_id,
                    activity_message,
                )
                yield AgentEvent(event="status", data=activity_message, conversation_id=conversation_id)
            return

        # ── 이벤트 타입: response.output_item.done — 출력 항목 완료 (도구 결과, 텍스트 등) ──
        if item_type == "response.output_item.done" and getattr(item, "item", None):
            output_item = item.item  # 완료된 출력 항목 객체
            output_item_type = getattr(output_item, "type", None)  # 출력 항목 타입
            output_index = getattr(item, "output_index", None)  # 응답 내 출력 순서 인덱스
            logger.info(
                "Azure AI output item completed, conversation_id=%s, output_item_type=%s, output_item_id=%s",
                conversation_id,
                output_item_type,
                getattr(output_item, "id", None),
            )
            # MCP 승인 요청 완료는 무시합니다 (이미 added에서 처리됨)
            approval_message = _format_mcp_approval_message(output_item)
            if approval_message:
                return

            # 도구 활동 완료 메시지를 생성합니다
            activity_message = _format_activity_status(output_item, completed=True)
            if activity_message:
                # MCP 도구 호출의 경과 시간을 계산하고 OpenTelemetry 스팬을 종료합니다
                output_item_id = getattr(output_item, "id", None)  # 출력 항목 ID
                if output_item_id and output_item_id in mcp_tool_start_times:
                    elapsed_ms = (time.monotonic() - mcp_tool_start_times.pop(output_item_id)) * 1000  # 경과 시간(ms) 계산
                    activity_message = f"{activity_message} ({elapsed_ms:,.0f} ms)"  # 경과 시간을 메시지에 추가
                    logger.info(
                        "Azure AI tool activity completed: conversation_id=%s, message=%s, elapsed_ms=%.2f",
                        conversation_id,
                        activity_message,
                        elapsed_ms,
                    )
                    # GenAI 트레이싱: 도구 호출 스팬에 결과(상태, 오류, 소요 시간)를 기록 후 종료
                    if output_item_id in mcp_tool_spans:
                        tool_span = mcp_tool_spans.pop(output_item_id)
                        serialized_output = _safe_serialize(output_item)
                        if isinstance(serialized_output, dict):
                            tool_status = serialized_output.get("status", "unknown")  # 도구 실행 상태
                            tool_error = serialized_output.get("error")  # 도구 실행 오류 메시지
                        else:
                            tool_status = "unknown"
                            tool_error = None
                        if tool_span.is_recording():
                            tool_span.set_attribute("gen_ai.tool.duration_ms", elapsed_ms)
                            tool_span.set_attribute("gen_ai.tool.status", tool_status)
                            if tool_error:
                                tool_span.set_attribute("gen_ai.tool.error", str(tool_error))
                                tool_span.set_status(trace.StatusCode.ERROR, str(tool_error))
                            else:
                                tool_span.set_status(trace.StatusCode.OK)
                        tool_span.end()
                else:
                    logger.info(
                        "Azure AI tool activity completed: conversation_id=%s, message=%s",
                        conversation_id,
                        activity_message,
                    )
                    # 시작 시간 없이 완료된 스팬도 종료합니다 (타이밍 데이터 없는 경우)
                    if output_item_id and output_item_id in mcp_tool_spans:
                        tool_span = mcp_tool_spans.pop(output_item_id)
                        if tool_span.is_recording():
                            tool_span.set_status(trace.StatusCode.OK)
                        tool_span.end()
                yield AgentEvent(event="status", data=activity_message, conversation_id=conversation_id)
                return

            # 완료된 출력 항목에서 텍스트 파트를 추출하여 발행합니다 (중복 제거 적용)
            for part_keys, message in _extract_output_item_text_parts(output_item, output_index):
                if part_keys & emitted_output_item_ids:
                    continue
                emitted_output_item_ids.update(part_keys)
                yield AgentEvent(event="message", data=message, conversation_id=conversation_id)
            return

        # ── 이벤트 타입: response.content_part.done — 콘텐츠 파트 완료 (인용 어노테이션 추출) ──
        if item_type == "response.content_part.done" and getattr(item, "part", None):
            logger.info("Azure AI content part completed, conversation_id=%s", conversation_id)
            for message in _extract_annotation_messages(item.part):
                logger.info("Azure AI citation status emitted, conversation_id=%s", conversation_id)
                yield AgentEvent(event="status", data=message, conversation_id=conversation_id)
            return

        # ── 이벤트 타입: response.completed — 전체 응답 완료 (토큰 사용량 보고) ──
        if item_type == "response.completed":
            usage = getattr(getattr(item, "response", None), "usage", None)  # 토큰 사용량 정보를 추출합니다
            if usage:
                input_tokens = getattr(usage, "input_tokens", "N/A")  # 입력 토큰 수
                output_tokens = getattr(usage, "output_tokens", "N/A")  # 출력 토큰 수
                total_tokens = getattr(usage, "total_tokens", "N/A")  # 전체 토큰 수
                summary = f"Token usage - input: {input_tokens}, output: {output_tokens}, total: {total_tokens}"
                logger.info(
                    (
                        "Azure AI response completed, conversation_id=%s, "
                        "input_tokens=%s, output_tokens=%s, total_tokens=%s"
                    ),
                    conversation_id,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                )
                # GenAI 트레이싱: 현재 스팬에 토큰 사용량 기록
                current_span = trace.get_current_span()
                if current_span.is_recording():
                    if isinstance(input_tokens, int):
                        current_span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
                    if isinstance(output_tokens, int):
                        current_span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
                    if isinstance(total_tokens, int):
                        current_span.set_attribute("gen_ai.usage.total_tokens", total_tokens)
                yield AgentEvent(event="status", data=summary, conversation_id=conversation_id)
            else:
                logger.info("Azure AI response completed without usage details, conversation_id=%s", conversation_id)
            return

        # ── 인식되지 않은 이벤트 타입 — 디버그 로깅 후 무시합니다 ──
        logger.debug("Ignored Azure AI stream item: %s", _safe_serialize(item))

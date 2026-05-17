"""에이전트 프레임워크: 스트리밍 채팅 에이전트의 기본 클래스.

모든 채팅 에이전트 구현의 추상적 기반을 정의합니다.
서브클래스는 ``stream()`` 메서드를 구현하여 특정 AI 서비스
(예: Azure AI Foundry)와의 통합을 제공합니다.
"""

# 표준 라이브러리 임포트
from abc import ABC, abstractmethod  # 추상 기본 클래스 및 추상 메서드 데코레이터
from collections.abc import AsyncIterator  # 비동기 이터레이터 타입 힌트
from dataclasses import dataclass  # 데이터 클래스 데코레이터

# 채팅 요청 모델 임포트
from app.models import ChatRequest


@dataclass
class AgentEvent:
    """에이전트의 스트리밍 응답 중 발행되는 단일 이벤트.

    SSE(Server-Sent Events)를 통해 프론트엔드에 전송되는
    이벤트 데이터 구조입니다.

    Attributes:
        event: 이벤트 타입 — 'status' (상태 업데이트), 'message' (텍스트 청크),
            'error' (오류 발생), 또는 'done' (스트림 완료).
        data: 페이로드 문자열 (스트리밍 텍스트, 상태 메시지 또는 오류 상세).
        conversation_id: 다중 턴 추적을 위한 선택적 대화 식별자.
    """

    event: str  # SSE 이벤트 타입 ("status", "message", "error", "done")
    data: str  # 이벤트 데이터 (텍스트 청크, 상태 메시지, 오류 상세 등)
    conversation_id: str | None = None  # 대화 ID (다중 턴 대화 추적용, 선택사항)


class BaseAgent(ABC):
    """스트리밍 채팅 에이전트의 추상 기본 클래스.

    서브클래스는 ``stream()``을 구현하여 오케스트레이터가
    SSE 응답으로 전달하는 ``AgentEvent`` 항목을 yield합니다.
    구체적인 AI 서비스 통합은 서브클래스에서 구현합니다.
    """

    @abstractmethod
    async def stream(self, request: ChatRequest) -> AsyncIterator[AgentEvent]:
        """주어진 채팅 요청에 대한 스트리밍 이벤트를 yield합니다.

        서브클래스에서 반드시 구현해야 하는 추상 메서드입니다.
        마지막 항목으로 최소 하나의 ``done`` 이벤트를 yield해야 합니다.

        Args:
            request: 프론트엔드에서 전송된 채팅 요청 객체.

        Yields:
            ``AgentEvent`` 인스턴스 (status → message 청크들 → done 순서).
        """
        ...  # pragma: no cover — 추상 메서드이므로 테스트 커버리지에서 제외

"""에이전트 프레임워크 패키지 — 스트리밍 에이전트의 기본 클래스와 오케스트레이터.

이 패키지는 Azure AI Foundry 에이전트를 감싸는 추상화 계층을 제공합니다.
BaseAgent(추상 기본 클래스)와 AgentOrchestrator(라우팅/오케스트레이션)를
통해 채팅 요청을 처리하고 SSE 이벤트 스트림으로 응답합니다.
"""

# 비동기 이터레이터 타입 힌트 (스트리밍 응답 제너레이터용)
from collections.abc import AsyncIterator

# 에이전트 프레임워크 기본 클래스와 이벤트 데이터 모델 임포트
from app.agent_framework.base import AgentEvent, BaseAgent
# 채팅 요청 모델 임포트
from app.models import ChatRequest

# 공개 API: 이 패키지에서 외부에 노출하는 클래스/타입 목록
__all__ = ["AgentEvent", "AgentOrchestrator", "BaseAgent"]


class AgentOrchestrator:
    """채팅 요청을 구성된 기본 에이전트로 라우팅합니다.

    기본 ``BaseAgent.stream()`` 구현에 위임하여
    SSE 전송 계층을 위한 ``AgentEvent`` 항목을 yield하는
    단일 ``stream_chat()`` 진입점을 제공합니다.
    향후 다중 에이전트 라우팅으로 확장할 수 있는 구조입니다.
    """

    def __init__(self, default_agent: BaseAgent) -> None:
        """오케스트레이터를 초기화합니다.

        Args:
            default_agent: 채팅 요청을 처리할 기본 에이전트 인스턴스.
        """
        # 기본 에이전트 참조 저장 (모든 채팅 요청이 이 에이전트로 라우팅됨)
        self._default_agent = default_agent

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[AgentEvent]:
        """기본 에이전트로부터 채팅 이벤트를 스트리밍합니다.

        Args:
            request: 프론트엔드에서 전송된 채팅 요청.

        Yields:
            에이전트가 생성하는 ``AgentEvent`` 인스턴스 (status, message, error, done).
        """
        # 기본 에이전트의 stream() 메서드에 위임하여 이벤트를 순차적으로 yield
        async for event in self._default_agent.stream(request):
            yield event

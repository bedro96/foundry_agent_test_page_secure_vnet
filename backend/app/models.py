"""API 엔드포인트용 Pydantic 요청/응답 모델 정의.

채팅, 인증, MCP, 음성 변환 등 모든 API 스키마를 포함합니다.
프론트엔드와 백엔드 간의 데이터 교환 형식을 정의하며,
Pydantic을 통해 입력 검증을 자동으로 수행합니다.
"""

# 표준 라이브러리 임포트
from typing import Any, Literal, Union  # 타입 힌트를 위한 유틸리티

# Pydantic 임포트: 데이터 검증 및 직렬화
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator


# ── 콘텐츠 파트 (멀티모달 메시지 구성 요소) ─────────────────────────────────

class TextContentPart(BaseModel):
    """``input_text`` 타입 판별자를 사용하는 텍스트 콘텐츠 파트.

    최신 API 형식의 텍스트 메시지 구성 요소입니다.
    """

    type: Literal["input_text"] = "input_text"  # 콘텐츠 타입 판별자
    text: str = Field(min_length=1)  # 텍스트 내용 (최소 1자 이상)


class LegacyTextContentPart(BaseModel):
    """레거시 ``text`` 타입 판별자를 사용하는 텍스트 콘텐츠 파트.

    이전 버전 클라이언트와의 호환성을 위해 유지됩니다.
    """

    type: Literal["text"] = "text"  # 레거시 콘텐츠 타입 판별자
    text: str = Field(min_length=1)  # 텍스트 내용 (최소 1자 이상)


class ImageUrlContentPart(BaseModel):
    """``input_image`` 타입 판별자를 사용하는 이미지 콘텐츠 파트.

    ``image_url`` 필드는 ``data:`` URI 또는 ``https`` URL을 허용합니다.
    멀티모달 채팅(텍스트+이미지) 요청에서 사용됩니다.
    """

    type: Literal["input_image"] = "input_image"  # 이미지 콘텐츠 타입 판별자
    image_url: str  # 이미지 URL 또는 data:image/jpeg;base64,... 형식의 데이터 URI
    detail: Literal["low", "high", "auto", "original"] = "auto"  # 이미지 해상도 수준


class LegacyImageUrlDetail(BaseModel):
    """``LegacyImageUrlContentPart``에서 사용하는 중첩 URL 래퍼.

    레거시 형식에서 이미지 URL을 감싸는 객체입니다.
    """

    url: str  # 이미지 URL 또는 data:image/jpeg;base64,... 형식의 데이터 URI


class LegacyImageUrlContentPart(BaseModel):
    """레거시 ``image_url`` 타입 판별자를 사용하는 이미지 콘텐츠 파트.

    이전 버전 OpenAI API 형식과의 호환성을 위해 유지됩니다.
    """

    type: Literal["image_url"] = "image_url"  # 레거시 이미지 콘텐츠 타입 판별자
    image_url: LegacyImageUrlDetail  # 중첩된 이미지 URL 객체


# 멀티모달 콘텐츠 파트의 판별 유니온 타입 (텍스트 또는 이미지)
ContentPart = Union[TextContentPart, LegacyTextContentPart, ImageUrlContentPart, LegacyImageUrlContentPart]


# ── 채팅 요청/응답 모델 ─────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    """채팅 대화의 단일 메시지.

    Attributes:
        role: 발신자 역할 — ``"system"``, ``"user"``, 또는 ``"assistant"``.
        content: 메시지 본문, 일반 문자열 또는 멀티모달
            ``ContentPart`` 객체 목록.
    """

    role: Literal["system", "user", "assistant"] = "user"  # 메시지 발신자 역할
    content: Union[str, list[ContentPart]] = Field(...)  # 메시지 내용 (텍스트 또는 멀티모달)

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: Union[str, list]) -> Union[str, list]:
        """메시지 콘텐츠가 비어 있거나 빈 목록이 아닌지 확인합니다.

        Args:
            v: 검증할 원시 콘텐츠 값.

        Returns:
            변경 없이 검증된 콘텐츠.

        Raises:
            ValueError: 문자열이 공백이거나 목록이 비어 있는 경우.
        """
        if isinstance(v, str) and not v.strip():
            raise ValueError("content must not be empty")
        if isinstance(v, list) and len(v) == 0:
            raise ValueError("content list must not be empty")
        return v


class ChatRequest(BaseModel):
    """채팅 엔드포인트의 인바운드 요청 본문.

    프론트엔드에서 전송하는 채팅 요청을 정의합니다.
    기존 대화를 이어가거나 새 대화를 시작할 수 있습니다.

    Attributes:
        messages: 대화를 구성하는 채팅 메시지의 순서 목록.
        conversation_id: 이어서 진행할 기존 대화 UUID (선택사항).
        metadata: AI 에이전트에 전달할 키-값 쌍 (선택사항).
    """

    messages: list[ChatMessage] = Field(min_length=1)  # 최소 1개 이상의 메시지 필수
    conversation_id: str | None = None  # 기존 대화 ID (없으면 새 대화 생성)
    metadata: dict[str, str] | None = None  # 에이전트에 전달할 추가 메타데이터


class ChatStreamEvent(BaseModel):
    """스트리밍 채팅 응답 중 발행되는 단일 Server-Sent Event.

    SSE를 통해 프론트엔드에 실시간으로 전송되는 이벤트 구조입니다.

    Attributes:
        event: 이벤트 타입 — ``"status"``, ``"message"``, ``"error"``, 또는
            ``"done"``.
        data: 페이로드 문자열 (메시지 청크, 상태 텍스트 또는 오류 상세).
        conversation_id: 대화 UUID, 확정된 후 포함됨.
    """

    event: Literal["status", "message", "error", "done"]  # SSE 이벤트 타입
    data: str  # 이벤트 페이로드 데이터
    conversation_id: str | None = None  # 대화 식별자 (확정 후 전송)


# ── 음성 변환 모델 ──────────────────────────────────────────────────────────

class TranscriptionRequest(BaseModel):
    """음성-텍스트 변환 엔드포인트의 요청 본문.

    프론트엔드에서 녹음된 음성 데이터를 Base64로 인코딩하여 전송합니다.
    Azure Speech API를 통해 텍스트로 변환됩니다.

    Attributes:
        audio_base64: Base64 인코딩된 오디오 데이터.
        mime_type: 오디오의 MIME 타입 (예: ``"audio/webm"``).
        file_name: 로깅용 원본 파일명 (선택사항).
        language: 음성 인식용 BCP-47 언어 태그 (기본값 ``"ko-KR"``).
    """

    audio_base64: str = Field(min_length=1)  # Base64 인코딩된 오디오 (필수)
    mime_type: str = Field(min_length=1)  # MIME 타입 (예: "audio/webm", "audio/wav")
    file_name: str | None = None  # 원본 파일명 (디버깅/로깅용)
    language: str = Field(default="ko-KR", min_length=2)  # BCP-47 언어 코드


class TranscriptionResponse(BaseModel):
    """음성 변환 엔드포인트에서 반환하는 응답 본문.

    변환된 텍스트와 인식된 언어 정보를 포함합니다.
    """

    text: str  # 음성에서 변환된 텍스트
    language: str  # 인식된 언어 코드


# ── 헬스 체크 모델 ──────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """``/health`` 엔드포인트의 응답 본문.

    서비스 상태, 애플리케이션 이름, 실행 환경을 반환합니다.
    """

    status: Literal["ok"] = "ok"  # 서비스 상태 ("ok" 고정)
    app_name: str  # 애플리케이션 이름 (Settings.app_name에서 제공)
    environment: str  # 실행 환경 (production/development)


class HealthStatusResponse(BaseModel):
    """시스템 상태 프로브 응답 — 백엔드 및 데이터베이스 연결 상태."""

    backend: bool
    db: bool


# ── 인증 모델 ───────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    """사용자 등록 엔드포인트의 요청 본문.

    새 사용자 계정 생성에 필요한 정보를 정의합니다.
    """

    username: str = Field(min_length=2, max_length=128)  # 로그인 사용자명 (2~128자)
    email: str = Field(min_length=5, max_length=256)  # 이메일 주소 (5~256자)
    password: str = Field(min_length=6, max_length=128)  # 비밀번호 (6~128자)
    client_ip: str | None = None  # 클라이언트 IP (감사 로그용, 선택사항)


class LoginRequest(BaseModel):
    """사용자 로그인 엔드포인트의 요청 본문.

    이메일과 비밀번호를 통한 인증 요청을 정의합니다.
    """

    email: str = Field(min_length=5, max_length=256)  # 로그인 이메일 주소
    password: str = Field(min_length=1, max_length=128)  # 로그인 비밀번호
    client_ip: str | None = None  # 클라이언트 IP (감사 로그용, 선택사항)


class AuthResponse(BaseModel):
    """인증 성공 후 반환되는 표준 응답.

    성공 메시지와 사용자 정보를 포함합니다.
    """

    message: str  # 응답 메시지 (예: "Login successful")
    user: dict  # 사용자 정보 딕셔너리 (id, username, email, role 등)


class TokenAuthResponse(AuthResponse):
    """JWT 액세스 토큰을 포함하는 인증 응답.

    AuthResponse를 상속하며 추가로 JWT 토큰을 제공합니다.
    """

    token: str  # HS256으로 서명된 JWT 액세스 토큰


# ── 관리자 API 모델 ────────────────────────────────────────────────────────

class AdminUserResponse(BaseModel):
    """관리자 API에서 반환하는 사용자 레코드.

    관리자 페이지에서 사용자 목록 및 상세 정보를 표시하는 데 사용됩니다.
    """

    id: str  # 사용자 UUID
    username: str  # 로그인 사용자명
    email: str | None  # 이메일 주소 (미등록 시 null)
    role: str  # 사용자 역할 ("user" 또는 "admin")
    is_active: int  # 활성화 상태 (0=비활성, 1=활성)
    created_at: str  # 계정 생성 시각 (ISO 형식)


class AdminUpdateUserRequest(BaseModel):
    """관리자가 사용자에 대해 업데이트할 수 있는 필드.

    부분 업데이트를 지원하며, 전달된 필드만 변경됩니다.
    """

    email: str | None = None  # 변경할 이메일 주소
    password: str | None = None  # 변경할 비밀번호 (해싱되어 저장됨)
    role: str | None = None  # 변경할 역할: "user" 또는 "admin"
    is_active: int | None = None  # 변경할 활성 상태: 0 = 비활성, 1 = 활성


# ── 대화 관리 모델 ──────────────────────────────────────────────────────────

class ConversationSummary(BaseModel):
    """대화 요약 정보.

    대화 목록 페이지에서 각 대화의 개요를 표시하는 데 사용됩니다.
    """

    id: str  # 대화 UUID
    title: str | None  # 대화 제목 (자동 생성 또는 사용자 지정)
    azure_conversation_id: str | None = None  # Azure AI Foundry 대화 ID
    created_at: str  # 생성 시각 (ISO 형식)
    message_count: int  # 대화에 포함된 메시지 수


class MessageDetail(BaseModel):
    """대화 내 개별 메시지.

    대화 상세 조회 시 각 메시지의 정보를 표시합니다.
    """

    id: str  # 메시지 UUID
    role: str  # 발신자 역할 ("user", "assistant", "system")
    content: str  # 메시지 본문
    created_at: str  # 생성 시각 (ISO 형식)


class ConversationDetail(BaseModel):
    """대화 상세 정보 (메시지 포함).

    특정 대화의 전체 메시지 이력을 포함한 상세 정보를 제공합니다.
    """

    id: str  # 대화 UUID
    title: str | None  # 대화 제목
    azure_conversation_id: str | None = None  # Azure AI Foundry 대화 ID
    created_at: str  # 생성 시각 (ISO 형식)
    messages: list[MessageDetail]  # 시간순으로 정렬된 메시지 목록


class PaginatedConversations(BaseModel):
    """페이지네이션된 대화 목록 응답.

    대화 목록을 페이지 단위로 분할하여 반환합니다.
    """

    items: list[ConversationSummary]  # 현재 페이지의 대화 목록
    total: int  # 전체 대화 수
    page: int  # 현재 페이지 번호
    page_size: int  # 페이지당 항목 수


class SaveConversationRequest(BaseModel):
    """대화 저장 요청.

    프론트엔드에서 채팅 완료 후 대화를 데이터베이스에 저장하는 요청입니다.
    """

    title: str | None = None  # 대화 제목 (선택사항)
    conversation_id: str | None = None  # Azure AI 대화 ID (기존 대화 연결용)
    messages: list[dict]  # [{role: "user"|"assistant", content: "..."}] 형식의 메시지 목록


# ── MCP 검증 모델 ──────────────────────────────────────────────────────────

class McpConnectRequest(BaseModel):
    """MCP 서버에 연결하고 도구 목록을 조회하는 요청.

    MCP 검증 페이지에서 MCP 서버의 Streamable HTTP 엔드포인트에
    연결하여 사용 가능한 도구를 확인하는 데 사용됩니다.
    """

    server_url: AnyHttpUrl  # MCP 서버의 Streamable HTTP URL
    auth_type: Literal["none", "api_key"] = "none"  # 인증 방식: 없음 또는 API 키
    auth_header: str = Field(default="x-api-key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9-]+$")  # 인증 헤더 이름
    auth_value: str = Field(default="", max_length=4096)  # 인증 헤더 값 (API 키)


class McpExecuteRequest(BaseModel):
    """MCP 도구를 실행하는 요청.

    MCP 검증 페이지에서 선택한 도구를 실제로 실행하여
    응답 결과를 검증하는 데 사용됩니다.
    """

    server_url: AnyHttpUrl  # MCP 서버의 Streamable HTTP URL
    auth_type: Literal["none", "api_key"] = "none"  # 인증 방식
    auth_header: str = Field(default="x-api-key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9-]+$")  # 인증 헤더 이름
    auth_value: str = Field(default="", max_length=4096)  # 인증 헤더 값
    tool_name: str = Field(min_length=1, max_length=256)  # 실행할 MCP 도구 이름
    arguments: dict[str, Any] = Field(default_factory=dict)  # 도구에 전달할 인자

"""chatdb 데이터베이스를 위한 SQLAlchemy ORM 모델.

Tables:
    users           — 등록된 채팅 사용자
    conversations   — 채팅 세션 (스레드당 하나)
    messages        — 대화 내 개별 채팅 메시지
    sources         — 어시스턴트 응답에 첨부된 웹/arXiv 소스
    audit_logs      — 관리 / 보안 감사 추적
"""

# 표준 라이브러리 임포트
import uuid  # UUID v4 기본 키 생성을 위한 모듈
from datetime import datetime, timezone  # UTC 타임스탬프 처리

# SQLAlchemy 임포트: 컬럼 타입 및 관계 정의
from sqlalchemy import (
    Column,  # 테이블 컬럼 정의
    DateTime,  # 날짜/시간 타입
    Enum,  # 열거형 타입 (제한된 값 집합)
    Float,  # 부동소수점 타입
    ForeignKey,  # 외래 키 참조
    Index,  # 복합 인덱스 정의
    Integer,  # 정수 타입
    String,  # 가변 길이 문자열 타입
    Text,  # 긴 텍스트 타입
)
from sqlalchemy.orm import DeclarativeBase, relationship  # ORM 기본 클래스 및 관계 매핑


def _utcnow() -> datetime:
    """시간대를 인식하는 UTC 타임스탬프를 반환합니다.

    Returns:
        UTC 시간대를 인식하는 ``datetime``으로서의 현재 날짜 및 시간.
    """
    return datetime.now(timezone.utc)


def _uuid() -> str:
    """새로운 UUID4 문자열을 생성합니다.

    Returns:
        36자 소문자 문자열로 된 랜덤 UUID v4.
    """
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """모든 ORM 모델의 선언적 기본 클래스."""
    pass


# ── 사용자 ─────────────────────────────────────────────────────────────────────

class User(Base):
    """채팅 애플리케이션의 등록된 사용자.

    사용자 계정 정보, 인증 자격 증명, 역할 기반 접근 제어를 관리합니다.
    최초 등록 사용자는 자동으로 관리자(admin) 역할이 부여됩니다.
    """

    __tablename__ = "users"  # MySQL 테이블 이름

    # 사용자 고유 식별자 (UUID v4, 36자 문자열)
    id = Column(String(36), primary_key=True, default=_uuid, comment="UUID primary key")
    # 로그인에 사용되는 사용자 이름 (고유, 필수, 인덱스)
    username = Column(String(128), unique=True, nullable=False, index=True, comment="Login handle")
    # 채팅 화면에 표시되는 이름 (선택사항)
    display_name = Column(String(256), nullable=True, comment="Display name shown in chat")
    # 이메일 주소 (선택사항, 인덱스)
    email = Column(String(256), nullable=True, index=True, comment="Email address")
    # bcrypt로 해싱된 비밀번호 (선택사항; 소셜 로그인 사용자는 null)
    password_hash = Column(String(512), nullable=True, comment="Bcrypt hash of password")
    # 사용자 역할: "user" (일반) 또는 "admin" (관리자)
    role = Column(
        Enum("user", "admin", name="user_role"),
        nullable=False,
        server_default="user",
        comment="Access role",
    )
    # 계정 활성화 상태: 1=활성, 0=비활성 (관리자 승인 필요)
    is_active = Column(Integer, nullable=False, server_default="0", comment="1=active, 0=disabled")
    # 레코드 생성 시각 (UTC)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, comment="Row creation time (UTC)")
    # 마지막 수정 시각 (UTC, 업데이트 시 자동 갱신)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow, comment="Last update time (UTC)"
    )

    # 사용자가 소유한 대화 목록 (1:N 관계, 사용자 삭제 시 대화도 삭제)
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        """User의 개발자 친화적 문자열 표현을 반환합니다.

        Returns:
            ``<User id='...' username='...'>>`` 형태의 문자열.
        """
        return f"<User id={self.id!r} username={self.username!r}>"


# ── 대화 ─────────────────────────────────────────────────────────────────────

class Conversation(Base):
    """채팅 대화 (세션/스레드).

    사용자별 채팅 세션을 관리하며, Azure AI Foundry의 대화 ID와 매핑됩니다.
    상태(active/archived/deleted)로 생명주기를 관리합니다.
    """

    __tablename__ = "conversations"  # MySQL 테이블 이름

    # 대화 고유 식별자 (UUID v4)
    id = Column(String(36), primary_key=True, default=_uuid, comment="UUID primary key")
    # 대화 소유자의 사용자 ID (외래 키, 사용자 삭제 시 대화도 삭제)
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, comment="Owner user"
    )
    # 대화 제목 (자동 생성 또는 사용자 지정)
    title = Column(String(512), nullable=True, comment="Auto-generated or user-set title")
    # Azure AI Foundry 대화 ID (외부 시스템과의 매핑용, 고유)
    azure_conversation_id = Column(
        String(256), nullable=True, unique=True, comment="Azure AI Foundry conversation ID"
    )
    # 대화 상태: "active" (진행중), "archived" (보관), "deleted" (삭제)
    status = Column(
        Enum("active", "archived", "deleted", name="conv_status"),
        nullable=False,
        server_default="active",
        comment="Conversation lifecycle status",
    )
    # 레코드 생성 시각 (UTC)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    # 마지막 수정 시각 (UTC, 업데이트 시 자동 갱신)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # 대화 소유자 참조 (N:1 관계)
    user = relationship("User", back_populates="conversations")
    # 대화에 속한 메시지 목록 (1:N 관계, 대화 삭제 시 메시지도 삭제)
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

    # 복합 인덱스: 사용자 ID + 상태 (사용자별 활성 대화 조회 최적화)
    __table_args__ = (Index("ix_conversations_user_status", "user_id", "status"),)

    def __repr__(self) -> str:
        """Conversation의 개발자 친화적 문자열 표현을 반환합니다.

        Returns:
            ``<Conversation id='...' user='...'>>`` 형태의 문자열.
        """
        return f"<Conversation id={self.id!r} user={self.user_id!r}>"


# ── 메시지 ──────────────────────────────────────────────────────────────────

class Message(Base):
    """대화 내 단일 채팅 메시지 (사용자 또는 어시스턴트).

    사용자 프롬프트와 AI 어시스턴트 응답을 저장하며,
    토큰 사용량 및 응답 시간 등 성능 메트릭도 기록합니다.
    """

    __tablename__ = "messages"  # MySQL 테이블 이름

    # 메시지 고유 식별자 (UUID v4)
    id = Column(String(36), primary_key=True, default=_uuid, comment="UUID primary key")
    # 메시지가 속한 대화 ID (외래 키, 대화 삭제 시 메시지도 삭제)
    conversation_id = Column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 메시지 발신자 역할: "user" (사용자), "assistant" (AI), "system" (시스템)
    role = Column(
        Enum("user", "assistant", "system", name="msg_role"),
        nullable=False,
        comment="Who sent the message",
    )
    # 메시지 본문 (마크다운 형식)
    content = Column(Text, nullable=False, comment="Message body (markdown)")
    # 입력 토큰 수 (AI 응답의 경우, 비용 추적용)
    token_input = Column(Integer, nullable=True, comment="Input tokens consumed")
    # 출력 토큰 수 (AI 응답의 경우, 비용 추적용)
    token_output = Column(Integer, nullable=True, comment="Output tokens generated")
    # 서버 측 응답 시간 (밀리초, 성능 모니터링용)
    response_time_ms = Column(Float, nullable=True, comment="Server-side response time in ms")
    # 응답 생성에 사용된 모델 이름 (예: "gpt-4o")
    model_name = Column(String(128), nullable=True, comment="Model used for this response")
    # 메시지 생성 시각 (UTC)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    # 메시지가 속한 대화 참조 (N:1 관계)
    conversation = relationship("Conversation", back_populates="messages")
    # 메시지에 첨부된 소스/참조 목록 (1:N 관계, 메시지 삭제 시 소스도 삭제)
    sources = relationship("Source", back_populates="message", cascade="all, delete-orphan")

    # 복합 인덱스: 대화 ID + 생성 시각 (시간순 메시지 조회 최적화)
    __table_args__ = (Index("ix_messages_conv_created", "conversation_id", "created_at"),)

    def __repr__(self) -> str:
        """Message의 개발자 친화적 문자열 표현을 반환합니다.

        Returns:
            ``<Message id='...' role='...'>>`` 형태의 문자열.
        """
        return f"<Message id={self.id!r} role={self.role!r}>"


# ── 소스 ───────────────────────────────────────────────────────────────────

class Source(Base):
    """어시스턴트 응답에서 인용된 참조 소스 (URL, 문서).

    AI 어시스턴트가 응답 생성 시 참조한 웹 페이지, 논문, 파일 등의
    출처 정보를 저장하여 응답의 근거를 추적합니다.
    """

    __tablename__ = "sources"  # MySQL 테이블 이름

    # 소스 고유 식별자 (UUID v4)
    id = Column(String(36), primary_key=True, default=_uuid, comment="UUID primary key")
    # 소스가 첨부된 메시지 ID (외래 키, 메시지 삭제 시 소스도 삭제)
    message_id = Column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 소스 제목 (웹 페이지 제목 등)
    title = Column(String(512), nullable=True, comment="Source title")
    # 소스 URL (웹 페이지, 논문 링크 등)
    url = Column(String(2048), nullable=True, comment="Source URL")
    # 소스에서 발췌한 관련 텍스트
    snippet = Column(Text, nullable=True, comment="Relevant excerpt from the source")
    # 소스 유형: "web" (웹), "arxiv" (논문), "file" (파일), "other" (기타)
    source_type = Column(
        Enum("web", "arxiv", "file", "other", name="source_type"),
        nullable=False,
        server_default="web",
        comment="Category of source",
    )
    # 소스 생성 시각 (UTC)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    # 소스가 속한 메시지 참조 (N:1 관계)
    message = relationship("Message", back_populates="sources")

    def __repr__(self) -> str:
        """Source의 개발자 친화적 문자열 표현을 반환합니다.

        Returns:
            ``<Source id='...' type='...'>>`` 형태의 문자열.
        """
        return f"<Source id={self.id!r} type={self.source_type!r}>"


# ── 감사 로그 ────────────────────────────────────────────────────────────────

class AuditLog(Base):
    """관리 및 보안 감사 추적.

    사용자 로그인, 계정 생성/삭제, 대화 삭제 등 중요한 보안 이벤트를
    기록하여 관리자가 시스템 활동을 모니터링할 수 있도록 합니다.
    """

    __tablename__ = "audit_logs"  # MySQL 테이블 이름

    # 감사 로그 자동 증가 기본 키
    id = Column(Integer, primary_key=True, autoincrement=True)
    # 감사 대상 사용자 ID (사용자 삭제 시 NULL로 유지)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # 수행된 작업 (예: "login", "delete_conversation", "create_user")
    action = Column(String(128), nullable=False, comment="Action performed (e.g., login, delete_conversation)")
    # 작업 상세 정보 (JSON 형식의 추가 데이터)
    detail = Column(Text, nullable=True, comment="JSON detail blob")
    # 클라이언트 IP 주소 (IPv4 또는 IPv6)
    ip_address = Column(String(45), nullable=True, comment="Client IP (v4 or v6)")
    # 감사 이벤트 발생 시각 (UTC, 인덱스)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)

    def __repr__(self) -> str:
        """AuditLog의 개발자 친화적 문자열 표현을 반환합니다.

        Returns:
            ``<AuditLog id=1 action='login'>>`` 형태의 문자열.
        """
        return f"<AuditLog id={self.id} action={self.action!r}>"

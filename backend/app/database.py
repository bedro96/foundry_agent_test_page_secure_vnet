"""MySQL(Azure Database for MySQL)을 위한 SQLAlchemy 엔진 및 세션 팩토리.

Usage:
    from app.database import get_engine, SessionLocal

    engine = get_engine()           # 싱글톤 엔진
    with SessionLocal() as session: # 범위 지정 세션
        session.execute(...)
"""

# 표준 라이브러리 임포트
import logging
import ssl as _ssl  # SSL/TLS 컨텍스트 생성을 위한 모듈

# SQLAlchemy 임포트: ORM 엔진, 이벤트 리스너, SQL 텍스트 실행
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine  # 엔진 타입 힌트
from sqlalchemy.orm import Session, sessionmaker  # 세션 팩토리

# 애플리케이션 설정 로더
from app.config import get_settings

# 이 모듈의 로거 인스턴스 (데이터베이스 연결 상태 추적용)
logger = logging.getLogger(__name__)

# 프로세스 전역 싱글톤 엔진 인스턴스 (최초 호출 시 지연 생성됨)
_engine: Engine | None = None


def _build_database_url() -> str:
    """설정에서 PyMySQL 연결 URL을 구성합니다.

    Returns:
        SQLAlchemy 호환 ``mysql+pymysql://`` 연결 문자열.

    Raises:
        RuntimeError: 필수 MySQL 설정 (host, database, user)이
            환경에 없는 경우.
    """

    # 애플리케이션 설정에서 MySQL 관련 값 로드
    s = get_settings()
    # 필수 MySQL 설정 (호스트, 데이터베이스, 사용자)이 모두 있는지 검증
    if not all([s.mysql_host, s.mysql_db, s.mysql_user]):
        raise RuntimeError(
            "MySQL settings incomplete — set MYSQL_HOST, MYSQL_DB, and MYSQL_USER in .env"
        )

    # 연결 URL 구성 정보 로깅 (비밀번호 제외)
    logger.info(
        "Building database URL: host=%s, db=%s, user=%s, port=%s",
        s.mysql_host, s.mysql_db, s.mysql_user, s.mysql_port,
    )
    # 비밀번호가 미설정이면 빈 문자열 사용
    password = s.mysql_password or ""
    # PyMySQL 드라이버를 사용하는 SQLAlchemy 연결 문자열 구성
    return (
        f"mysql+pymysql://{s.mysql_user}:{password}"
        f"@{s.mysql_host}:{s.mysql_port}/{s.mysql_db}"
        f"?charset={s.mysql_charset}"
    )


def _create_ssl_context(ssl_mode: str) -> _ssl.SSLContext | None:
    """ssl_mode가 암호화를 요구할 때 SSL 컨텍스트를 반환합니다.

    Args:
        ssl_mode: ``"required"``, ``"preferred"``, ``"disabled"`` 또는
            ``"none"`` 중 하나.

    Returns:
        TLS 연결을 위한 구성된 ``ssl.SSLContext``, SSL이 비활성화된 경우
        ``None``.
    """

    # SSL 비활성화 모드인 경우 컨텍스트 없이 반환
    if ssl_mode.lower() in ("disabled", "none", ""):
        return None

    # 기본 SSL 컨텍스트 생성 (시스템 CA 인증서 사용)
    ctx = _ssl.create_default_context()
    if ssl_mode.lower() in ("preferred", "required"):
        # Azure MySQL은 잘 알려진 CA를 사용; 호스트명 검증 및 인증서 필수 설정
        ctx.check_hostname = True
        ctx.verify_mode = _ssl.CERT_REQUIRED
    return ctx


def get_engine() -> Engine:
    """프로세스 전역 SQLAlchemy 엔진을 반환합니다 (지연 싱글톤).

    Returns:
        구성된 MySQL 데이터베이스에 연결된 공유 ``Engine`` 인스턴스.
    """

    global _engine  # noqa: PLW0603 — 모듈 수준 싱글톤 엔진 참조
    # 이미 엔진이 생성되어 있으면 기존 인스턴스 반환 (싱글톤 패턴)
    if _engine is not None:
        return _engine

    # 설정 로드 및 연결 URL / SSL 컨텍스트 구성
    s = get_settings()
    url = _build_database_url()  # MySQL 연결 URL 생성
    ssl_ctx = _create_ssl_context(s.mysql_ssl_mode)  # SSL 컨텍스트 생성

    # PyMySQL 연결 매개변수 딕셔너리 구성
    connect_args: dict = {}
    if ssl_ctx is not None:
        connect_args["ssl"] = ssl_ctx  # SSL 컨텍스트를 연결 인자에 추가
        logger.info("MySQL SSL enabled: ssl_mode=%s", s.mysql_ssl_mode)
    connect_args["connect_timeout"] = s.mysql_connect_timeout  # 연결 타임아웃 설정

    # 엔진 생성 전 구성 정보 로깅
    logger.info(
        "Creating MySQL engine: host=%s, db=%s, pool_size=%d, ssl=%s",
        s.mysql_host,
        s.mysql_db,
        s.mysql_pool_size,
        ssl_ctx is not None,
    )
    # SQLAlchemy 엔진 생성: 커넥션 풀, 사전 핑, 자동 재활용 등 설정
    _engine = create_engine(
        url,
        pool_size=s.mysql_pool_size,  # 최대 영구 연결 수
        max_overflow=2,  # 풀 크기 초과 시 추가 허용 연결 수
        pool_pre_ping=True,  # 연결 사용 전 유효성 검사 (끊어진 연결 방지)
        pool_recycle=1800,  # 30분마다 연결 재활용 (MySQL wait_timeout 대응)
        echo=False,  # SQL 쿼리 로깅 비활성화 (프로덕션 성능 최적화)
        connect_args=connect_args,
    )

    # 이벤트 리스너: 새로운 물리적 연결이 생성될 때 로깅
    @event.listens_for(_engine, "connect")
    def _on_connect(dbapi_conn, connection_record):  # noqa: ARG001
        logger.info("MySQL connection established to %s/%s", s.mysql_host, s.mysql_db)

    # 이벤트 리스너: 풀에서 연결이 체크아웃(사용 시작)될 때 디버그 로깅
    @event.listens_for(_engine, "checkout")
    def _on_checkout(dbapi_conn, connection_record, connection_proxy):  # noqa: ARG001
        logger.debug("MySQL connection checked out from pool")

    # 이벤트 리스너: 풀에 연결이 반환(사용 완료)될 때 디버그 로깅
    @event.listens_for(_engine, "checkin")
    def _on_checkin(dbapi_conn, connection_record):  # noqa: ARG001
        logger.debug("MySQL connection returned to pool")

    logger.info("MySQL engine created successfully")
    return _engine


def SessionLocal() -> Session:  # noqa: N802 — factory named like a class by convention
    """전역 엔진에 바인딩된 새 SQLAlchemy 세션을 생성합니다.

    Returns:
        ``expire_on_commit=False``로 설정된 새 ``Session`` 인스턴스.
    """

    return sessionmaker(bind=get_engine(), expire_on_commit=False)()


def check_connection() -> bool:
    """빠른 헬스 체크: SELECT 1을 실행하고 성공 시 True를 반환합니다.

    Returns:
        데이터베이스가 성공적으로 응답하면 ``True``, 연결 또는
        쿼리 오류 시 ``False``.
    """

    logger.debug("MySQL health-check starting")
    try:
        # 엔진에서 연결을 가져와 간단한 쿼리(SELECT 1) 실행
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        # 쿼리 성공 시 데이터베이스 정상 응답으로 판단
        logger.info("MySQL health-check passed")
        return True
    except Exception as exc:
        # 연결 실패 또는 쿼리 오류 시 False 반환
        logger.error("MySQL health-check failed: %s", exc)
        return False

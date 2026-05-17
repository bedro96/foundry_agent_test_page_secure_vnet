"""인증 서비스: 비밀번호 해싱, JWT 토큰 관리, 사용자 CRUD.

사용자 인증과 계정 관리를 위한 핵심 서비스 모듈입니다.
bcrypt를 통한 안전한 비밀번호 해싱, PyJWT를 통한 JWT 토큰 발급/검증,
SQLAlchemy를 통한 사용자 CRUD 작업을 제공합니다.
"""

# 표준 라이브러리 임포트
import logging
from datetime import datetime, timedelta, timezone  # JWT 만료 시간 계산용

# 서드파티 라이브러리 임포트
import bcrypt  # 비밀번호 해싱 (Blowfish 암호화 알고리즘)
import jwt  # JWT 토큰 생성 및 검증 (PyJWT)
from sqlalchemy.orm import Session  # SQLAlchemy 데이터베이스 세션

# 애플리케이션 모듈 임포트
from app.config import get_settings  # 설정 싱글톤 로더
from app.db_models import User  # 사용자 ORM 모델

# 이 모듈의 로거 인스턴스 (인증 이벤트 추적용)
logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """bcrypt를 사용하여 비밀번호를 해싱합니다.

    Args:
        password: 해싱할 평문 비밀번호.

    Returns:
        bcrypt로 해싱된 비밀번호 문자열.
    """

    # 평문 비밀번호를 UTF-8 바이트로 인코딩하고 솔트를 생성하여 해싱
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """비밀번호를 bcrypt 해시와 대조하여 검증합니다.

    Args:
        password: 확인할 평문 비밀번호.
        password_hash: 비교 대상인 저장된 bcrypt 해시.

    Returns:
        비밀번호가 해시와 일치하면 ``True``, 그렇지 않으면 ``False``.
    """

    # 입력 비밀번호와 저장된 해시를 바이트 단위로 비교
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_jwt_token(user_id: str, email: str, role: str) -> str:
    """사용자 클레임이 포함된 JWT 토큰을 생성합니다.

    Args:
        user_id: 사용자의 고유 식별자 (UUID 문자열).
        email: 클레임에 포함될 이메일 주소.
        role: 사용자 역할 (예: ``"user"`` 또는 ``"admin"``).

    Returns:
        HS256으로 서명된 JWT 토큰 문자열.
    """

    # JWT 비밀키와 만료 시간 등 설정값 로드
    settings = get_settings()
    # 현재 UTC 시각을 기준으로 토큰 생성
    now = datetime.now(timezone.utc)
    # JWT 페이로드 구성: 사용자 정보, 만료 시각, 발급 시각
    payload = {
        "user_id": user_id,  # 사용자 고유 ID
        "email": email,  # 사용자 이메일
        "role": role,  # 사용자 역할 (user/admin)
        "exp": now + timedelta(hours=settings.jwt_expiry_hours),  # 토큰 만료 시각
        "iat": now,  # 토큰 발급 시각
    }
    logger.info("create_jwt_token() issued: user_id=%s, email=%s, role=%s", user_id, email, role)
    # HS256 알고리즘으로 페이로드를 서명하여 JWT 문자열 반환
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_jwt_token(token: str) -> dict | None:
    """JWT 토큰을 디코딩하고 검증합니다.

    Args:
        token: 디코딩할 원시 JWT 문자열.

    Returns:
        성공 시 디코딩된 페이로드 딕셔너리, 토큰이 만료되었거나
        유효하지 않은 경우 ``None``.
    """

    # JWT 검증을 위한 비밀키 로드
    settings = get_settings()
    try:
        # HS256 알고리즘으로 토큰 서명 검증 및 페이로드 디코딩
        decoded = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        logger.info("decode_jwt_token() valid: user_id=%s, email=%s", decoded.get("user_id"), decoded.get("email"))
        return decoded
    except jwt.ExpiredSignatureError:
        # 토큰 만료 시간(exp)이 현재 시각보다 이전인 경우
        logger.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError as error:
        # 서명 불일치, 형식 오류 등 기타 JWT 검증 실패
        logger.warning("Invalid JWT token: %s", error)
        return None


def create_user(db: Session, username: str, email: str, password: str) -> User:
    """데이터베이스에 새 사용자를 생성합니다.

    등록된 첫 번째 사용자는 자동으로 관리자가 됩니다.

    Args:
        db: 활성 SQLAlchemy 세션.
        username: 원하는 로그인 핸들.
        email: 사용자의 이메일 주소.
        password: 평문 비밀번호 (저장 전 해싱됨).

    Returns:
        새로 생성되고 커밋된 ``User`` ORM 인스턴스.
    """

    # 기존 사용자 수 조회 — 최초 등록 사용자 판별용
    existing_count = db.query(User).count()
    # 최초 사용자는 관리자(admin)로 승격, 이후 사용자는 일반(user) 역할
    role = "admin" if existing_count == 0 else "user"

    # 새 User ORM 인스턴스 생성 (비밀번호는 bcrypt 해싱)
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),  # 평문 비밀번호를 해싱하여 저장
        role=role,
        is_active=1 if role == "admin" else 0,  # 관리자는 즉시 활성화, 일반 사용자는 비활성
    )
    # 데이터베이스에 추가하고 커밋
    db.add(user)
    db.commit()
    # 생성된 레코드의 자동 생성 필드 (id, created_at 등) 새로고침
    db.refresh(user)
    logger.info("User created: id=%s username=%s role=%s", user.id, user.username, user.role)
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    """이메일 주소로 사용자를 찾습니다.

    Args:
        db: 활성 SQLAlchemy 세션.
        email: 조회할 이메일 주소.

    Returns:
        일치하는 ``User`` 인스턴스, 찾지 못한 경우 ``None``.
    """

    logger.debug("get_user_by_email() lookup: email=%s", email)
    # 이메일 주소로 사용자 레코드 조회 (일치하는 첫 번째 결과)
    user = db.query(User).filter(User.email == email).first()
    logger.debug("get_user_by_email() result: email=%s, found=%s", email, user is not None)
    return user


def get_user_by_username(db: Session, username: str) -> User | None:
    """사용자 이름으로 사용자를 찾습니다.

    Args:
        db: 활성 SQLAlchemy 세션.
        username: 조회할 사용자 이름.

    Returns:
        일치하는 ``User`` 인스턴스, 찾지 못한 경우 ``None``.
    """

    logger.debug("get_user_by_username() lookup: username=%s", username)
    # 사용자 이름으로 사용자 레코드 조회 (일치하는 첫 번째 결과)
    user = db.query(User).filter(User.username == username).first()
    logger.debug("get_user_by_username() result: username=%s, found=%s", username, user is not None)
    return user


def get_all_users(db: Session) -> list[User]:
    """데이터베이스의 모든 사용자를 반환합니다.

    관리자 페이지의 사용자 목록 조회에 사용됩니다.

    Args:
        db: 활성 SQLAlchemy 세션.

    Returns:
        모든 ``User`` ORM 인스턴스의 목록.
    """
    # 사용자 테이블의 전체 레코드 조회
    users = db.query(User).all()
    logger.info("get_all_users() returned %d users", len(users))
    return users


def get_user_by_id(db: Session, user_id: str) -> User | None:
    """기본 키 ID로 사용자를 찾습니다.

    Args:
        db: 활성 SQLAlchemy 세션.
        user_id: 사용자의 UUID 문자열.

    Returns:
        일치하는 ``User`` 인스턴스, 찾지 못한 경우 ``None``.
    """
    logger.debug("get_user_by_id() lookup: user_id=%s", user_id)
    # UUID 기본 키로 사용자 레코드 조회
    user = db.query(User).filter(User.id == user_id).first()
    logger.debug("get_user_by_id() result: user_id=%s, found=%s", user_id, user is not None)
    return user


def update_user(db: Session, user: User, **kwargs: str | int) -> User:
    """User 행의 변경 가능한 필드를 업데이트합니다.

    Args:
        db: 활성 SQLAlchemy 세션.
        user: 수정할 ``User`` ORM 인스턴스.
        **kwargs: 필드명 / 값 쌍. ``"password"`` 키는
            저장 전 자동으로 재해싱됩니다.

    Returns:
        업데이트되고 새로고침된 ``User`` 인스턴스.
    """
    logger.info("update_user() updating: user_id=%s, fields=%s", user.id, list(kwargs.keys()))
    # 전달된 키-값 쌍을 순회하며 필드 업데이트
    for key, value in kwargs.items():
        if key == "password" and isinstance(value, str):
            # "password" 키는 특별 처리: 평문을 bcrypt 해싱 후 password_hash에 저장
            user.password_hash = hash_password(value)
        elif hasattr(user, key):
            # 그 외 유효한 필드는 직접 설정
            setattr(user, key, value)
    # 변경 사항을 데이터베이스에 커밋
    db.commit()
    # 업데이트된 필드 값 새로고침
    db.refresh(user)
    logger.info("update_user() completed: user_id=%s, username=%s", user.id, user.username)
    return user


def delete_user(db: Session, user: User) -> None:
    """사용자를 영구적으로 삭제합니다.

    Args:
        db: 활성 SQLAlchemy 세션.
        user: 삭제할 ``User`` ORM 인스턴스.
    """
    logger.info("delete_user() deleting: user_id=%s, username=%s", user.id, user.username)
    # 데이터베이스에서 사용자 레코드 삭제 (CASCADE로 관련 대화도 삭제됨)
    db.delete(user)
    # 삭제를 데이터베이스에 커밋
    db.commit()
    logger.info("delete_user() completed: user_id=%s", user.id)

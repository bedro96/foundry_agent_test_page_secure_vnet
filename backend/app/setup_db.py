#!/usr/bin/env python3
"""데이터베이스 설정 스크립트 — db_models.py에 정의된 모든 테이블을 생성합니다.

이 스크립트는 MySQL 데이터베이스에 ORM 모델 기반의 테이블을 생성하고,
테이블 존재 여부를 검증하며, 각 테이블의 행 수를 출력하는 기능을 제공합니다.
--drop 옵션으로 기존 테이블을 삭제 후 재생성할 수 있으며,
--verify 옵션으로 테이블 상태만 확인할 수도 있습니다.

Usage:
    # 테이블 생성 (안전 — 이미 존재하면 건너뜀):
    uv run python -m app.setup_db

    # 모든 테이블 삭제 후 재생성 (파괴적):
    uv run python -m app.setup_db --drop

    # 생성 후 테이블 검증:
    uv run python -m app.setup_db --verify
"""

# ──────────────────────────────────────────────
# 표준 라이브러리 및 서드파티 패키지 임포트
# ──────────────────────────────────────────────
import argparse  # CLI 인자 파싱을 위한 표준 라이브러리
import logging  # 로깅 기능을 위한 표준 라이브러리
import sys  # 프로세스 종료 코드 제어를 위한 표준 라이브러리

from sqlalchemy import inspect, text  # SQLAlchemy 데이터베이스 검사 및 원시 SQL 실행 도구

from app.database import check_connection, get_engine  # 데이터베이스 연결 확인 및 엔진 팩토리
from app.db_models import Base  # 모든 ORM 모델의 베이스 클래스 (메타데이터 포함)

# ──────────────────────────────────────────────
# 로깅 설정 — 콘솔에 타임스탬프, 로그 레벨, 로거 이름을 포함한 메시지를 출력합니다
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,  # INFO 이상 레벨의 로그만 출력
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",  # 로그 출력 형식 지정
)
logger = logging.getLogger("setup_db")  # 이 모듈 전용 로거 인스턴스 생성

# 의존성 순서의 테이블 목록 (삭제 시 자식 테이블 우선)
# - users: 사용자 계정 정보 테이블
# - conversations: 대화 세션 테이블 (users 참조)
# - messages: 개별 메시지 테이블 (conversations 참조)
# - sources: 메시지 출처/참조 자료 테이블
# - audit_logs: 시스템 감사 로그 테이블
EXPECTED_TABLES = ["users", "conversations", "messages", "sources", "audit_logs"]


def create_tables(drop_first: bool = False) -> None:
    """데이터베이스에 모든 ORM 정의 테이블을 생성합니다.

    Base.metadata에 등록된 모든 모델(테이블)을 MySQL에 반영합니다.
    create_all()은 이미 존재하는 테이블은 건너뛰므로 안전하게 반복 실행 가능합니다.
    drop_first=True 시에는 모든 테이블을 삭제 후 재생성합니다(데이터 손실 주의).

    Args:
        drop_first: True인 경우 재생성 전에 기존 테이블을 삭제합니다.

    Returns:
        None — 테이블 생성 결과는 로그로 출력됩니다.
    """

    # 데이터베이스 엔진 인스턴스를 가져옵니다
    engine = get_engine()

    # 기존 테이블 삭제 단계 — drop_first 플래그가 설정된 경우에만 실행
    if drop_first:
        logger.warning("Dropping all tables — this is DESTRUCTIVE!")
        # 모든 ORM 모델에 해당하는 테이블을 데이터베이스에서 삭제합니다
        Base.metadata.drop_all(engine)
        logger.info("All tables dropped.")

    # 테이블 생성 단계 — 이미 존재하는 테이블은 자동으로 건너뜁니다
    logger.info("Creating tables...")
    Base.metadata.create_all(engine)
    logger.info("Tables created successfully.")


def verify_tables() -> bool:
    """모든 예상 테이블이 존재하는지 확인하고 컬럼 정보를 출력합니다.

    EXPECTED_TABLES 목록에 정의된 각 테이블이 데이터베이스에 존재하는지 검사합니다.
    존재하는 테이블은 컬럼 목록을 함께 출력하고, 누락된 테이블은 에러로 보고합니다.
    또한 예상 목록에 없는 추가 테이블이 있으면 알려줍니다.

    Returns:
        ``EXPECTED_TABLES``의 모든 테이블이 존재하면 ``True``,
        하나라도 누락되면 ``False``를 반환합니다.
    """

    # 데이터베이스 엔진 인스턴스를 가져옵니다
    engine = get_engine()
    # SQLAlchemy Inspector를 사용하여 데이터베이스 메타데이터를 조회합니다
    inspector = inspect(engine)
    # 현재 데이터베이스에 존재하는 모든 테이블 이름을 집합으로 가져옵니다
    existing = set(inspector.get_table_names())

    # 검증 결과 플래그 — 누락 테이블이 있으면 False로 변경됩니다
    all_ok = True
    # 각 예상 테이블에 대해 존재 여부를 순회하며 확인합니다
    for table_name in EXPECTED_TABLES:
        if table_name in existing:
            # 테이블이 존재하면 컬럼 정보를 조회합니다
            columns = inspector.get_columns(table_name)
            # 컬럼 이름만 추출하여 로그에 출력합니다
            col_names = [c["name"] for c in columns]
            logger.info("✓ %-20s columns: %s", table_name, ", ".join(col_names))
        else:
            # 테이블이 누락된 경우 에러 로그를 출력합니다
            logger.error("✗ %-20s MISSING", table_name)
            all_ok = False

    # 예상 목록(EXPECTED_TABLES)에 없는 추가 테이블이 있는지 확인합니다
    extras = existing - set(EXPECTED_TABLES)
    if extras:
        # 추가 테이블이 발견되면 정보 로그로 보고합니다
        logger.info("Extra tables in database: %s", ", ".join(sorted(extras)))

    return all_ok


def print_row_counts() -> None:
    """각 테이블의 행 수를 출력합니다 — 빠른 상태 확인에 유용합니다.

    EXPECTED_TABLES에 정의된 모든 테이블에 대해 SELECT COUNT(*) 쿼리를 실행하여
    현재 저장된 데이터 행 수를 로그로 출력합니다. 접근 불가능한 테이블은
    에러 없이 안내 메시지를 출력합니다.

    Returns:
        None — 행 수 결과는 로그로 출력됩니다.
    """

    # 데이터베이스 엔진 인스턴스를 가져옵니다
    engine = get_engine()
    # 데이터베이스 연결을 열고 컨텍스트 매니저로 자동 정리합니다
    with engine.connect() as conn:
        # 각 예상 테이블에 대해 행 수를 조회합니다
        for table_name in EXPECTED_TABLES:
            try:
                # 원시 SQL로 테이블의 전체 행 수를 조회합니다
                result = conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`"))  # noqa: S608
                # scalar()로 단일 값(행 수)을 추출합니다
                count = result.scalar()
                logger.info("  %-20s %d rows", table_name, count)
            except Exception:
                # 테이블 접근 실패 시 (존재하지 않거나 권한 부족 등) 안내 메시지 출력
                logger.info("  %-20s (not accessible)", table_name)


def main() -> None:
    """CLI 진입점 — 데이터베이스 테이블 설정 및 검증을 수행합니다.

    명령줄 인자를 파싱하여 다음 작업 중 하나를 실행합니다:
    1. --verify: 기존 테이블 상태만 확인하고 행 수를 출력한 후 종료
    2. --drop: 모든 테이블을 삭제 후 재생성 (데이터 손실 주의)
    3. 기본: 누락된 테이블만 새로 생성 (기존 테이블은 유지)

    모든 경우에 MySQL 연결 확인을 먼저 수행하며, 연결 실패 시 종료 코드 1로 종료합니다.

    Returns:
        None — 프로세스 종료 코드로 결과를 반환합니다 (0: 성공, 1: 실패).
    """

    # CLI 인자 파서를 생성합니다 — chatdb용 MySQL 테이블 설정 도구
    parser = argparse.ArgumentParser(description="Set up MySQL database tables for chatdb")
    # --drop 옵션: 모든 테이블을 삭제 후 재생성하는 파괴적 작업 플래그
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop all tables before recreating (DESTRUCTIVE)",
    )
    # --verify 옵션: 테이블 생성 없이 기존 상태만 확인하는 플래그
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Only verify existing tables without creating",
    )
    # 명령줄 인자를 파싱하여 args 객체에 저장합니다
    args = parser.parse_args()

    # ── 1단계: MySQL 연결 상태 확인 ──
    logger.info("Checking MySQL connectivity...")
    if not check_connection():
        # 연결 실패 시 에러 로그를 출력하고 종료 코드 1로 프로세스를 종료합니다
        logger.error("Cannot connect to MySQL. Check .env settings and network.")
        sys.exit(1)
    logger.info("MySQL connection OK.")

    # ── 2단계: --verify 모드 처리 — 테이블 검증만 수행 후 종료 ──
    if args.verify:
        # 테이블 존재 여부를 확인합니다
        ok = verify_tables()
        # 각 테이블의 행 수를 출력합니다
        print_row_counts()
        # 검증 결과에 따라 종료 코드를 반환합니다 (성공: 0, 실패: 1)
        sys.exit(0 if ok else 1)

    # ── 3단계: 테이블 생성 (또는 --drop 시 삭제 후 재생성) ──
    create_tables(drop_first=args.drop)

    # ── 4단계: 생성 후 테이블 검증 및 행 수 확인 ──
    ok = verify_tables()
    print_row_counts()

    # ── 5단계: 최종 결과 보고 및 프로세스 종료 ──
    if ok:
        # 모든 테이블이 정상적으로 생성된 경우 성공 메시지를 출력합니다
        logger.info("Database setup complete — all %d tables ready.", len(EXPECTED_TABLES))
    else:
        # 일부 테이블이 누락된 경우 에러를 보고하고 종료 코드 1로 종료합니다
        logger.error("Some tables are missing after creation — check logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()

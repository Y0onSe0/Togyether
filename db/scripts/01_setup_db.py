"""
01_setup_db.py
DB 스키마 생성 (db_setup.sql 실행)

실행:
    python 01_setup_db.py
    python 01_setup_db.py --drop  ← 기존 테이블 삭제 후 재생성
"""

import sys
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from config import DB_SETUP_SQL
from modules.connect_db import connect_db


def drop_all(conn):
    """기존 테이블/타입 전부 삭제 (개발 시 초기화용)"""
    print("[setup] 기존 테이블 삭제 중...")
    cursor = conn.cursor()
    cursor.execute("""
        DROP TABLE IF EXISTS
            keyword_dictionary,
            vaccination_centers,
            health_centers,
            transfer_agencies,
            consultation_documents,
            service_guide_documents,
            consultations,
            sessions,
            employees
        CASCADE;

        DROP TYPE IF EXISTS
            consultation_status,
            employee_status,
            employee_role
        CASCADE;
    """)
    conn.commit()
    cursor.close()
    print("[setup] 삭제 완료")


def run_setup_sql(conn):
    """db_setup.sql 실행"""
    print(f"[setup] SQL 파일 실행: {DB_SETUP_SQL}")

    if not DB_SETUP_SQL.exists():
        print(f"[setup] ❌ SQL 파일 없음: {DB_SETUP_SQL}")
        sys.exit(1)

    with open(DB_SETUP_SQL, "r", encoding="utf-8") as f:
        sql = f.read()

    cursor = conn.cursor()
    cursor.execute(sql)
    conn.commit()
    cursor.close()
    print("[setup] ✓ 스키마 생성 완료")


def verify_tables(conn):
    """생성된 테이블 목록 확인"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename;
    """)
    tables = [row[0] for row in cursor.fetchall()]
    cursor.close()

    print(f"\n[setup] 생성된 테이블 ({len(tables)}개):")
    for t in tables:
        print(f"  ✓ {t}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop", action="store_true", help="기존 테이블 삭제 후 재생성")
    args = parser.parse_args()

    conn = connect_db()

    if args.drop:
        confirm = input("⚠ 모든 테이블을 삭제합니다. 계속할까요? (yes): ")
        if confirm.strip().lower() != "yes":
            print("취소됨")
            return
        drop_all(conn)

    run_setup_sql(conn)
    verify_tables(conn)
    conn.close()


if __name__ == "__main__":
    main()

"""
modules/connect_db.py
PostgreSQL 연결 관리
"""

import sys
import psycopg2
import psycopg2.extras

sys.path.append(str(__import__('pathlib').Path(__file__).parent.parent))
from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME


def connect_db():
    """DB 연결 반환. 실패 시 에러 출력 후 종료."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname=DB_NAME
        )
        conn.autocommit = False
        print(f"[DB] 연결 성공 → {DB_HOST}:{DB_PORT}/{DB_NAME}")
        return conn
    except psycopg2.OperationalError as e:
        print(f"[DB] 연결 실패: {e}")
        print(f"     HOST={DB_HOST}, PORT={DB_PORT}, DB={DB_NAME}")
        sys.exit(1)

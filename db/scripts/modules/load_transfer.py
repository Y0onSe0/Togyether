"""
modules/load_transfer.py
이관 정보 RDB 적재

transfer_agencies   : 소속기관 9개 (질병관리청 내 부서)
health_centers      : 보건소
vaccination_centers : 예방접종기관 49개
"""

import json
import sys
from pathlib import Path
from psycopg2.extras import execute_batch

sys.path.append(str(Path(__file__).parent.parent))
from config import DATA_DIR, CONSULT_DIR, BATCH_SIZE

# ── 파일 경로 ─────────────────────────────────────────────────────────────
TRANSFER_AGENCY_FILE   = DATA_DIR / "상담" / "요양기관 현황.json"
VACCINATION_CENTER_FILE = DATA_DIR / "상담" / "진료비정보.json"


# ── 1. 소속기관 적재 ──────────────────────────────────────────────────────
INSERT_AGENCY_SQL = """
INSERT INTO transfer_agencies
    (agency_name, division, phone, fax, email, handled_categories, note)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING;
"""

# 질병관리청 소속기관 9개 (하드코딩 — 데이터 파일 없을 때 기본값)
DEFAULT_AGENCIES = [
    ("감염병관리과",       "법정감염병 신고 및 관리",         "043-719-7166", None, None,
     ["감염병신고", "격리조치", "법정감염병"],             None),
    ("신종감염병대응과",   "신종감염병 대응 및 위기관리",     "043-719-9000", None, None,
     ["신종감염병", "생물테러", "위기대응"],               None),
    ("인수공통감염병관리과","인수공통감염병 예방·관리",       "043-719-7200", None, None,
     ["인수공통감염병", "동물감염병"],                     None),
    ("의료감염관리과",     "의료관련감염 예방·관리",          "043-719-7580", None, None,
     ["의료감염", "항생제내성", "CRE", "MRSA"],            None),
    ("결핵정책과",         "결핵 예방 및 관리 정책",          "043-719-7300", None, None,
     ["결핵", "잠복결핵"],                                 None),
    ("에이즈관리과",       "HIV/AIDS 예방 및 관리",           "043-719-7350", None, None,
     ["HIV", "AIDS", "에이즈"],                            None),
    ("예방접종관리과",     "예방접종 정책 및 이상반응 관리",  "043-719-8350", None, None,
     ["예방접종", "백신", "이상반응"],                     None),
    ("역학조사과",         "역학조사 및 감염병 감시",         "043-719-7130", None, None,
     ["역학조사", "집단감염", "감염병감시"],               None),
    ("검역정책과",         "국경검역 및 해외감염병 대응",     "043-719-7510", None, None,
     ["검역", "해외유입감염병", "격리시설"],               None),
]


def load_transfer_agencies(conn):
    """소속기관 9개 적재"""
    print("\n[transfer_agencies] 소속기관 적재 중...")
    cursor = conn.cursor()
    execute_batch(cursor, INSERT_AGENCY_SQL, DEFAULT_AGENCIES)
    conn.commit()
    print(f"  ✓ {len(DEFAULT_AGENCIES)}개 완료")
    cursor.close()


# ── 2. 보건소 적재 ────────────────────────────────────────────────────────
INSERT_HC_SQL = """
INSERT INTO health_centers
    (center_name, region, district, address, phone, fax, operating_hours)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING;
"""


def load_health_centers(conn):
    """
    요양기관 현황.json → health_centers 테이블
    """
    print(f"\n[health_centers] 파일: {TRANSFER_AGENCY_FILE.name}")

    if not TRANSFER_AGENCY_FILE.exists():
        print("  ⚠ 파일 없음, 건너뜀")
        return

    with open(TRANSFER_AGENCY_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # 원본 구조에 맞게 파싱
    rows = []
    items = raw if isinstance(raw, list) else raw.get("items", [])

    for item in items:
        # 필드명 유연하게 처리 (원본 JSON 키명이 다를 수 있음)
        name    = (item.get("기관명") or item.get("center_name") or item.get("name", "")).strip()
        region  = (item.get("시도")   or item.get("region", "")).strip()
        district= (item.get("시군구") or item.get("district", "")).strip()
        address = (item.get("주소")   or item.get("address", "")).strip()
        phone   = (item.get("전화번호") or item.get("phone", "")).strip()
        fax     = (item.get("팩스")   or item.get("fax", "")).strip() or None
        hours   = (item.get("운영시간") or item.get("operating_hours", "")).strip() or None

        if name:
            rows.append((name, region, district, address, phone, fax, hours))

    if not rows:
        print("  ⚠ 파싱된 데이터 없음")
        return

    cursor = conn.cursor()
    for i in range(0, len(rows), BATCH_SIZE):
        execute_batch(cursor, INSERT_HC_SQL, rows[i:i+BATCH_SIZE])
        conn.commit()

    print(f"  ✓ {len(rows)}개 완료")
    cursor.close()


# ── 3. 예방접종기관 적재 ─────────────────────────────────────────────────
INSERT_VC_SQL = """
INSERT INTO vaccination_centers
    (center_name, region, district, address, phone, available_vaccines, operating_hours, is_public)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING;
"""


def load_vaccination_centers(conn):
    """
    진료비정보.json → vaccination_centers 테이블
    """
    print(f"\n[vaccination_centers] 파일: {VACCINATION_CENTER_FILE.name}")

    if not VACCINATION_CENTER_FILE.exists():
        print("  ⚠ 파일 없음, 건너뜀")
        return

    with open(VACCINATION_CENTER_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    rows = []
    items = raw if isinstance(raw, list) else raw.get("items", [])

    for item in items:
        name     = (item.get("기관명") or item.get("center_name") or item.get("name", "")).strip()
        region   = (item.get("시도")   or item.get("region", "")).strip()
        district = (item.get("시군구") or item.get("district", "")).strip()
        address  = (item.get("주소")   or item.get("address", "")).strip()
        phone    = (item.get("전화번호") or item.get("phone", "")).strip()
        vaccines = item.get("취급백신") or item.get("available_vaccines") or []
        hours    = (item.get("운영시간") or item.get("operating_hours", "")).strip() or None
        is_pub   = item.get("공공여부", True)

        if isinstance(vaccines, str):
            vaccines = [v.strip() for v in vaccines.split(",") if v.strip()]

        if name:
            rows.append((name, region, district, address, phone, vaccines, hours, is_pub))

    if not rows:
        print("  ⚠ 파싱된 데이터 없음")
        return

    cursor = conn.cursor()
    for i in range(0, len(rows), BATCH_SIZE):
        execute_batch(cursor, INSERT_VC_SQL, rows[i:i+BATCH_SIZE])
        conn.commit()

    print(f"  ✓ {len(rows)}개 완료")
    cursor.close()

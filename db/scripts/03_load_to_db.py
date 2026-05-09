"""
03_load_to_db.py
전체 데이터 DB 적재 (메인 오케스트레이터)

실행 순서:
    1. service_guide_documents  (disease_info + FAQ + vacc)
    2. consultation_documents
    3. 이관 정보 (transfer_agencies, health_centers, vaccination_centers)

실행:
    python 03_load_to_db.py                   ← 전체
    python 03_load_to_db.py --limit 50        ← 테스트 (각 테이블 50개)
    python 03_load_to_db.py --skip transfer   ← 이관 정보 건너뜀
    python 03_load_to_db.py --skip consult    ← 상담 사례 건너뜀
"""

import sys
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from modules.connect_db      import connect_db
from modules.load_service_guide import (
    load_disease_info, load_faq, load_vacc_info
)
from modules.load_consultation_docs import load_consultation_docs
from modules.load_transfer   import (
    load_transfer_agencies, load_health_centers, load_vaccination_centers
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="각 데이터 소스별 적재 최대 개수 (테스트용)")
    parser.add_argument("--skip", nargs="*", default=[],
                        choices=["disease", "faq", "vacc", "consult", "transfer"],
                        help="건너뛸 데이터 소스")
    args = parser.parse_args()
    skip = set(args.skip or [])

    conn = connect_db()

    print("=" * 60)
    print("  질병관리청 콜센터 DB 적재 시작")
    print("=" * 60)

    # ── 1. service_guide_documents ──────────────────────────
    if "disease" not in skip:
        load_disease_info(conn, limit=args.limit)
    else:
        print("\n[건너뜀] disease_info")

    if "faq" not in skip:
        load_faq(conn, limit=args.limit)
    else:
        print("\n[건너뜀] FAQ")

    if "vacc" not in skip:
        load_vacc_info(conn, limit=args.limit)
    else:
        print("\n[건너뜀] vacc_info")

    # ── 2. consultation_documents ───────────────────────────
    if "consult" not in skip:
        load_consultation_docs(conn, limit=args.limit)
    else:
        print("\n[건너뜀] consultation_docs")

    # ── 3. 이관 정보 ────────────────────────────────────────
    if "transfer" not in skip:
        load_transfer_agencies(conn)
        load_health_centers(conn)
        load_vaccination_centers(conn)
    else:
        print("\n[건너뜀] 이관 정보")

    # ── 최종 통계 ───────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  적재 완료. 테이블별 건수 확인:")
    print("=" * 60)

    cursor = conn.cursor()
    tables = [
        "service_guide_documents",
        "consultation_documents",
        "transfer_agencies",
        "health_centers",
        "vaccination_centers",
    ]
    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table};")
            count = cursor.fetchone()[0]
            print(f"  {table:<35} {count:>6}개")
        except Exception as e:
            print(f"  {table:<35} 오류: {e}")

    # service_guide_documents document_type별 세부
    cursor.execute("""
        SELECT document_type, COUNT(*)
        FROM service_guide_documents
        GROUP BY document_type
        ORDER BY COUNT(*) DESC;
    """)
    rows = cursor.fetchall()
    if rows:
        print("\n  service_guide_documents 세부:")
        for doc_type, cnt in rows:
            print(f"    - {doc_type:<20} {cnt:>6}개")

    cursor.close()
    conn.close()
    print("\n✓ 완료")


if __name__ == "__main__":
    main()

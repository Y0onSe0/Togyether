"""
04_verify.py
DB 적재 검증 + 벡터 유사도 검색 테스트

실행:
    python 04_verify.py
    python 04_verify.py --search "코로나 격리 기간"
    python 04_verify.py --search "예방접종 이상반응"
"""

import sys
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from modules.connect_db import connect_db
from modules.embedder   import embed_texts, embedding_to_pgvector


# ── 1. 테이블별 건수 확인 ─────────────────────────────────────────────────
def verify_counts(conn):
    print("\n[검증 1] 테이블별 건수")
    cursor = conn.cursor()

    tables = [
        "employees", "sessions", "consultations",
        "service_guide_documents", "consultation_documents",
        "transfer_agencies", "health_centers", "vaccination_centers",
        "keyword_dictionary",
    ]
    for t in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {t};")
            print(f"  {t:<35} {cursor.fetchone()[0]:>6}개")
        except Exception:
            print(f"  {t:<35}  테이블 없음")

    # document_type 세부
    cursor.execute("""
        SELECT document_type, category, COUNT(*)
        FROM service_guide_documents
        GROUP BY document_type, category
        ORDER BY document_type, COUNT(*) DESC;
    """)
    rows = cursor.fetchall()
    if rows:
        print("\n  service_guide_documents 세부 (document_type × category):")
        for doc_type, cat, cnt in rows:
            print(f"    {doc_type:<15} | {(cat or '-'):<25} | {cnt}개")

    cursor.close()


# ── 2. 임베딩 차원 검증 ───────────────────────────────────────────────────
def verify_embeddings(conn):
    print("\n[검증 2] 임베딩 상태")
    cursor = conn.cursor()

    for table, col in [
        ("service_guide_documents", "embedding"),
        ("consultation_documents",  "embedding"),
    ]:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table};")
            total = cursor.fetchone()[0]
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL;")
            has_emb = cursor.fetchone()[0]
            print(f"  {table}: {has_emb}/{total}개 임베딩 완료 ({total - has_emb}개 누락)")
        except Exception as e:
            conn.rollback()
            print(f"  {table}: 오류 — {e}")

    cursor.close()


# ── 3. 벡터 유사도 검색 테스트 ────────────────────────────────────────────
def test_similarity_search(conn, query: str):
    print(f"\n[검증 3] 유사도 검색 테스트: '{query}'")

    # 쿼리 임베딩 (prefix="query")
    vectors = embed_texts([query], prefix="query")
    query_vec = embedding_to_pgvector(vectors[0])

    cursor = conn.cursor()

    # service_guide_documents 검색
    print("\n  ▶ service_guide_documents TOP 5:")
    cursor.execute("""
        SELECT
            id,
            document_type,
            category,
            title,
            ROUND((1 - (embedding <=> %s::vector))::numeric, 4) AS similarity
        FROM service_guide_documents
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT 5;
    """, (query_vec, query_vec))

    for row in cursor.fetchall():
        print(f"    [{row[1]}] {row[3][:40]:<40}  similarity={row[4]}")

    # consultation_documents 검색
    print("\n  ▶ consultation_documents TOP 5:")
    cursor.execute("""
        SELECT
            id,
            category,
            title,
            ROUND((1 - (embedding <=> %s::vector))::numeric, 4) AS similarity
        FROM consultation_documents
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT 5;
    """, (query_vec, query_vec))

    for row in cursor.fetchall():
        print(f"    {row[2][:45]:<45}  similarity={row[3]}")

    cursor.close()


# ── 4. 이관 정보 조회 테스트 ──────────────────────────────────────────────
def verify_transfer(conn):
    print("\n[검증 4] 이관 정보")
    conn.rollback()
    cursor = conn.cursor()

    cursor.execute("SELECT agency_name, phone FROM transfer_agencies LIMIT 5;")
    rows = cursor.fetchall()
    print(f"  transfer_agencies (상위 5개):")
    for r in rows:
        print(f"    {r[0]:<25} {r[1]}")

    cursor.execute("SELECT COUNT(*) FROM health_centers;")
    print(f"\n  health_centers 총: {cursor.fetchone()[0]}개")

    cursor.execute("SELECT COUNT(*) FROM vaccination_centers;")
    print(f"  vaccination_centers 총: {cursor.fetchone()[0]}개")

    cursor.close()


# ── 메인 ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--search", type=str, default=None,
                        help="유사도 검색 테스트 쿼리")
    args = parser.parse_args()

    conn = connect_db()

    verify_counts(conn)
    verify_embeddings(conn)
    verify_transfer(conn)

    if args.search:
        test_similarity_search(conn, args.search)
    else:
        # 기본 테스트 쿼리
        test_similarity_search(conn, "코로나 격리 기간은 얼마나 되나요")

    conn.close()
    print("\n✓ 검증 완료")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
load_kc_from_embedded.py

knowledge_chunks_embedded_v2.json → knowledge_chunks 테이블 재적재.
임베딩이 이미 포함된 JSON을 그대로 사용하므로 API 호출 불필요.

실행:
    cd db/scripts
    python load_kc_from_embedded.py
    python load_kc_from_embedded.py --dry-run   # 실제 INSERT 없이 건수만 확인
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import psycopg2
import psycopg2.extras

from modules.connect_db import connect_db
from modules.embedder   import embedding_to_pgvector

# ── 경로 ──────────────────────────────────────────────────────────────────────
V2_JSON = Path(r"C:\Users\jys72\Downloads\knowledge_chunks_embedded_v2.json")

BATCH_SIZE = 200


def load(conn, chunks: list[dict], dry_run: bool) -> int:
    """TRUNCATE → INSERT. 반환: 삽입 건수."""

    if dry_run:
        print(f"[dry-run] {len(chunks)}건 INSERT 예정 (실제 반영 안 함)")
        return len(chunks)

    cur = conn.cursor()

    # 1. 기존 데이터 삭제
    print("[1] TRUNCATE knowledge_chunks RESTART IDENTITY ...")
    cur.execute("TRUNCATE TABLE knowledge_chunks RESTART IDENTITY;")
    conn.commit()
    print("    ✓")

    # 2. 행 구성
    rows = []
    missing_emb = 0
    for c in chunks:
        emb_raw = c.get("embedding")
        if emb_raw:
            emb = embedding_to_pgvector(emb_raw)
        else:
            emb = None
            missing_emb += 1

        kw = c.get("keywords")
        rows.append((
            c.get("source_id"),
            c.get("data_id"),
            c.get("source_category", "disease"),
            c.get("knowledge_type",  "disease_guideline"),
            c.get("disease_name"),
            c.get("document_title"),
            c.get("chapter"),
            c.get("section_title"),
            c.get("content"),
            c.get("chunk_text", ""),
            c.get("embed_text",  ""),
            c.get("chunk_index", 0),
            json.dumps(kw, ensure_ascii=False) if kw is not None else "[]",
            c.get("source"),
            emb,
        ))

    if missing_emb:
        print(f"    ⚠  임베딩 없는 청크: {missing_emb}건 (embedding=NULL로 삽입)")

    # 3. 배치 INSERT
    print(f"[2] INSERT {len(rows)}건 (배치 {BATCH_SIZE}건씩) ...")
    psycopg2.extras.execute_batch(cur, """
        INSERT INTO knowledge_chunks
            (source_id, data_id, source_category, knowledge_type,
             disease_name, document_title, chapter, section_title,
             content, chunk_text, embed_text, chunk_index,
             keywords, source, embedding)
        VALUES (%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s)
    """, rows, page_size=BATCH_SIZE)
    conn.commit()
    cur.close()
    print("    ✓")

    return len(rows)


def verify(conn):
    """적재 결과 검증."""
    cur = conn.cursor()

    # 전체 건수
    cur.execute("SELECT COUNT(*) FROM knowledge_chunks")
    total = cur.fetchone()[0]
    print(f"\n[검증] knowledge_chunks 전체: {total}건")

    # data_id별 세부
    cur.execute("""
        SELECT data_id, COUNT(*), COUNT(embedding) AS with_emb
        FROM knowledge_chunks
        GROUP BY data_id
        ORDER BY data_id
    """)
    rows = cur.fetchall()
    print(f"  {'data_id':<12} {'청크':>6} {'임베딩':>6}")
    print(f"  {'-'*12} {'-'*6} {'-'*6}")
    for did, cnt, with_emb in rows:
        flag = "" if with_emb == cnt else f"  ⚠ 임베딩 누락 {cnt - with_emb}건"
        print(f"  {str(did):<12} {cnt:>6} {with_emb:>6}{flag}")

    # 다른 테이블 보존 확인
    print()
    for t in ["acw_cards", "agents", "calls", "transfer_agencies", "category_master"]:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(f"  {t:<25} {cur.fetchone()[0]:>6}건 (보존)")
        except Exception as e:
            print(f"  {t}: {e}")

    cur.close()


def main():
    parser = argparse.ArgumentParser(description="v2 JSON → knowledge_chunks 재적재")
    parser.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 건수만 확인")
    args = parser.parse_args()

    if not V2_JSON.exists():
        print(f"[오류] 파일 없음: {V2_JSON}")
        print("       먼저 embed_and_merge.py를 실행하세요.")
        sys.exit(1)

    print(f"[로드] {V2_JSON.name}")
    chunks = json.loads(V2_JSON.read_text(encoding='utf-8'))
    print(f"  총 {len(chunks)}건")

    conn = connect_db()
    inserted = load(conn, chunks, dry_run=args.dry_run)

    if not args.dry_run:
        verify(conn)
        print(f"\n✓ 완료: {inserted}건 적재")

    conn.close()


if __name__ == "__main__":
    main()

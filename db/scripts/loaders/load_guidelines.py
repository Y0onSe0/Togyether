"""
loaders/load_guidelines.py
parsed/*.json → 임베딩 생성 → guidelines 테이블 적재

사용법:
    python loaders/load_guidelines.py                         ← 전체 JSON 적재
    python loaders/load_guidelines.py --file chunks_diagnostic.json  ← 특정 파일만
    python loaders/load_guidelines.py --dry-run               ← DB 적재 없이 확인만

적재 흐름:
    parsed/chunks_diagnostic.json  ─┐
    parsed/chunks_management.json  ─┼→ 임베딩 → guidelines 테이블
    parsed/chunks_별책.json        ─┘  (추가될 파일도 자동으로 처리)
"""

import sys
import json
import argparse
from pathlib import Path

from psycopg2.extras import execute_batch, Json as PgJson

sys.path.append(str(Path(__file__).parent.parent))
from config import BATCH_SIZE, COMMIT_INTERVAL
from modules.embedder import embed_texts, embedding_to_pgvector
from modules.connect_db import connect_db

PARSED_DIR = Path(__file__).parent.parent / "parsed"

INSERT_SQL = """
INSERT INTO guidelines
    (id, disease_name, document_title, chapter, section_title,
     content, chunk_text, chunk_index, keywords, embedding, source, metadata)
VALUES
    (%s, %s, %s, %s, %s,
     %s, %s, %s, %s, %s::vector, %s, %s::jsonb)
ON CONFLICT (id) DO UPDATE SET
    content       = EXCLUDED.content,
    chunk_text    = EXCLUDED.chunk_text,
    embedding     = EXCLUDED.embedding,
    keywords      = EXCLUDED.keywords,
    metadata      = EXCLUDED.metadata;
"""


# ── JSON 로드 ─────────────────────────────────────────────────────────────
def load_json_chunks(json_file: Path) -> list[dict]:
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)


# ── DB 적재 ───────────────────────────────────────────────────────────────
def insert_to_db(chunks: list[dict], embeddings: list):
    conn   = connect_db()
    cursor = conn.cursor()

    # source별로 기존 청크 삭제 (재실행 대비)
    sources = list({c['source'] for c in chunks})
    cursor.execute('DELETE FROM guidelines WHERE source = ANY(%s)', (sources,))
    print(f"  기존 청크 삭제: source {len(sources)}개 파일")

    rows = []
    for chunk, emb in zip(chunks, embeddings):
        # metadata: dict이면 JSON 직렬화, None이면 그대로
        meta = chunk.get('metadata')
        meta_val = json.dumps(meta, ensure_ascii=False) if meta else None

        rows.append((
            chunk['id'],
            chunk['disease_name'],
            chunk['document_title'],
            chunk.get('chapter'),
            chunk.get('section_title'),
            chunk['content'],
            chunk['chunk_text'],
            chunk['chunk_index'],
            chunk['keywords'],
            embedding_to_pgvector(emb),
            chunk['source'],
            meta_val,
        ))

    total, done = len(rows), 0
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i: i + BATCH_SIZE]
        execute_batch(cursor, INSERT_SQL, batch, page_size=BATCH_SIZE)
        done += len(batch)
        if done % COMMIT_INTERVAL == 0 or done == total:
            conn.commit()
            print(f"  적재 중... {done}/{total}")

    cursor.close()
    conn.close()
    print(f"  [완료] {total}개 적재")


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file',    type=str, default=None,
                        help='특정 JSON 파일만 처리 (예: chunks_diagnostic.json)')
    parser.add_argument('--dry-run', action='store_true',
                        help='임베딩/DB 적재 없이 청크 수만 확인')
    args = parser.parse_args()

    # 처리할 JSON 파일 목록
    if args.file:
        json_files = [PARSED_DIR / args.file]
    else:
        json_files = sorted(PARSED_DIR.glob('chunks_*.json'))

    if not json_files:
        print(f"[오류] JSON 파일 없음: {PARSED_DIR}/chunks_*.json")
        print("  먼저 parsers/parse_*.py 를 실행하세요.")
        return

    print(f"[가이드라인 적재] JSON {len(json_files)}개 처리\n")

    all_chunks = []
    for json_file in json_files:
        if not json_file.exists():
            print(f"  [스킵] 파일 없음: {json_file.name}")
            continue

        chunks = load_json_chunks(json_file)
        print(f"  {json_file.name}: {len(chunks)}개 청크")
        all_chunks.extend(chunks)

    total = len(all_chunks)
    print(f"\n총 {total}개 청크 로드됨\n")

    if args.dry_run:
        print("[dry-run] 임베딩/DB 적재 건너뜀")

        # content_type별 통계
        from collections import Counter
        ct = Counter(c.get('content_type', 'unknown') for c in all_chunks)
        print("content_type 분포:")
        for k, v in ct.items():
            print(f"  {k}: {v}개")
        return

    # 임베딩 생성
    print("[임베딩] 생성 중...")
    texts      = [c['chunk_text'] for c in all_chunks]
    embeddings = embed_texts(texts, prefix='passage')

    # DB 적재
    print("\n[DB] 적재 중...")
    insert_to_db(all_chunks, embeddings)

    print(f"\n[완료] guidelines 테이블에 {total}개 청크 적재")


if __name__ == '__main__':
    main()

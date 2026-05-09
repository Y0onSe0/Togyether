"""
load_all.py
parsed/ 폴더의 전체 데이터를 DB에 일괄 적재

실행:
    cd db/scripts
    python load_all.py                 # 전체 적재 (테이블에 기존 데이터 있으면 중단)
    python load_all.py --fresh         # 테이블 초기화 후 적재 ← 첫 실행 시 권장
    python load_all.py --no-embed      # 임베딩 생성 없이 적재 (embedding=NULL)
    python load_all.py --skip kc       # knowledge_chunks 건너뜀
    python load_all.py --skip ta       # transfer_agencies 건너뜀
    python load_all.py --skip acw      # acw_cards 건너뜀
    python load_all.py --limit 20      # 각 파일 20건만 (빠른 테스트)

적재 순서:
    1. DB 스키마 확인/생성   (db_setup_v2.sql)
    2. knowledge_chunks      (DATA-001~014 JSON × 14)
    3. transfer_agencies     (DATA-015 CSV)
    4. agents seed           (system acw_cards용 mock 상담사 5명)
    5. calls seed            (system acw_cards용 mock 통화 200건)
    6. acw_cards             (DATA-016 JSON)
"""

import sys
import json
import csv
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from config import OPENAI_API_KEY
from modules.connect_db import connect_db
from modules.embedder   import embed_texts, embedding_to_pgvector

import psycopg2
import psycopg2.extras

# ── 경로 ───────────────────────────────────────────────────────────────────
SCRIPTS_DIR  = Path(__file__).parent
PARSED_DIR   = SCRIPTS_DIR / "parsed"
SQL_FILE     = SCRIPTS_DIR.parent / "db_setup_v2.sql"

# ── knowledge_chunks 파일 목록 (없으면 경고 후 건너뜀) ─────────────────────
KC_FILES = [
    "DATA_001_chunks_covid.json",
    "DATA_002_chunks_diagnostic.json",
    "DATA_003_chunks_dupest.json",
    "DATA_004_chunks_hiv.json",
    "DATA_005_chunks_mers.json",
    "DATA_006_chunks_tb.json",
    "DATA_007_chunks_vhf.json",
    "DATA_008_chunks_질병관리청_FAQ.json",
    "DATA_009_chunks_crawl.json",
    "DATA_010_chunks_faq.json",
    "DATA_011_chunks_hiv_system.json",
    "DATA_012_chunks_covid19_system.json",
    "DATA_013_chunks_tb_system.json",
    "DATA_014_chunks_tb_hospital.json",
]

TRANSFER_CSV = PARSED_DIR / "DATA_015_질병관리청_소속기관.csv"
ACW_JSON     = PARSED_DIR / "DATA_16_acw_cards_all.json"


# ══════════════════════════════════════════════════════════════════════════
# 0. 스키마 설정 / 테이블 초기화
# ══════════════════════════════════════════════════════════════════════════

def setup_schema(conn):
    """db_setup_v2.sql 실행 (IF NOT EXISTS → 이미 있어도 안전)"""
    if not SQL_FILE.exists():
        print(f"[setup] ❌ SQL 파일 없음: {SQL_FILE}")
        sys.exit(1)
    print(f"[setup] 스키마 적용: {SQL_FILE.name}")
    with open(SQL_FILE, encoding="utf-8") as f:
        sql = f.read()
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    cur.close()
    print("[setup] ✓ 완료\n")


def fresh_drop(conn):
    """기존 테이블 전부 DROP (구버전 스키마 제거 후 재생성용)"""
    print("[fresh] 기존 테이블 삭제 중...")
    cur = conn.cursor()
    cur.execute("""
        DROP TABLE IF EXISTS
            acw_cards,
            calls,
            agents,
            knowledge_chunks,
            transfer_agencies,
            category_master
        CASCADE;
    """)
    conn.commit()
    cur.close()
    print("[fresh] ✓ 완료\n")


def check_empty(conn):
    """테이블에 이미 데이터가 있으면 경고 후 중단"""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM knowledge_chunks")
    cnt = cur.fetchone()[0]
    cur.close()
    if cnt > 0:
        print(f"[경고] knowledge_chunks에 이미 {cnt}건이 있습니다.")
        print("       --fresh 플래그로 초기화 후 재실행하거나, 의도적이면 계속하세요.")
        ans = input("       계속하시겠습니까? (yes / no): ").strip().lower()
        if ans != "yes":
            print("중단됨.")
            sys.exit(0)


# ══════════════════════════════════════════════════════════════════════════
# 1. knowledge_chunks (DATA-001 ~ DATA-014)
# ══════════════════════════════════════════════════════════════════════════

def load_knowledge_chunks(conn, limit=None, no_embed=False):
    print("=" * 60)
    print("  [1/3] knowledge_chunks 적재")
    print("=" * 60)

    total = 0

    for fname in KC_FILES:
        fpath = PARSED_DIR / fname
        if not fpath.exists():
            print(f"  ⚠  파일 없음 → 건너뜀: {fname}")
            continue

        with open(fpath, encoding="utf-8") as f:
            chunks = json.load(f)

        if limit:
            chunks = chunks[:limit]
        if not chunks:
            print(f"  ⚠  빈 파일: {fname}")
            continue

        data_id = chunks[0].get("data_id", "?")
        print(f"\n  {data_id}  {fname}  ({len(chunks)}청크)")

        # 임베딩
        if no_embed:
            embeddings = [None] * len(chunks)
        else:
            texts = [c.get("embed_text") or c.get("chunk_text", "") for c in chunks]
            vecs  = embed_texts(texts)
            embeddings = [embedding_to_pgvector(v) for v in vecs]

        # 행 구성
        rows = []
        for chunk, emb in zip(chunks, embeddings):
            kw = chunk.get("keywords")
            rows.append((
                chunk.get("source_id"),
                chunk.get("data_id"),
                chunk.get("source_category", "disease"),
                chunk.get("knowledge_type",  "disease_guideline"),
                chunk.get("disease_name"),
                chunk.get("document_title"),
                chunk.get("chapter"),
                chunk.get("section_title"),
                chunk.get("content"),
                chunk.get("chunk_text", ""),
                chunk.get("embed_text",  ""),
                chunk.get("chunk_index", 0),
                json.dumps(kw, ensure_ascii=False) if kw is not None else "[]",
                chunk.get("source"),
                emb,
            ))

        cur = conn.cursor()
        psycopg2.extras.execute_batch(cur, """
            INSERT INTO knowledge_chunks
                (source_id, data_id, source_category, knowledge_type,
                 disease_name, document_title, chapter, section_title,
                 content, chunk_text, embed_text, chunk_index,
                 keywords, source, embedding)
            VALUES (%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s)
        """, rows, page_size=200)
        conn.commit()
        cur.close()

        print(f"  ✓  {len(rows)}건 삽입")
        total += len(rows)

    print(f"\n  knowledge_chunks 합계: {total}건\n")


# ══════════════════════════════════════════════════════════════════════════
# 2. transfer_agencies (DATA-015 CSV)
# ══════════════════════════════════════════════════════════════════════════

def load_transfer_agencies(conn, limit=None, no_embed=False):
    print("=" * 60)
    print("  [2/3] transfer_agencies 적재")
    print("=" * 60)

    if not TRANSFER_CSV.exists():
        print(f"  ❌ CSV 없음: {TRANSFER_CSV}\n")
        return

    rows_data = []
    with open(TRANSFER_CSV, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows_data.append(row)

    if limit:
        rows_data = rows_data[:limit]

    print(f"  총 {len(rows_data)}개 기관")

    # description = CSV의 embed_text 컬럼 (담당업무 원문)
    descriptions = [r.get("embed_text", "").strip() or "." for r in rows_data]

    if no_embed:
        embeddings = [None] * len(rows_data)
    else:
        vecs = embed_texts(descriptions)
        embeddings = [embedding_to_pgvector(v) for v in vecs]

    rows = []
    for r, emb in zip(rows_data, embeddings):
        org  = r.get("중분류", "").strip()
        dept = r.get("부서명",  "").strip()
        rows.append((
            r.get("분류", "").strip() or None,
            org,
            dept if dept != org else None,           # 중분류와 같으면 NULL
            r.get("전화번호", "").strip() or None,
            r.get("embed_text", "").strip() or None, # → description
            emb,                                      # → description_embedding
            r.get("담당업무 요약", "").strip() or None, # → description_summary
        ))

    cur = conn.cursor()
    psycopg2.extras.execute_batch(cur, """
        INSERT INTO transfer_agencies
            (category, org_name, dept_name, phone,
             description, description_embedding, description_summary)
        VALUES (%s,%s,%s,%s, %s,%s,%s)
    """, rows, page_size=100)
    conn.commit()
    cur.close()
    print(f"  ✓  {len(rows)}건 삽입\n")


# ══════════════════════════════════════════════════════════════════════════
# 3. acw_cards (DATA-016 JSON)
#    순서: agents → calls → acw_cards
# ══════════════════════════════════════════════════════════════════════════

def _q_text(qa_summary) -> str:
    """qa_summary에서 Q 텍스트 추출 (dict / list 양쪽 처리)"""
    if not qa_summary:
        return ""
    if isinstance(qa_summary, dict):
        return qa_summary.get("q", "")
    if isinstance(qa_summary, list) and qa_summary:
        return qa_summary[0].get("q", "")
    return ""


def _qa_json(qa_summary) -> str | None:
    """qa_summary를 DB JSONB 형식(배열)으로 직렬화"""
    if qa_summary is None:
        return None
    if isinstance(qa_summary, dict):
        return json.dumps([qa_summary], ensure_ascii=False)
    return json.dumps(qa_summary, ensure_ascii=False)


def _seed_agents(conn, system_cards: list):
    """system 카드의 agent_id로 mock 상담사 생성"""
    agent_ids = sorted({c["agent_id"] for c in system_cards if c.get("agent_id")})
    if not agent_ids:
        return

    # bcrypt 없으면 더미 해시 사용
    try:
        import bcrypt
        pw_hash = bcrypt.hashpw(b"kdca1234!", bcrypt.gensalt()).decode()
    except ImportError:
        # bcrypt 미설치 시 더미값 (실제 운영에서는 반드시 bcrypt 사용)
        pw_hash = "$2b$12$dummyhashforseeddataonly000000000000000000000000000"

    rows = [(i, f"agent{i:02d}", f"상담사{i:02d}", pw_hash) for i in agent_ids]
    cur = conn.cursor()
    psycopg2.extras.execute_batch(cur, """
        INSERT INTO agents (agent_id, username, name, password_hash)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (agent_id) DO NOTHING
    """, rows)
    cur.execute(f"SELECT setval('agents_agent_id_seq', {max(agent_ids)}, true)")
    conn.commit()
    cur.close()
    print(f"  ✓  agents: {len(agent_ids)}명 삽입")


def _seed_calls(conn, system_cards: list):
    """system 카드의 통화 정보로 mock calls 생성"""
    call_cards = [c for c in system_cards if c.get("call_id")]
    if not call_cards:
        return

    rows = [(
        c["call_id"],
        c.get("agent_id"),
        "ended",
        c.get("started_at"),
        c.get("ended_at"),
        c.get("duration_sec"),
    ) for c in call_cards]

    cur = conn.cursor()
    psycopg2.extras.execute_batch(cur, """
        INSERT INTO calls (call_id, agent_id, status, started_at, ended_at, duration_sec)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (call_id) DO NOTHING
    """, rows)
    cur.execute(f"SELECT setval('calls_call_id_seq', {max(c['call_id'] for c in call_cards)}, true)")
    conn.commit()
    cur.close()
    print(f"  ✓  calls:  {len(rows)}건 삽입")


def load_acw_cards(conn, limit=None, no_embed=False):
    print("=" * 60)
    print("  [3/3] acw_cards 적재")
    print("=" * 60)

    if not ACW_JSON.exists():
        print(f"  ❌ JSON 없음: {ACW_JSON}\n")
        return

    with open(ACW_JSON, encoding="utf-8") as f:
        cards = json.load(f)

    if limit:
        cards = cards[:limit]

    system_cards = [c for c in cards if c.get("source") == "system"]
    aihub_cards  = [c for c in cards if c.get("source") == "ai_hub"]
    print(f"  system: {len(system_cards)}건 / ai_hub: {len(aihub_cards)}건")

    # 3-1. agents / calls 시드
    print("\n  -- agents/calls 시드 생성 --")
    _seed_agents(conn, system_cards)
    _seed_calls(conn,  system_cards)

    # 3-2. q_embedding 생성
    q_texts = [_q_text(c.get("qa_summary")) or "." for c in cards]

    if no_embed:
        q_embeddings = [None] * len(cards)
    else:
        print(f"\n  -- q_embedding 생성 ({len(cards)}건) --")
        vecs = embed_texts(q_texts)
        q_embeddings = [embedding_to_pgvector(v) for v in vecs]

    # 3-3. acw_cards 삽입
    print("\n  -- acw_cards 삽입 --")
    acw_rows = []
    for c, emb in zip(cards, q_embeddings):
        kw = c.get("keywords")
        acw_rows.append((
            c.get("call_id"),
            c.get("agent_id"),
            c.get("source", "ai_hub"),
            c.get("title"),
            c.get("customer_type"),
            c.get("customer_type_custom"),
            c.get("category"),
            c.get("category_major"),
            c.get("category_mid"),
            json.dumps(c["category_mid_list"], ensure_ascii=False) if c.get("category_mid_list") else None,
            c.get("category_mid_custom"),
            c.get("disease_name"),
            _qa_json(c.get("qa_summary")),
            c.get("transcript"),
            c.get("ai_response_summary"),
            c.get("is_transferred", False),
            c.get("transfer_target"),
            json.dumps(kw, ensure_ascii=False) if kw is not None else "[]",
            c.get("satisfaction"),
            c.get("agent_memo"),
            c.get("is_resolved"),
            c.get("agent_used_ai"),
            emb,
            c.get("acw_started_at"),
            c.get("acw_ended_at"),
            c.get("acw_duration_sec"),
            c.get("created_at"),
            json.dumps(c["ai_guidance"], ensure_ascii=False) if c.get("ai_guidance") else None,
        ))

    cur = conn.cursor()
    psycopg2.extras.execute_batch(cur, """
        INSERT INTO acw_cards (
            call_id, agent_id, source,
            title, customer_type, customer_type_custom,
            category, category_major, category_mid,
            category_mid_list, category_mid_custom,
            disease_name, qa_summary, transcript,
            ai_response_summary, is_transferred, transfer_target,
            keywords, satisfaction, agent_memo,
            is_resolved, agent_used_ai, q_embedding,
            acw_started_at, acw_ended_at, acw_duration_sec,
            created_at, ai_guidance
        ) VALUES (
            %s,%s,%s,
            %s,%s,%s,
            %s,%s,%s,
            %s,%s,
            %s,%s,%s,
            %s,%s,%s,
            %s,%s,%s,
            %s,%s,%s,
            %s,%s,%s,
            COALESCE(%s::timestamp, NOW()),%s
        )
        ON CONFLICT DO NOTHING
    """, acw_rows, page_size=200)
    conn.commit()
    cur.close()
    print(f"  ✓  acw_cards: {len(acw_rows)}건 삽입\n")


# ══════════════════════════════════════════════════════════════════════════
# 4. 결과 검증
# ══════════════════════════════════════════════════════════════════════════

def verify(conn):
    print("=" * 60)
    print("  최종 테이블 건수")
    print("=" * 60)

    cur = conn.cursor()
    tables = [
        ("knowledge_chunks",   "전체"),
        ("transfer_agencies",  "전체"),
        ("agents",             "전체"),
        ("calls",              "전체"),
        ("acw_cards",          "전체"),
    ]
    for table, _ in tables:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        cnt = cur.fetchone()[0]
        print(f"  {table:<25} {cnt:>6}건")

    # knowledge_chunks 세부
    print()
    cur.execute("""
        SELECT data_id, knowledge_type, COUNT(*)
        FROM knowledge_chunks
        GROUP BY data_id, knowledge_type
        ORDER BY data_id
    """)
    rows = cur.fetchall()
    if rows:
        print("  knowledge_chunks 세부:")
        for data_id, ktype, cnt in rows:
            print(f"    {data_id:<12} {ktype:<20} {cnt:>5}건")

    # acw_cards 세부
    print()
    cur.execute("SELECT source, COUNT(*) FROM acw_cards GROUP BY source ORDER BY source")
    rows = cur.fetchall()
    if rows:
        print("  acw_cards 세부:")
        for src, cnt in rows:
            print(f"    {src:<10} {cnt:>5}건")

    cur.close()


# ══════════════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="parsed/ 전체 데이터 DB 적재")
    parser.add_argument("--fresh",    action="store_true", help="테이블 초기화 후 적재")
    parser.add_argument("--no-embed", action="store_true", help="임베딩 생성 건너뜀 (embedding=NULL)")
    parser.add_argument("--skip",     nargs="*", choices=["kc", "ta", "acw"], default=[],
                        help="건너뛸 대상: kc=knowledge_chunks, ta=transfer_agencies, acw=acw_cards")
    parser.add_argument("--limit",    type=int, default=None,
                        help="각 파일 최대 N건만 적재 (테스트용)")
    args = parser.parse_args()
    skip = set(args.skip or [])

    if args.no_embed:
        print("[주의] --no-embed: 임베딩 없이 적재합니다. 벡터 검색 불가.")
    elif not OPENAI_API_KEY:
        print("[오류] OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        print("       임베딩 없이 적재하려면 --no-embed 플래그를 사용하세요.")
        sys.exit(1)

    conn = connect_db()

    # --fresh: 구버전 테이블 DROP → 재생성
    if args.fresh:
        fresh_drop(conn)

    # 스키마 생성 (CREATE IF NOT EXISTS → DROP 후면 새로 생성, 아니면 안전 스킵)
    setup_schema(conn)

    # --fresh 아닐 때: kc를 건너뛰지 않는 경우에만 기존 데이터 경고
    if not args.fresh and "kc" not in skip:
        check_empty(conn)

    # 적재
    if "kc"  not in skip:
        load_knowledge_chunks(conn,  limit=args.limit, no_embed=args.no_embed)

    if "ta"  not in skip:
        load_transfer_agencies(conn, limit=args.limit, no_embed=args.no_embed)

    if "acw" not in skip:
        load_acw_cards(conn, limit=args.limit, no_embed=args.no_embed)

    # 검증
    verify(conn)
    conn.close()
    print("\n✓ 완료")


if __name__ == "__main__":
    main()

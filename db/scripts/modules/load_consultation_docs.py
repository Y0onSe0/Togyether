"""
modules/load_consultation_docs.py
consultation_documents 테이블 적재

원본: merged_all_QA.json (1508개 발화)
처리: 대화셋일련번호 기준으로 묶어서 1 대화셋 = 1 문서로 저장
"""

import json
import sys
import re
from pathlib import Path
from collections import defaultdict
from psycopg2.extras import execute_batch

sys.path.append(str(Path(__file__).parent.parent))
from config import CONSULTATION_FILE, EMBED_CONSULT_FILE, BATCH_SIZE, COMMIT_INTERVAL
from modules.embedder import embedding_to_pgvector

INSERT_SQL = """
INSERT INTO consultation_documents
    (id, session_id, category, title,
     content, intents, keywords, metadata, embedding, source)
VALUES
    (%s, %s, %s, %s,
     %s, %s, %s, %s::jsonb, %s::vector, %s)
ON CONFLICT (id) DO UPDATE SET
    content   = EXCLUDED.content,
    embedding = EXCLUDED.embedding,
    intents   = EXCLUDED.intents,
    keywords  = EXCLUDED.keywords;
"""


def _group_by_session(data: list[dict]) -> dict:
    """발화 목록을 대화셋일련번호 기준으로 묶기"""
    sessions = defaultdict(list)
    for row in data:
        sessions[row["대화셋일련번호"]].append(row)
    return sessions


def _build_document(session_id: str, rows: list[dict]) -> dict:
    """
    하나의 대화셋 → 1개 문서 생성
    """
    # 대화 전문 (content)
    turns = []
    for row in rows:
        speaker = row["화자"]
        q = row.get("고객질문(요청)", "").strip()
        a = row.get("상담사답변",     "").strip()
        if speaker == "고객"  and q:
            turns.append(f"고객: {q}")
        elif speaker == "상담사" and a:
            turns.append(f"상담사: {a}")
    content = "\n".join(turns)

    # 고객 의도 목록 (중복 제거, 순서 유지)
    intents = list(dict.fromkeys(
        r["고객의도"].strip()
        for r in rows
        if r.get("고객의도", "").strip()
    ))

    # 카테고리
    category = rows[0].get("카테고리", "")
    source_file = rows[0].get("출처파일", "")

    # 제목: 주요 의도 기반
    main_intent = intents[1] if len(intents) > 1 else (intents[0] if intents else session_id)
    title = f"{category} - {main_intent}" if category else main_intent

    # 키워드: 고객 발화에서 명사 추출
    customer_text = " ".join(
        r.get("고객질문(요청)", "")
        for r in rows if r["화자"] == "고객"
    )
    keywords = list({
        w for w in re.findall(r'[가-힣]{2,}', customer_text)
        if len(w) >= 2
    })[:15]

    # text (임베딩용): 의도 + 고객 발화만
    text = f"{' '.join(intents)} " + " ".join(
        r.get("고객질문(요청)", "")
        for r in rows if r["화자"] == "고객"
    )

    return {
        "session_id":  session_id,
        "category":    category,
        "title":       title,
        "content":     content,
        "text":        text,
        "intents":     intents,
        "keywords":    keywords,
        "source_file": source_file,
        "turn_count":  len(turns),
    }


def load_consultation_docs(conn, limit: int = None):
    """
    merged_all_QA.json → consultation_documents 테이블
    """
    # 임베딩 파일 우선, 없으면 원본 사용
    path = EMBED_CONSULT_FILE if EMBED_CONSULT_FILE.exists() else CONSULTATION_FILE
    print(f"\n[consultation_docs] 파일: {path.name}")

    with open(path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # 임베딩 파일이면 이미 문서 단위로 변환된 것
    if EMBED_CONSULT_FILE.exists():
        _load_from_embed_file(conn, raw_data, limit)
    else:
        _load_from_raw_file(conn, raw_data, limit)


def _load_from_raw_file(conn, raw_data: list, limit: int = None):
    """원본 발화 데이터 → 대화셋 묶음 → INSERT (임베딩 없이)"""
    sessions = _group_by_session(raw_data)
    session_list = list(sessions.items())
    if limit:
        session_list = session_list[:limit]

    print(f"  대화셋 수: {len(session_list)}개 (발화 {len(raw_data)}개)")

    rows = []
    for idx, (session_id, turns) in enumerate(session_list, start=1):
        doc = _build_document(session_id, turns)
        doc_id = f"consult_doc_{idx:04d}"

        rows.append((
            doc_id,
            doc["session_id"],
            doc["category"],
            doc["title"],
            doc["content"],
            doc["intents"],
            doc["keywords"],
            json.dumps({
                "turn_count":  doc["turn_count"],
                "source_file": doc["source_file"],
            }, ensure_ascii=False),
            None,                           # embedding 없음
            "kdca_callcenter",
        ))

    _bulk_insert(conn, rows)


def _load_from_embed_file(conn, embed_data: list, limit: int = None):
    """임베딩 완료된 문서 리스트 → INSERT"""
    if limit:
        embed_data = embed_data[:limit]

    print(f"  문서 수: {len(embed_data)}개 (임베딩 포함)")

    rows = []
    for doc in embed_data:
        embedding = doc.get("embedding")
        emb_str   = embedding_to_pgvector(embedding) if embedding else None

        rows.append((
            doc["id"],
            doc.get("session_id", ""),
            doc.get("category",   ""),
            doc.get("title",      ""),
            doc["content"],
            doc.get("intents",  []),
            doc.get("keywords", []),
            json.dumps(doc.get("metadata", {}), ensure_ascii=False),
            emb_str,
            doc.get("source", "kdca_callcenter"),
        ))

    _bulk_insert(conn, rows)


def _bulk_insert(conn, rows: list):
    cursor = conn.cursor()
    total  = len(rows)
    done   = 0

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        execute_batch(cursor, INSERT_SQL, batch, page_size=BATCH_SIZE)
        done += len(batch)

        if done % COMMIT_INTERVAL == 0 or done == total:
            conn.commit()
            print(f"  [consultation_docs] {done}/{total} 적재 완료")

    print(f"  [consultation_docs] ✓ 총 {total}개 완료")
    cursor.close()

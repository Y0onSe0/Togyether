"""
modules/load_service_guide.py
service_guide_documents 테이블 적재

document_type = 'disease_info'
  ├── diseases1.json         133개  감염병 정보
  ├── kdca_faq_by_category   166개  감염병 FAQ
  ├── kdca_dportal_faq        90개  감염병 포털 FAQ
  └── vacc_info.json          10개  예방접종 정보

document_type = 'guideline'
  └── PDF 청킹 결과 (수천 개) ← 별도 스크립트에서 처리
"""

import json
import sys
import re
from pathlib import Path
from psycopg2.extras import execute_batch

sys.path.append(str(Path(__file__).parent.parent))
from config import (
    DISEASE_INFO_FILE, FAQ_FILE, DPORTAL_FAQ_FILE, VACC_INFO_FILE,
    EMBED_DISEASE_FILE, EMBED_FAQ_FILE, EMBED_VACC_FILE,
    BATCH_SIZE, COMMIT_INTERVAL
)
from modules.embedder import embedding_to_pgvector

# ── INSERT SQL ─────────────────────────────────────────────────────────────
INSERT_SQL = """
INSERT INTO service_guide_documents
    (id, document_type, category, sub_category,
     title, content, chunk_text, chunk_index,
     metadata, keywords, embedding, source, priority)
VALUES
    (%s, %s, %s, %s,
     %s, %s, %s, %s,
     %s::jsonb, %s, %s::vector, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    content      = EXCLUDED.content,
    embedding    = EXCLUDED.embedding,
    keywords     = EXCLUDED.keywords,
    updated_at   = NOW();
"""


# ── 1. 감염병 정보 적재 ────────────────────────────────────────────────────
def load_disease_info(conn, limit: int = None):
    """
    diseases_with_embeddings.json → service_guide_documents
    (document_type = 'disease_info')
    """
    path = EMBED_DISEASE_FILE if EMBED_DISEASE_FILE.exists() else DISEASE_INFO_FILE
    print(f"\n[disease_info] 파일: {path.name}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if limit:
        data = data[:limit]

    rows = []
    for doc in data:
        meta = doc.get("metadata", {})
        embedding = doc.get("embedding")
        emb_str   = embedding_to_pgvector(embedding) if embedding else None

        rows.append((
            doc["id"],                          # id
            "disease_info",                     # document_type
            meta.get("category", "기타"),        # category
            meta.get("group_name", ""),         # sub_category (등급)
            doc["title"],                       # title
            doc["content"],                     # content
            doc.get("text", doc["content"]),    # chunk_text (임베딩용)
            0,                                  # chunk_index
            json.dumps({                        # metadata JSONB
                "disease_name": meta.get("disease_name", ""),
                "icd_code":     meta.get("icd_code", ""),
                "group_name":   meta.get("group_name", ""),
                "department":   meta.get("department", ""),
                "sections":     meta.get("sections", [])
            }, ensure_ascii=False),
            meta.get("keywords", []),           # keywords TEXT[]
            emb_str,                            # embedding
            meta.get("source", "kdca_disease_portal"),  # source
            8,                                  # priority (감염병 정보는 높게)
        ))

    _bulk_insert(conn, rows, "disease_info")


# ── 2. FAQ 적재 ───────────────────────────────────────────────────────────
def load_faq(conn, limit: int = None):
    """
    kdca_faq_by_category.json + kdca_dportal_faq.json
    → service_guide_documents (document_type = 'disease_info')
    """
    items = []

    # FAQ 파일 1
    with open(FAQ_FILE, "r", encoding="utf-8") as f:
        d = json.load(f)
    items += [{"source": "kdca_faq", **i} for i in d.get("items", [])]

    # FAQ 파일 2
    with open(DPORTAL_FAQ_FILE, "r", encoding="utf-8") as f:
        d = json.load(f)
    items += [{"source": "kdca_dportal_faq", **i} for i in d.get("items", [])]

    # 임베딩 파일 있으면 병합
    embed_map = {}
    if EMBED_FAQ_FILE.exists():
        with open(EMBED_FAQ_FILE, "r", encoding="utf-8") as f:
            for doc in json.load(f):
                embed_map[doc["id"]] = doc.get("embedding")

    if limit:
        items = items[:limit]

    print(f"\n[FAQ] 총 {len(items)}개")

    rows = []
    for idx, item in enumerate(items, start=1):
        faq_id    = f"faq_{idx:04d}"
        question  = item.get("question", "")
        answer    = item.get("answer",   "")
        category  = item.get("category", "FAQ")
        source    = item.get("source",   "kdca_faq")

        content   = f"Q: {question}\nA: {answer}"
        chunk_text = f"{category} FAQ {question} {answer}"

        embedding = embed_map.get(faq_id)
        emb_str   = embedding_to_pgvector(embedding) if embedding else None

        # 키워드: 질문에서 명사 추출 (간단 버전)
        keywords  = list({w for w in re.findall(r'[가-힣]{2,}', question) if len(w) >= 2})[:10]

        rows.append((
            faq_id, "disease_info", category, "FAQ",
            f"{category} FAQ - {question[:50]}",
            content, chunk_text, 0,
            json.dumps({"category": category, "source": source}, ensure_ascii=False),
            keywords, emb_str, source, 6,
        ))

    _bulk_insert(conn, rows, "FAQ")


# ── 3. 예방접종 정보 적재 ─────────────────────────────────────────────────
def load_vacc_info(conn, limit: int = None):
    """
    vacc_info.json → service_guide_documents (document_type = 'disease_info')
    """
    print(f"\n[vacc_info] 파일: {VACC_INFO_FILE.name}")

    with open(VACC_INFO_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)   # dict: {백신명: {url, paragraphs, tables}}

    embed_map = {}
    if EMBED_VACC_FILE.exists():
        with open(EMBED_VACC_FILE, "r", encoding="utf-8") as f:
            for doc in json.load(f):
                embed_map[doc["id"]] = doc.get("embedding")

    items = list(data.items())
    if limit:
        items = items[:limit]

    rows = []
    for idx, (vacc_name, info) in enumerate(items, start=1):
        vacc_id    = f"vacc_info_{idx:03d}"
        paragraphs = info.get("paragraphs", [])
        tables     = info.get("tables", [])

        # 테이블 → 텍스트 변환
        table_lines = []
        for table in tables:
            for row in table:
                if len(row) == 2:
                    table_lines.append(f"{row[0]}: {row[1]}")

        content    = "\n".join(paragraphs + table_lines)
        chunk_text = f"예방접종 {vacc_name} {content}"

        embedding = embed_map.get(vacc_id)
        emb_str   = embedding_to_pgvector(embedding) if embedding else None

        rows.append((
            vacc_id, "disease_info", "예방접종", vacc_name,
            f"{vacc_name} 예방접종 안내",
            content, chunk_text, 0,
            json.dumps({"vaccine_name": vacc_name, "url": info.get("url", "")},
                       ensure_ascii=False),
            [vacc_name, "예방접종", "백신"],
            emb_str, "kahp_vaccination", 7,
        ))

    _bulk_insert(conn, rows, "vacc_info")


# ── 4. 지침 PDF 청크 적재 ─────────────────────────────────────────────────
def load_guideline_chunks(conn, chunks: list[dict]):
    """
    PDF 파싱 + 청킹 결과를 받아서 적재.
    chunks: [{"id", "disease_name", "document_title", "chapter",
               "section_title", "content", "chunk_text", "chunk_index",
               "keywords", "embedding", "source"}, ...]
    """
    print(f"\n[guideline] {len(chunks)}개 청크 적재 중...")

    rows = []
    for chunk in chunks:
        embedding = chunk.get("embedding")
        emb_str   = embedding_to_pgvector(embedding) if embedding else None

        rows.append((
            chunk["id"],
            "guideline",
            chunk.get("disease_name", ""),
            chunk.get("chapter", ""),
            chunk.get("document_title", ""),
            chunk["content"],
            chunk.get("chunk_text", chunk["content"]),
            chunk.get("chunk_index", 0),
            json.dumps({
                "disease_name":  chunk.get("disease_name", ""),
                "source_file":   chunk.get("source", ""),
                "chapter":       chunk.get("chapter", ""),
                "section_title": chunk.get("section_title", ""),
            }, ensure_ascii=False),
            chunk.get("keywords", []),
            emb_str,
            chunk.get("source", "kdca_guideline_pdf"),
            9,   # 지침은 최우선 순위
        ))

    _bulk_insert(conn, rows, "guideline")


# ── 공통 배치 INSERT ──────────────────────────────────────────────────────
def _bulk_insert(conn, rows: list, label: str):
    cursor = conn.cursor()
    total  = len(rows)
    done   = 0

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        execute_batch(cursor, INSERT_SQL, batch, page_size=BATCH_SIZE)
        done += len(batch)

        if done % COMMIT_INTERVAL == 0 or done == total:
            conn.commit()
            print(f"  [{label}] {done}/{total} 적재 완료")

    print(f"  [{label}] ✓ 총 {total}개 완료")
    cursor.close()

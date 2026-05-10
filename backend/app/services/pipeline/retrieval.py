"""
RAG 검색 파이프라인 (v5)
query + is_oos → 2-A / 2-B / 2-C 병렬 검색 → 통합 결과 반환

RTL-SRCH-001: 쿼리 임베딩 (text-embedding-3-small, 1536d)
RTL-SRCH-002: 2-A — knowledge_chunks 통합 검색 (is_oos=false 시에만)
  - disease_name 있음: 감염병 청크는 disease_name 프리필터, 시스템 청크는 항상 포함
  - disease_name 없음: 전체 청크 검색
  - 코사인 유사도 ≥ 0.70, Top-3
RTL-SRCH-003: 2-B — acw_cards q_embedding 유사사례 검색 (항상 실행)
  - 코사인 유사도 ≥ 0.70, Top-3 (DB 연동 전: 빈 배열 반환)
RTL-SRCH-004: 2-C — transfer_agencies 이관기관 검색 (항상 실행)
  - 코사인 유사도 ≥ 0.70, Top-3 (DB 연동 전: 빈 배열 반환)

반환:
  {
    "step2a": [{chunk_id, chunk_text, knowledge_type, disease_name,
                document_title, section_title, data_id, similarity}],
    "step2b": [{acw_id, title, disease_name, qa_summary, similarity}],
    "step2c": [{org_name, dept_name, phone, description_summary, similarity}],
    "_disease_filter": str | None,
  }
"""

import asyncio
import json
import os
import numpy as np
from pathlib import Path
from openai import AsyncOpenAI

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
CHUNKS_PATH     = Path(__file__).parent.parent / "감염병db" / "knowledge_chunks_embedded.json"
EMBEDDING_MODEL = "text-embedding-3-small"
SIMILARITY_THRESHOLD = 0.70
TOP_K = 3

# ─────────────────────────────────────────
# 전역 캐시 (lazy load)
# ─────────────────────────────────────────
_client: AsyncOpenAI | None = None

_all_vecs: np.ndarray | None = None
_all_meta: list | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


def _load_chunks() -> tuple[np.ndarray, list]:
    global _all_vecs, _all_meta
    if _all_vecs is None:
        with open(CHUNKS_PATH, encoding="utf-8") as f:
            chunks = json.load(f)
        _all_meta = chunks
        _all_vecs = np.array([c["embedding"] for c in chunks], dtype=np.float32)
    return _all_vecs, _all_meta


# ─────────────────────────────────────────
# 임베딩
# ─────────────────────────────────────────
async def embed_query(text: str) -> np.ndarray:
    """쿼리 → 1536d 임베딩 벡터 (RTL-SRCH-001)"""
    resp = await _get_client().embeddings.create(
        model=EMBEDDING_MODEL, input=[text[:8000]]
    )
    return np.array(resp.data[0].embedding, dtype=np.float32)


# ─────────────────────────────────────────
# 코사인 유사도 검색 (임계값 필터 포함)
# ─────────────────────────────────────────
def _cosine_search(
    query_vec: np.ndarray,
    vecs: np.ndarray,
    meta: list,
    k: int = TOP_K,
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[dict]:
    norms = np.linalg.norm(vecs, axis=1)
    q_norm = np.linalg.norm(query_vec)
    scores = vecs @ query_vec / (norms * q_norm + 1e-9)

    top_idx = np.argsort(scores)[::-1][:k]
    results = []
    for i in top_idx:
        sim = float(scores[i])
        if sim >= threshold:
            results.append({"_idx": int(i), "similarity": sim})
    return results


# ─────────────────────────────────────────
# 2-A: knowledge_chunks 통합 검색 (RTL-SRCH-002)
# ─────────────────────────────────────────
def _search_2a(
    query_vec: np.ndarray,
    disease_name: str | None,
    top_k: int = TOP_K,
) -> list[dict]:
    vecs, meta = _load_chunks()

    if disease_name:
        # 감염병 청크: disease_name 프리필터 / 시스템 청크: 항상 포함
        idx_list = [
            i for i, c in enumerate(meta)
            if c.get("source_category") != "disease"
            or c.get("disease_name") == disease_name
        ]
        f_vecs = vecs[idx_list]
        f_meta = [meta[i] for i in idx_list]
    else:
        f_vecs = vecs
        f_meta = meta

    hits = _cosine_search(query_vec, f_vecs, f_meta, k=top_k)

    results = []
    for h in hits:
        c = f_meta[h["_idx"]]
        results.append({
            "chunk_id":       c.get("chunk_id") or c.get("id", ""),
            "chunk_text":     c.get("chunk_text", ""),
            "knowledge_type": c.get("knowledge_type", ""),
            "disease_name":   c.get("disease_name") or "",
            "document_title": c.get("document_title") or c.get("source", ""),
            "section_title":  c.get("section_title") or c.get("section", ""),
            "data_id":        c.get("data_id") or "",
            "similarity":     h["similarity"],
        })
    return results


# ─────────────────────────────────────────
# 2-B: acw_cards 유사사례 검색 (RTL-SRCH-003)
# ─────────────────────────────────────────
async def _search_2b(query_vec: np.ndarray, top_k: int = TOP_K) -> list[dict]:
    """acw_cards.q_embedding 코사인 검색 — DB 연동 전 stub"""
    # TODO: pgvector 연동 후 실제 DB 쿼리로 교체
    # SELECT acw_id, title, disease_name, qa_summary,
    #        1 - (q_embedding <=> $1::vector) AS similarity
    # FROM acw_cards
    # WHERE 1 - (q_embedding <=> $1::vector) >= 0.70
    # ORDER BY similarity DESC LIMIT $2
    return []


# ─────────────────────────────────────────
# 2-C: transfer_agencies 이관기관 검색 (RTL-SRCH-004)
# ─────────────────────────────────────────
async def _search_2c(query_vec: np.ndarray, top_k: int = TOP_K) -> list[dict]:
    """transfer_agencies.description_embedding 코사인 검색 — DB 연동 전 stub"""
    # TODO: pgvector 연동 후 실제 DB 쿼리로 교체
    # SELECT org_name, dept_name, phone, description_summary,
    #        1 - (description_embedding <=> $1::vector) AS similarity
    # FROM transfer_agencies
    # WHERE 1 - (description_embedding <=> $1::vector) >= 0.70
    # ORDER BY similarity DESC LIMIT $2
    return []


# ─────────────────────────────────────────
# 공개 인터페이스
# ─────────────────────────────────────────
async def retrieve_all(
    query: str,
    is_oos: bool,
    disease_name: str | None = None,
    query_vec: np.ndarray | None = None,
    top_k: int = TOP_K,
) -> dict:
    """
    RTL-SRCH-001~004 통합 검색.

    파라미터:
      query       — STEP 1 정제 쿼리
      is_oos      — STEP 1 출력 (2-A 실행 여부 제어)
      disease_name — STEP 1 출력, nullable (2-A 프리필터)
      query_vec   — 이미 생성된 임베딩 벡터 (None이면 내부에서 생성)
      top_k       — 각 검색 최대 반환 수 (기본 3)

    반환:
    {
        "step2a": [{chunk_id, chunk_text, knowledge_type, disease_name,
                    document_title, section_title, data_id, similarity}],
        "step2b": [{acw_id, title, disease_name, qa_summary, similarity}],
        "step2c": [{org_name, dept_name, phone, description_summary, similarity}],
        "_disease_filter": str | None,
    }
    """
    # RTL-SRCH-001: 쿼리 임베딩 (전달받은 벡터 재사용 가능)
    if query_vec is None:
        query_vec = await embed_query(query)

    # 2-B / 2-C는 항상 실행 (병렬)
    step2b, step2c = await asyncio.gather(
        _search_2b(query_vec, top_k),
        _search_2c(query_vec, top_k),
    )

    # 2-A는 is_oos=false 시에만 실행 (동기 NumPy 연산)
    if is_oos:
        step2a = []
        disease_filter = None
    else:
        loop = asyncio.get_event_loop()
        step2a = await loop.run_in_executor(
            None, _search_2a, query_vec, disease_name, top_k
        )
        disease_filter = disease_name if disease_name else None

    return {
        "step2a":          step2a,
        "step2b":          step2b,
        "step2c":          step2c,
        "_disease_filter": disease_filter,
    }


# ─────────────────────────────────────────
# CLI 테스트
# ─────────────────────────────────────────
async def _main():
    import sys

    query        = sys.argv[1] if len(sys.argv) > 1 else "노로바이러스 격리 기간"
    is_oos_str   = sys.argv[2] if len(sys.argv) > 2 else "false"
    disease_name = sys.argv[3] if len(sys.argv) > 3 else None

    is_oos = is_oos_str.lower() == "true"

    print(f"쿼리    : {query}")
    print(f"is_oos  : {is_oos}")
    print(f"병명    : {disease_name}\n")

    out = await retrieve_all(query, is_oos, disease_name)

    print(f"=== 2-A (knowledge_chunks) — {len(out['step2a'])}건 ===")
    for i, h in enumerate(out["step2a"], 1):
        print(f"  {i}. [sim={h['similarity']:.4f}] [{h['knowledge_type']}] "
              f"{h['disease_name']} — {h['section_title']}")
        print(f"     {h['chunk_text'][:100].replace(chr(10),' ')}...")

    print(f"\n=== 2-B (acw_cards) — {len(out['step2b'])}건 ===")
    for i, h in enumerate(out["step2b"], 1):
        print(f"  {i}. [sim={h['similarity']:.4f}] {h['title']}")

    print(f"\n=== 2-C (transfer_agencies) — {len(out['step2c'])}건 ===")
    for i, h in enumerate(out["step2c"], 1):
        print(f"  {i}. [sim={h['similarity']:.4f}] {h['org_name']} {h['dept_name']}")


if __name__ == "__main__":
    asyncio.run(_main())

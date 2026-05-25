"""
RAG 검색 파이프라인 (v8 — Hybrid RAG: Dense + BM25 + RRF + Cross-Encoder Reranking)
knowledge_chunks DB에서 청크를 로드해 in-memory Hybrid RAG 수행

RTL-SRCH-001: 쿼리 임베딩 (text-embedding-3-small, 1536d)
RTL-SRCH-002: 2-A — knowledge_chunks 하이브리드 검색 (is_oos=false 시에만)
  - Dense: NumPy 코사인 유사도 (embedding 벡터 in-memory 캐시)
  - BM25:  키워드 기반 in-memory 검색 (rank-bm25)
  - RRF:   Reciprocal Rank Fusion으로 결합 (k=60)
  - Rerank: bongsoo/klue-cross-encoder-v1 (sentence-transformers 설치 시 활성화)

청크 데이터: 서버 시작 후 첫 요청 시 knowledge_chunks 테이블에서 전체 로드 (lazy)
2-B/2-C: ws.py에서 step2_search.py를 통해 DB 직접 조회

반환:
  {
    "step2a": [{chunk_id, chunk_text, knowledge_type, disease_name,
                document_title, section_title, data_id, similarity}],
    "step2b": [],
    "step2c": [],
    "_disease_filter": str | None,
  }
"""

import asyncio
import json
import re
import numpy as np
from openai import AsyncOpenAI
from rank_bm25 import BM25Okapi
from app.core.config import settings
from app.core.database import get_pool

try:
    from sentence_transformers import CrossEncoder as _CrossEncoder
    _CE_AVAILABLE = True
except ImportError:
    _CE_AVAILABLE = False

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
EMBEDDING_MODEL      = "text-embedding-3-small"
SIMILARITY_THRESHOLD = 0.40
TOP_K     = 5
RRF_K     = 60
BM25_TOP  = 20
DENSE_TOP = 20
W_DENSE   = 1.0
W_BM25    = 1.0
RERANK_MODEL = "bongsoo/klue-cross-encoder-v1"
RERANK_POOL  = 20
USE_RERANK   = True

# ─────────────────────────────────────────
# 전역 캐시 (lazy load — 첫 요청 시 DB에서 로드)
# ─────────────────────────────────────────
_client: AsyncOpenAI | None = None

_all_vecs: np.ndarray | None = None   # shape: (N, 1536)
_all_meta: list | None = None          # list of chunk dicts

_reranker = None

_bm25_index: BM25Okapi | None = None
_bm25_meta: list | None = None

_load_lock: asyncio.Lock | None = None


# ─────────────────────────────────────────
# 병명 별칭 테이블 (LLM 출력 → KB disease_name)
# ─────────────────────────────────────────
DISEASE_NAME_ALIASES: dict[str, str] = {
    "HIV/AIDS":        "후천성면역결핍증(AIDS)",
    "HIV":             "후천성면역결핍증(AIDS)",
    "에이즈":          "후천성면역결핍증(AIDS)",
    "코로나":          "코로나바이러스감염증-19",
    "코로나19":        "코로나바이러스감염증-19",
    "COVID-19":        "코로나바이러스감염증-19",
    "메르스":          "중동호흡기증후군(MERS)",
    "MERS":            "중동호흡기증후군(MERS)",
    "독감":            "인플루엔자",
    "에이형 간염":     "A형간염",
    "A형 간염":        "A형간염",
    "비형 간염":       "B형간염",
    "B형 간염":        "B형간염",
    "씨형 간염":       "C형간염",
    "C형 간염":        "C형간염",
    "이형 간염":       "E형간염",
    "E형 간염":        "E형간염",
    "CRE":             "카바페넴내성장내세균목(CRE) 감염증",
    "카바페넴":        "카바페넴내성장내세균목(CRE) 감염증",
    "VRE":             "반코마이신내성장알균(VRE) 감염증",
    "VRSA":            "반코마이신내성황색포도알균(VRSA) 감염증",
    "MRAB":            "다제내성아시네토박터바우마니균(MRAB) 감염증",
    "볼거리":          "유행성이하선염",
    "수족구":          "수족구병",
    "노로":            "노로바이러스 감염증",
    "노로바이러스":    "노로바이러스 감염증",
    "살모넬라":        "살모넬라균 감염증",
    "캄필로박터":      "캄필로박터균 감염증",
    "루벨라":          "풍진",
}


def _normalize_disease_name(disease_name: str | None) -> str | None:
    if not disease_name:
        return disease_name
    return DISEASE_NAME_ALIASES.get(disease_name, disease_name)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


# ─────────────────────────────────────────
# DB에서 전체 청크 로드 (최초 1회)
# ─────────────────────────────────────────
async def _ensure_chunks_loaded() -> tuple[np.ndarray, list]:
    """knowledge_chunks 테이블에서 전체 데이터 로드 (lazy, thread-safe)"""
    global _all_vecs, _all_meta, _bm25_index, _bm25_meta, _load_lock

    if _all_vecs is not None:
        return _all_vecs, _all_meta

    # asyncio.Lock은 첫 호출 시 생성 (이벤트 루프 보장)
    if _load_lock is None:
        _load_lock = asyncio.Lock()

    async with _load_lock:
        if _all_vecs is not None:   # double-check
            return _all_vecs, _all_meta

        print("[retrieval] knowledge_chunks DB 로드 중...")
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT chunk_index::text AS chunk_id,
                   data_id, document_title, section_title,
                   disease_name, knowledge_type, chunk_text,
                   embedding::text AS embedding
            FROM knowledge_chunks
            ORDER BY chunk_index
            """
        )

        meta = []
        vecs = []
        for row in rows:
            emb_raw = row["embedding"]
            # pgvector → Python list[float] 파싱
            emb = json.loads(emb_raw) if isinstance(emb_raw, str) else list(emb_raw)
            chunk = {
                "chunk_id":       row["chunk_id"],
                "data_id":        row["data_id"] or "",
                "document_title": row["document_title"] or "",
                "section_title":  row["section_title"] or "",
                "disease_name":   row["disease_name"] or "",
                "knowledge_type": row["knowledge_type"] or "",
                "chunk_text":     row["chunk_text"] or "",
            }
            meta.append(chunk)
            vecs.append(emb)

        _all_meta = meta
        _all_vecs = np.array(vecs, dtype=np.float32)

        # BM25 인덱스 동시 빌드
        corpus = [_tokenize_ko(c["chunk_text"]) for c in meta]
        _bm25_index = BM25Okapi(corpus)
        _bm25_meta = meta

        print(f"[retrieval] 로드 완료: {len(meta):,}건, shape={_all_vecs.shape}")
        return _all_vecs, _all_meta


# ─────────────────────────────────────────
# Reranker
# ─────────────────────────────────────────
def _load_reranker():
    global _reranker
    if _reranker is None:
        if not _CE_AVAILABLE:
            raise ImportError("sentence-transformers 필요: pip install sentence-transformers")
        _reranker = _CrossEncoder(RERANK_MODEL, max_length=512)
    return _reranker


def _rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    if not candidates:
        return candidates
    model = _load_reranker()
    pairs = [(query, c["chunk_text"]) for c in candidates]
    scores = model.predict(pairs)
    ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
    results = []
    for score, c in ranked[:top_k]:
        c = dict(c)
        c["rerank_score"] = round(float(score), 4)
        results.append(c)
    return results


# ─────────────────────────────────────────
# 토크나이저
# ─────────────────────────────────────────
def _tokenize_ko(text: str) -> list[str]:
    tokens = re.split(r"[\s\(\)\[\]▢◾·•\-,./]+", text)
    return [t for t in tokens if len(t) >= 2]


# ─────────────────────────────────────────
# 임베딩
# ─────────────────────────────────────────
async def embed_query(text: str) -> np.ndarray:
    resp = await _get_client().embeddings.create(
        model=EMBEDDING_MODEL, input=[text[:8000]]
    )
    return np.array(resp.data[0].embedding, dtype=np.float32)


# ─────────────────────────────────────────
# Dense: 코사인 유사도 검색
# ─────────────────────────────────────────
def _cosine_search(
    query_vec: np.ndarray,
    vecs: np.ndarray,
    k: int,
) -> list[tuple[int, float]]:
    norms = np.linalg.norm(vecs, axis=1)
    q_norm = np.linalg.norm(query_vec)
    scores = vecs @ query_vec / (norms * q_norm + 1e-9)
    top_idx = np.argsort(scores)[::-1][:k]
    return [(int(i), float(scores[i])) for i in top_idx]


def _meta_to_result(c: dict, score: float) -> dict:
    return {
        "chunk_id":       c.get("chunk_id", ""),
        "chunk_text":     c.get("chunk_text", ""),
        "knowledge_type": c.get("knowledge_type", ""),
        "disease_name":   c.get("disease_name", ""),
        "document_title": c.get("document_title", ""),
        "section_title":  c.get("section_title", ""),
        "data_id":        c.get("data_id", ""),
        "similarity":     round(score, 4),
    }


# ─────────────────────────────────────────
# BM25: 키워드 검색
# ─────────────────────────────────────────
def _bm25_search(query: str, k: int) -> list[tuple[int, float]]:
    tokens = _tokenize_ko(query)
    scores = _bm25_index.get_scores(tokens)
    top_idx = np.argsort(scores)[::-1][:k]
    return [(int(i), float(scores[i])) for i in top_idx if scores[i] > 0]


# ─────────────────────────────────────────
# RRF 병합
# ─────────────────────────────────────────
def _rrf_merge(
    dense_ranked: list[tuple[int, float]],
    bm25_ranked:  list[tuple[int, float]],
    meta: list,
    top_k: int,
    threshold: float,
) -> list[dict]:
    rrf_scores: dict[int, float] = {}
    dense_score_map: dict[int, float] = {}

    for rank, (idx, score) in enumerate(dense_ranked):
        rrf_scores[idx] = rrf_scores.get(idx, 0.0) + W_DENSE / (RRF_K + rank + 1)
        dense_score_map[idx] = score

    for rank, (idx, _) in enumerate(bm25_ranked):
        rrf_scores[idx] = rrf_scores.get(idx, 0.0) + W_BM25 / (RRF_K + rank + 1)

    sorted_idx = sorted(rrf_scores, key=lambda i: rrf_scores[i], reverse=True)

    results = []
    for idx in sorted_idx:
        dense_score = dense_score_map.get(idx, 0.0)
        # Dense score가 없거나 threshold 미만이면 제외
        if dense_score < threshold:
            continue
        results.append(_meta_to_result(meta[idx], dense_score))
        if len(results) >= top_k:
            break

    return results


# ─────────────────────────────────────────
# 2-A: knowledge_chunks 하이브리드 검색 (동기, executor에서 실행)
# ─────────────────────────────────────────
def _search_2a_sync(
    query: str,
    query_vec: np.ndarray,
    top_k: int,
) -> list[dict]:
    vecs = _all_vecs
    meta = _all_meta

    dense_ranked = _cosine_search(query_vec, vecs, DENSE_TOP)
    bm25_ranked  = _bm25_search(query, BM25_TOP)

    rrf_top = RERANK_POOL if (USE_RERANK and _CE_AVAILABLE) else top_k
    rrf_results = _rrf_merge(dense_ranked, bm25_ranked, meta, rrf_top, SIMILARITY_THRESHOLD)

    if USE_RERANK and _CE_AVAILABLE and rrf_results:
        try:
            top1_kt = rrf_results[0].get("knowledge_type", "")
            if top1_kt == "system_manual":
                return rrf_results[:top_k]
            return _rerank(query, rrf_results, top_k)
        except Exception as e:
            print(f"[Rerank 오류] {e}")
            return rrf_results[:top_k]

    return rrf_results[:top_k]


# ─────────────────────────────────────────
# 공개 인터페이스
# ─────────────────────────────────────────
async def retrieve_all(
    query: str,
    is_oos: bool,
    disease_name: str | None = None,
    query_vec: np.ndarray | None = None,
    top_k: int = TOP_K,
    knowledge_type: str | None = None,
) -> dict:
    """
    하이브리드 RAG 검색 (2-A).
    2-B/2-C는 ws.py에서 step2_search.py를 통해 DB 직접 조회.

    반환:
    {
        "step2a": [{chunk_id, chunk_text, knowledge_type, disease_name,
                    document_title, section_title, data_id, similarity}],
        "step2b": [],
        "step2c": [],
        "_disease_filter": str | None,
    }
    """
    if query_vec is None:
        query_vec = await embed_query(query)

    if is_oos:
        return {
            "step2a":          [],
            "step2b":          [],
            "step2c":          [],
            "_disease_filter": None,
        }

    # 청크 로드 보장 (최초 1회 DB 로드)
    await _ensure_chunks_loaded()

    loop = asyncio.get_event_loop()
    step2a = await loop.run_in_executor(
        None, _search_2a_sync, query, query_vec, top_k
    )

    normalized = _normalize_disease_name(disease_name)

    return {
        "step2a":          step2a,
        "step2b":          [],
        "step2c":          [],
        "_disease_filter": normalized if normalized else None,
    }

"""
RAG 검색 파이프라인 (pgvector 버전)
refined_query + category → knowledge_chunks 검색 → top-k 결과 반환

카테고리:
  감염병 → source_category='disease' (disease_name 프리필터 + FAQ 병합)
  시스템 → source_category='system'
  범위외 → 검색 없음

검색 방식 (Hybrid):
  1. 코사인 유사도 (pgvector, 인덱스 가속)
  2. 키워드 오버랩 (인메모리)
  3. RRF(Reciprocal Rank Fusion) 재랭킹
"""
import re
import numpy as np
from app.core.database import get_pool

TOP_K = 5
RRF_K = 60
CANDIDATE_K = 30  # pgvector 1차 후보 수 (RRF 재랭킹용)

DISEASE_ALIASES: dict[str, list[str]] = {
    "에이즈":          ["HIV/AIDS", "후천성면역결핍증(AIDS)"],
    "AIDS":            ["HIV/AIDS", "후천성면역결핍증(AIDS)"],
    "후천성면역결핍증": ["HIV/AIDS", "후천성면역결핍증(AIDS)"],
    "코로나":          ["코로나19", "코로나바이러스감염증-19"],
    "코로나바이러스":  ["코로나19", "코로나바이러스감염증-19"],
    "COVID":           ["코로나19", "코로나바이러스감염증-19"],
    "메르스":          ["중동호흡기증후군"],
    "MERS":            ["중동호흡기증후군"],
    "폐결핵":          ["결핵"],
    "결핵균":          ["결핵"],
    "에볼라":          ["에볼라바이러스병"],
    "마버그":          ["마버그열"],
    "천연두":          ["두창"],
    "흑사병":          ["페스트"],
    "탄저균":          ["탄저"],
    "노로":            ["노로바이러스 감염증"],
    "SFTS":            ["중증열성혈소판감소증후군"],
    "쯔쯔가무시":      ["쯔쯔가무시증"],
}


def _vec_str(vec) -> str:
    if isinstance(vec, np.ndarray):
        vec = vec.tolist()
    return "[" + ",".join(map(str, vec)) + "]"


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r'[가-힣a-zA-Z0-9]+', text)
    return {t for t in tokens if len(t) >= 2}


def _rrf_rerank(rows: list[dict], query: str, k: int = TOP_K) -> list[dict]:
    """코사인 순위 + 키워드 순위 → RRF 재랭킹"""
    n = len(rows)
    if n == 0:
        return []

    cos_scores = np.array([r["cos_score"] for r in rows], dtype=np.float32)
    q_tokens = _tokenize(query)
    kw_scores = np.zeros(n, dtype=np.float32)
    if q_tokens:
        for i, r in enumerate(rows):
            c_tokens = _tokenize(r.get("embed_text") or r.get("chunk_text", ""))
            kw_scores[i] = len(q_tokens & c_tokens) / len(q_tokens)

    cos_rank_of = np.empty(n, dtype=int)
    kw_rank_of = np.empty(n, dtype=int)
    cos_rank_of[np.argsort(cos_scores)[::-1]] = np.arange(n)
    kw_rank_of[np.argsort(kw_scores)[::-1]] = np.arange(n)

    rrf = 1.0 / (RRF_K + cos_rank_of + 1) + 1.0 / (RRF_K + kw_rank_of + 1)
    top_idx = np.argsort(rrf)[::-1][:k]

    return [
        {**rows[i], "score": float(rrf[i]), "kw_score": float(kw_scores[i])}
        for i in top_idx
    ]


def _merge_rrf(result_lists: list[list[dict]], k: int = TOP_K) -> list[dict]:
    """여러 결과 리스트를 source_id 기준으로 RRF 병합"""
    scores: dict = {}
    items: dict = {}
    for results in result_lists:
        for rank, item in enumerate(results, 1):
            sid = item.get("source_id", id(item))
            scores[sid] = scores.get(sid, 0.0) + 1.0 / (RRF_K + rank)
            items.setdefault(sid, item)
    top = sorted(scores.items(), key=lambda x: -x[1])[:k]
    return [{**items[sid], "score": score} for sid, score in top]


def _extract_disease(query: str, rows: list[dict]) -> str | None:
    disease_count: dict[str, int] = {}
    for r in rows:
        d = r.get("disease_name", "")
        if d:
            disease_count[d] = disease_count.get(d, 0) + 1

    diseases = set(disease_count.keys())
    matched = []

    for disease in diseases:
        if disease in query:
            matched.append(disease)
            continue
        for token in query.split():
            if len(token) >= 3 and disease.startswith(token):
                matched.append(disease)
                break

    for alias, canonicals in DISEASE_ALIASES.items():
        if alias in query:
            candidates = [c for c in canonicals if c in diseases]
            if candidates:
                best = max(candidates, key=lambda d: disease_count.get(d, 0))
                matched.append(best)

    if not matched:
        return None
    return max(set(matched), key=lambda d: disease_count.get(d, 0))


async def retrieve_knowledge(
    query_vec,
    query: str,
    category: str,
    top_k: int = TOP_K,
) -> dict:
    """
    pgvector 기반 Hybrid RAG 검색.
    query_vec: llm_session에서 이미 생성된 임베딩 벡터 (재사용)

    반환:
    {
        "results": list[dict],        # card_generator.generate_card()에 전달
        "_category": str,
        "_disease_filter": str | None,
    }
    """
    if category == "범위외":
        return {"results": [], "_category": "범위외", "_disease_filter": None}

    pool = await get_pool()
    vec_str = _vec_str(query_vec)

    if category == "감염병":
        rows = await pool.fetch(
            """
            SELECT source_id, data_id, knowledge_type, disease_name,
                   document_title, section_title, chunk_text, embed_text,
                   1 - (embedding <=> $1::vector) AS cos_score
            FROM knowledge_chunks
            WHERE source_category = 'disease'
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            vec_str, CANDIDATE_K,
        )
        rows = [dict(r) for r in rows]

        disease = _extract_disease(query, rows)

        if disease:
            filtered = [r for r in rows if r.get("disease_name") == disease]
            results = _rrf_rerank(filtered, query, k=top_k)
            return {"results": results, "_category": "감염병", "_disease_filter": disease}
        else:
            # 병명 없음 → disease_info + faq 각각 RRF 후 병합
            di_results = _rrf_rerank(
                [r for r in rows if r.get("knowledge_type") == "disease_info"], query, k=top_k
            )
            faq_results = _rrf_rerank(
                [r for r in rows if r.get("knowledge_type") == "faq"], query, k=top_k
            )
            results = _merge_rrf([di_results, faq_results], k=top_k)
            return {"results": results, "_category": "감염병", "_disease_filter": None}

    else:  # 시스템
        rows = await pool.fetch(
            """
            SELECT source_id, data_id, knowledge_type, disease_name,
                   document_title, section_title, chunk_text, embed_text,
                   1 - (embedding <=> $1::vector) AS cos_score
            FROM knowledge_chunks
            WHERE source_category = 'system'
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            vec_str, CANDIDATE_K,
        )
        rows = [dict(r) for r in rows]
        results = _rrf_rerank(rows, query, k=top_k)
        return {"results": results, "_category": "시스템", "_disease_filter": None}

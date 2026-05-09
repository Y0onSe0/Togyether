"""
RAG 검색 파이프라인 (pgvector 버전 v2)
refined_query + category → knowledge_chunks 검색 → top-k 결과 반환

카테고리:
  감염병   → source_category='disease' (disease_name 메타데이터 필터)
  접수처리 → source_category='system'
  범위외   → 검색 없음

검색 방식:
  메타데이터 필터링 (disease_name, LLM 추출) + 코사인 유사도 (pgvector)

변경사항 (v2):
  - disease_name 추출을 문자열 매칭 → LLM 출력 파라미터로 이관
  - RRF/키워드 오버랩 제거, 코사인 단독 검색으로 단순화
  - DISEASE_ALIASES / _extract_disease() 제거
  - 카테고리명: 시스템 → 접수처리
"""
import numpy as np
from app.core.database import get_pool

TOP_K = 5
CANDIDATE_K = 30  # pgvector 1차 후보 수


def _vec_str(vec) -> str:
    if isinstance(vec, np.ndarray):
        vec = vec.tolist()
    return "[" + ",".join(map(str, vec)) + "]"


async def _validate_disease(disease_name: str | None, pool) -> str | None:
    """LLM이 반환한 disease_name이 실제 DB에 존재하는지 확인."""
    if not disease_name:
        return None
    row = await pool.fetchrow(
        "SELECT disease_name FROM knowledge_chunks WHERE disease_name = $1 LIMIT 1",
        disease_name,
    )
    return disease_name if row else None


async def retrieve_knowledge(
    query_vec,
    query: str,
    category: str,
    disease_name: str | None = None,
    top_k: int = TOP_K,
) -> dict:
    """
    pgvector 기반 코사인 유사도 검색.
    query_vec: llm_session에서 이미 생성된 임베딩 벡터 (재사용)
    disease_name: llm_session LLM이 추출한 공식 병명 (없으면 None)

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
        disease = await _validate_disease(disease_name, pool)

        if disease:
            # 병명 있음 → 해당 병명 청크만 코사인 검색
            rows = await pool.fetch(
                """
                SELECT source_id, data_id, knowledge_type, disease_name,
                       document_title, section_title, chunk_text, embed_text,
                       1 - (embedding <=> $1::vector) AS cos_score
                FROM knowledge_chunks
                WHERE source_category = 'disease'
                  AND disease_name = $2
                ORDER BY embedding <=> $1::vector
                LIMIT $3
                """,
                vec_str, disease, top_k,
            )
        else:
            # 병명 없음 → 전체 disease 청크 코사인 검색
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
                vec_str, top_k,
            )

        results = [dict(r) for r in rows]
        # score 필드 통일 (cos_score와 동일)
        for r in results:
            r["score"] = r["cos_score"]

        return {
            "results":         results,
            "_category":       "감염병",
            "_disease_filter": disease,
        }

    else:  # 접수처리
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
            vec_str, top_k,
        )
        results = [dict(r) for r in rows]
        for r in results:
            r["score"] = r["cos_score"]

        return {
            "results":         results,
            "_category":       "접수처리",
            "_disease_filter": None,
        }

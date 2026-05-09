"""
STEP 2: 병렬 pgvector 검색
2A: knowledge_chunks (disease_name 프리필터, is_oos=false 시만)
2B: acw_cards (q_embedding, 항상)
2C: transfer_agencies (description_embedding, 항상)
"""
import asyncio
from openai import AsyncOpenAI
from app.core.config import settings
from app.core.database import get_pool

_client: AsyncOpenAI | None = None
SIMILARITY_THRESHOLD = 0.70
TOP_K = 3


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def _embed(text: str) -> list[float]:
    client = _get_client()
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding


def _vec_str(vec: list[float]) -> str:
    return "[" + ",".join(map(str, vec)) + "]"


async def _search_knowledge(pool, query_vec: list[float], disease_name: str | None) -> list[dict]:
    disease_filter = "AND disease_name = $3" if disease_name else ""
    params = [_vec_str(query_vec), SIMILARITY_THRESHOLD]
    if disease_name:
        params.append(disease_name)

    rows = await pool.fetch(
        f"""
        SELECT chunk_id, document_title, section_title, data_id, chunk_text,
               1 - (embedding <=> $1::vector) AS similarity
        FROM knowledge_chunks
        WHERE 1 - (embedding <=> $1::vector) >= $2
          {disease_filter}
        ORDER BY embedding <=> $1::vector
        LIMIT {TOP_K}
        """,
        *params,
    )
    return [dict(r) for r in rows]


async def _search_acw(pool, query_vec: list[float]) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT acw_id, title, qa_summary,
               1 - (q_embedding <=> $1::vector) AS similarity
        FROM acw_cards
        WHERE q_embedding IS NOT NULL
          AND 1 - (q_embedding <=> $1::vector) >= $2
        ORDER BY q_embedding <=> $1::vector
        LIMIT $3
        """,
        _vec_str(query_vec), SIMILARITY_THRESHOLD, TOP_K,
    )
    result = []
    for r in rows:
        qa = r["qa_summary"] or []
        result.append({
            "acw_id": r["acw_id"],
            "title": r["title"],
            "similarity": float(r["similarity"]),
            "qa_summary": qa,
        })
    return result


async def _search_transfer(pool, query_vec: list[float]) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT org_name, dept_name, phone, description_summary,
               1 - (description_embedding <=> $1::vector) AS similarity
        FROM transfer_agencies
        WHERE description_embedding IS NOT NULL
          AND 1 - (description_embedding <=> $1::vector) >= $2
        ORDER BY description_embedding <=> $1::vector
        LIMIT $3
        """,
        _vec_str(query_vec), SIMILARITY_THRESHOLD, TOP_K,
    )
    return [{
        "org_name": r["org_name"],
        "dept_name": r["dept_name"],
        "phone": r["phone"],
        "description_summary": r["description_summary"],
        "similarity": float(r["similarity"]),
    } for r in rows]


async def run_step2(query: str, disease_name: str | None, call_id: int) -> dict:
    pool = await get_pool()
    query_vec = await _embed(query)

    results = await asyncio.gather(
        _search_knowledge(pool, query_vec, disease_name),
        _search_acw(pool, query_vec),
        _search_transfer(pool, query_vec),
        return_exceptions=True,
    )

    knowledge = results[0] if not isinstance(results[0], Exception) else []
    similar = results[1] if not isinstance(results[1], Exception) else []
    transfer = results[2] if not isinstance(results[2], Exception) else []

    return {
        "knowledge_chunks": knowledge,
        "similar_cases": similar,
        "transfer_suggestions": transfer,
    }

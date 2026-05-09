"""
STEP 3: AI 안내 생성
knowledge_chunks + conversation_history → answer (1~3문장) + sources
"""
import json
from openai import AsyncOpenAI
from app.core.config import settings

_client: AsyncOpenAI | None = None

SYSTEM_PROMPT = """당신은 질병관리청 1339 콜센터 AI 안내 어시스턴트입니다.
제공된 참고 문서를 바탕으로 상담사에게 간결한 안내문을 생성하세요.
- 1~3문장으로 핵심 정보만 전달
- 문서에 없는 내용은 추측하지 마세요
- 친절하고 명확한 한국어로 작성"""


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def run_step3(
    query: str,
    disease_name: str | None,
    knowledge_chunks: list[dict],
    conversation_history: list[dict],
) -> tuple[str, list[dict]]:
    client = _get_client()

    chunks_text = "\n\n".join(
        f"[{i+1}] {c.get('document_title','')} / {c.get('section_title','')}\n{c.get('chunk_text','')}"
        for i, c in enumerate(knowledge_chunks)
    )
    history_text = "\n".join(
        f"{t['speaker']}: {t['text']}" for t in conversation_history[-6:]
    )

    user_content = f"[질문]\n{query}\n\n[대화 내역]\n{history_text}\n\n[참고 문서]\n{chunks_text}"

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
        max_tokens=300,
    )

    answer = response.choices[0].message.content.strip()

    sources = [
        {
            "chunk_id": c.get("chunk_id"),
            "document_title": c.get("document_title", ""),
            "section_title": c.get("section_title", ""),
            "data_id": c.get("data_id", ""),
            "chunk_text": c.get("chunk_text", ""),
        }
        for c in knowledge_chunks
    ]

    return answer, sources

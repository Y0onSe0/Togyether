"""
STEP 1: LLM 통합 판정
conversation_history → ready / is_oos / disease_name / query
"""
import json
from openai import AsyncOpenAI
from app.core.config import settings

_client: AsyncOpenAI | None = None

SYSTEM_PROMPT = """당신은 질병관리청 1339 콜센터 AI입니다.
대화 내역을 분석하여 아래 JSON을 반환하세요.

{
  "ready": true/false,         // 질문 파악이 충분한지
  "is_oos": true/false,        // 업무 범위 외 여부
  "oos_type": "unrelated"|"action_required"|null,
  "oos_reason": "string|null", // is_oos=true 시 사유 (1문장)
  "disease_name": "string|null", // 관련 질병명
  "query": "string|null"       // 검색할 핵심 질문 (ready=true 시)
}

ready=false: 아직 질문이 명확하지 않음 (인사/짧은 발화)
is_oos=true: 보험, 법률, 타기관 업무 등 1339 범위 외"""


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def run_step1(conversation_history: list[dict]) -> dict:
    client = _get_client()

    history_text = "\n".join(
        f"{t['speaker']}: {t['text']}" for t in conversation_history[-8:]
    )

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"[대화 내역]\n{history_text}"},
        ],
        temperature=0.1,
    )

    return json.loads(response.choices[0].message.content)

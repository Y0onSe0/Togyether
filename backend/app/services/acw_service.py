"""
ACW 서비스
- generate_acw_fields: gpt-4o-mini JSON mode로 ACW 필드 자동 생성
- embed_text: q_embedding 생성 (text-embedding-3-small)
"""
import json
from openai import AsyncOpenAI
from app.core.config import settings
from app.schemas.acw import AcwGenerateResponse, QaSummaryItem

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


GENERATE_SYSTEM = """당신은 질병관리청 1339 콜센터 상담 후처리 전문가입니다.
상담 전문(transcript)과 AI 안내(ai_guidance)를 바탕으로 ACW 카드 필드를 JSON으로 생성하세요.

반환 JSON 필드:
- title: 상담 제목 (한 줄 요약)
- customer_type: "citizen" | "medical_staff" | "public_health" | "other"
- customer_type_custom: customer_type이 "other"일 때만 기입, 아니면 null
- category: "감염병" | "예방접종" | "접수처리" | "범위외"
- category_major: 대분류 (예: "코로나19", "인플루엔자")
- category_mid: 주요 중분류 1개
- category_mid_list: 중분류 목록 (배열)
- category_mid_custom: category가 "범위외"일 때 상세 내용, 아니면 null
- disease_name: 주요 질병명 (없으면 null)
- qa_summary: [{"q": "고객 핵심 질문", "a": "상담사 핵심 답변"}] 배열
- ai_response_summary: 상담 대화 전문([상담 전문] 섹션)만을 기반으로 작성한 단일 서술형 단락. 반드시 "고객 문의 → 상담사 안내 → 처리 결과" 순서로 3~4문장으로 요약. AI 안내 내용은 참고하지 말고 오직 대화 내용만 반영할 것.
- is_transferred: 이관 여부 (true/false)
- transfer_target: 이관 대상 기관명 (없으면 null)
- keywords: 핵심 키워드 배열 (최대 5개)"""


async def generate_acw_fields(
    transcript: str | None,
    ai_guidance: dict | None,
) -> AcwGenerateResponse:
    client = _get_client()

    user_content = f"[상담 전문]\n{transcript or '(없음)'}\n\n[AI 안내]\n{json.dumps(ai_guidance, ensure_ascii=False) if ai_guidance else '(없음)'}"

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": GENERATE_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )

    raw = json.loads(response.choices[0].message.content)

    qa_raw = raw.get("qa_summary", [])
    qa = [QaSummaryItem(q=item["q"], a=item["a"]) for item in qa_raw if "q" in item and "a" in item]

    return AcwGenerateResponse(
        title=raw.get("title"),
        customer_type=raw.get("customer_type"),
        customer_type_custom=raw.get("customer_type_custom"),
        category=raw.get("category"),
        category_major=raw.get("category_major"),
        category_mid=raw.get("category_mid"),
        category_mid_list=raw.get("category_mid_list", []),
        category_mid_custom=raw.get("category_mid_custom"),
        disease_name=raw.get("disease_name"),
        qa_summary=qa,
        ai_response_summary=raw.get("ai_response_summary"),
        is_transferred=raw.get("is_transferred", False),
        transfer_target=raw.get("transfer_target"),
        keywords=raw.get("keywords", []),
    )


async def embed_text(text: str) -> list[float]:
    client = _get_client()
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding

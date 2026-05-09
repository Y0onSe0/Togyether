"""
STEP 3: 카드 생성기
retrieval 결과 → 상담사 카드 JSON

카테고리: 감염병 | 접수처리 | 범위외
"""
import json
from openai import AsyncOpenAI
from app.core.config import settings

_client: AsyncOpenAI | None = None

KNOWLEDGE_SCORE_THRESHOLD = 0.40

EMERGENCY_KEYWORDS = [
    "경련", "의식 잃", "의식을 잃", "의식이 없", "의식없", "의식불명",
    "심정지", "심폐소생", "쓰러", "실신",
    "호흡곤란", "숨을 못", "숨쉬기 힘", "숨이 안", "흉통",
    "가슴 통증", "가슴이 아파", "가슴이 너무 아파",
    "다량 출혈", "피가 안 멈", "피가 너무", "출혈이 심",
    "응급", "위급", "생명이 위험", "119",
]

RAG_SYSTEM = """당신은 질병관리청 콜센터 상담사 보조 AI입니다.
고객 문의와 아래 [문서]를 바탕으로 상담사가 전화 통화 중 바로 읽을 수 있는 카드를 만드세요.

반드시 아래 JSON 형식으로만 출력하세요:
{
  "intent": "고객 의도 — 병명·주제·행위를 포함한 10자 이내 명사구 (예: '레지오넬라 감염 경로 문의')",
  "answer": "핵심 답변 1~2문장. 기간·수치·절차 등 구체적 정보가 있으면 반드시 포함."
}

규칙:
- answer는 반드시 아래 [문서]에 명시된 내용에만 근거할 것
- [문서]에 없는 수치·날짜·기관명·절차는 절대 생성하지 말 것
- [문서]에 명확한 답이 없으면 반드시: "관련 지침에서 명확한 내용을 찾지 못했습니다."
- 말투: 상담사가 고객에게 직접 말하는 구어체 ('~입니다', '~하시면 됩니다')
- 지침 원문을 그대로 붙여넣지 말고, 핵심만 쉽게 재서술할 것
- '병원 방문 권유', '진료 받으세요', '전문의 상담' 등 일반 의학 조언은 절대 추가하지 말 것"""


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _is_emergency(query: str) -> bool:
    return any(kw in query for kw in EMERGENCY_KEYWORDS)


def _chunk_label(c: dict) -> str:
    disease = c.get("disease_name", "")
    section = c.get("section_title") or c.get("section") or c.get("title", "")
    if disease and section:
        return f"{disease} / {section}"
    return disease or section or ""


def _extract_references(chunks: list) -> list[dict]:
    return [
        {
            "source_id":      c.get("source_id", ""),
            "knowledge_type": c.get("knowledge_type", ""),
            "disease":        c.get("disease_name", ""),
            "section":        c.get("section_title") or c.get("section", ""),
            "chunk_text":     c.get("chunk_text", "")[:300],
            "score":          round(c.get("score", 0), 4),
        }
        for c in chunks
    ]


async def generate_card(refined_query: str, category: str, retrieval: dict) -> dict:
    """
    retrieval(retrieve_knowledge() 반환값) → 상담사 카드 dict

    반환 필드:
      category, intent, answer, references, _disease_filter, [emergency]
    """
    results = retrieval.get("results", [])
    disease_filter = retrieval.get("_disease_filter")
    is_emergency = _is_emergency(refined_query)

    if category == "범위외":
        card = {
            "category":       "범위외",
            "intent":         refined_query,
            "answer":         "질병관리청 소관 외 문의입니다.",
            "references":     [],
            "_disease_filter": None,
        }
        if is_emergency:
            card["emergency"] = True
        return card

    top_cos = max((c.get("cos_score", 0) for c in results), default=0)
    if not results or top_cos < KNOWLEDGE_SCORE_THRESHOLD:
        card = {
            "category":       category,
            "intent":         refined_query,
            "answer":         "관련 지침에서 명확한 내용을 찾지 못했습니다.",
            "references":     _extract_references(results[:3]),
            "_disease_filter": disease_filter,
        }
        if is_emergency:
            card["emergency"] = True
        return card

    top_chunks = results[:3]
    chunks_text = "\n\n".join(
        f"[{_chunk_label(c)}]\n{c.get('chunk_text', '')[:500]}"
        for c in top_chunks
    )
    user_msg = f"고객 문의: {refined_query}\n\n[문서]\n{chunks_text}"

    resp = await _get_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": RAG_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0,
        max_tokens=200,
        response_format={"type": "json_object"},
    )
    llm = json.loads(resp.choices[0].message.content)

    FALLBACK = "관련 지침에서 명확한 내용을 찾지 못했습니다."
    raw_answer = llm.get("answer", FALLBACK)
    answer = FALLBACK if FALLBACK in raw_answer else raw_answer

    card = {
        "category":        category,
        "intent":          llm.get("intent", refined_query),
        "answer":          answer,
        "references":      _extract_references(top_chunks),
        "_disease_filter": disease_filter,
    }
    if is_emergency:
        card["emergency"] = True
    return card

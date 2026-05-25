"""
카드 생성기 v3 — retrieve_all() 결과 → ai_guidance dict

변경사항 (v3):
  - 입력: query, is_oos, oos_type, oos_reason, disease_name, retrieval (retrieve_all 반환값)
  - 임계값 제거 (retrieve_all에서 cosine ≥ 0.70 필터 완료)
  - 출력 status: success | oos | no_result (RTL-UI-001)
  - sources 필드: chunk_id, document_title, section_title, data_id, chunk_text

출력 (ai_guidance 캐시 구조):
  success:   {status, query, disease_name, answer, sources[{chunk_id, document_title, section_title, data_id, chunk_text}]}
  oos:       {status, oos_type, oos_reason}
  no_result: {status, query}
"""

import json
from openai import AsyncOpenAI
from app.core.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


# ── 응급 감지 ──────────────────────────────────────────────────
EMERGENCY_KEYWORDS = [
    "경련", "의식 잃", "의식을 잃", "의식이 없", "의식없", "의식불명",
    "심정지", "심폐소생", "쓰러", "실신",
    "호흡곤란", "숨을 못", "숨쉬기 힘", "숨이 안", "흉통",
    "가슴 통증", "가슴이 아파", "가슴이 너무 아파",
    "다량 출혈", "피가 안 멈", "피가 너무", "출혈이 심",
    "응급", "위급", "생명이 위험", "119",
]


def _is_emergency(query: str) -> bool:
    return any(kw in query for kw in EMERGENCY_KEYWORDS)


# ── RAG LLM 프롬프트 ───────────────────────────────────────────
RAG_SYSTEM = """당신은 질병관리청 콜센터 상담사 보조 AI입니다.
고객 문의와 아래 [문서]를 바탕으로 상담사가 전화 통화 중 바로 읽을 수 있는 카드를 만드세요.

반드시 아래 JSON 형식으로만 출력하세요:
{
  "intent": "고객 의도 — 병명·주제·행위를 포함한 10자 이내 명사구 (예: '레지오넬라 감염 경로 문의')",
  "answer": "핵심 답변 1~2문장. 기간·수치·절차 등 구체적 정보가 있으면 반드시 포함."
}

규칙:
- answer는 [문서]에 명시된 내용을 최우선으로 사용할 것
- [문서] 내용이 질문에 직접 답하지 않더라도, 관련 정보(잠복기·증상·조치 등)가 있으면 그것을 바탕으로 유용한 정보를 제공할 것
- [문서]에 전혀 관련 내용이 없을 때만: "관련 지침에서 명확한 내용을 찾지 못했습니다."
- [문서]에 없는 구체적 수치·날짜·기관명을 새로 만들어내지 말 것 (문서에 있는 수치는 그대로 활용)
- 말투: 상담사가 고객에게 직접 말하는 구어체 ('~입니다', '~하시면 됩니다')
- 지침 원문을 그대로 붙여넣지 말고, 핵심만 쉽게 재서술할 것
- '병원 방문 권유', '진료 받으세요', '전문의 상담' 등 일반 의학 조언은 절대 추가하지 말 것"""


# ── 헬퍼 ──────────────────────────────────────────────────────
def _chunk_label(c: dict) -> str:
    disease = c.get("disease_name", "")
    section = c.get("section_title", "")
    if disease and section:
        return f"{disease} / {section}"
    return disease or section or c.get("document_title", "")


def _make_source(c: dict) -> dict:
    return {
        "chunk_id":       c.get("chunk_id", ""),
        "document_title": c.get("document_title", ""),
        "section_title":  c.get("section_title", ""),
        "data_id":        c.get("data_id", ""),
        "chunk_text":     c.get("chunk_text", "")[:300],
    }


async def _call_llm(system: str, user: str, max_tokens: int = 200) -> dict:
    resp = await _get_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=0,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


# ── 메인 ──────────────────────────────────────────────────────
async def generate_card(
    query: str,
    is_oos: bool,
    oos_type: str | None,
    oos_reason: str | None,
    disease_name: str | None,
    retrieval: dict,
) -> dict:
    """
    retrieve_all() 결과 → ai_guidance dict (RTL-UI-001)

    파라미터:
      query        — STEP 1 정제 쿼리
      is_oos       — STEP 1 출력
      oos_type     — "action_required" | "unrelated" | None
      oos_reason   — OOS 사유 (is_oos=true 시)
      disease_name — STEP 1 출력, nullable
      retrieval    — retrieve_all() 반환값

    반환 (status별):
      success:   {status, query, disease_name, answer, sources, [emergency]}
      oos:       {status, oos_type, oos_reason, [emergency]}
      no_result: {status, query, [emergency]}
    """
    is_emergency = _is_emergency(query)

    # ── OOS 처리 (2-A 미실행) ──────────────────────────────────
    if is_oos:
        card = {
            "status":     "oos",
            "oos_type":   oos_type,
            "oos_reason": oos_reason,
        }
        if is_emergency:
            card["emergency"] = True
        return card

    # ── 2-A 결과 확인 (threshold는 retrieve_all에서 처리됨) ──────
    step2a = retrieval.get("step2a", [])

    if not step2a:
        card = {
            "status": "no_result",
            "query":  query,
        }
        if is_emergency:
            card["emergency"] = True
        return card

    # ── LLM 카드 생성 (2-A 상위 5개 → 상위 3개 청크 사용) ────────────────
    top_chunks = step2a[:3]
    chunks_text = "\n\n".join(
        f"[{_chunk_label(c)}]\n{c.get('chunk_text', '')[:800]}"   # 500→800 chars
        for c in top_chunks
    )
    user_msg = f"고객 문의: {query}\n\n[문서]\n{chunks_text}"
    llm = await _call_llm(RAG_SYSTEM, user_msg, max_tokens=300)   # 200→300 tokens

    FALLBACK = "관련 지침에서 명확한 내용을 찾지 못했습니다."
    raw_answer = (llm.get("answer") or "").strip()
    # 빈 답변 또는 fallback 문구 그 자체일 때만 fallback 처리
    answer = raw_answer if raw_answer and raw_answer != FALLBACK else FALLBACK

    card = {
        "status":       "success",
        "query":        query,
        "disease_name": disease_name,
        "answer":       answer,
        "sources":      [_make_source(c) for c in top_chunks],
    }
    if is_emergency:
        card["emergency"] = True
    return card

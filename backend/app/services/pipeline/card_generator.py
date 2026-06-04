"""
카드 생성기 v6 — retrieve_all() 결과 → ai_guidance dict

변경사항 (v6):
- 유사도 임계값 수정
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

# api_pending 분기 대상 카테고리
API_PENDING_CATEGORIES = {"예방접종", "감염병 통계·현황", "해외/검역 정보 문의"}


def _is_emergency(query: str) -> bool:
    return any(kw in query for kw in EMERGENCY_KEYWORDS)


# ── RAG LLM 프롬프트 ───────────────────────────────────────────
RAG_SYSTEM = """당신은 질병관리청 콜센터 상담사 보조 AI입니다.
고객 문의와 아래 [문서]를 바탕으로 상담사가 전화 통화 중 바로 읽을 수 있는 카드를 만드세요.

반드시 아래 JSON 형식으로만 출력하세요:
{
  "intent": "고객 의도 — 병명·주제·행위를 포함한 10자 이내 명사구 (예: '레지오넬라 감염 경로 문의')",
  "answer": "핵심 답변 1~2문장. [문서]에 기간·수치·날짜·퍼센트·횟수 등 구체적 숫자가 있으면 반드시 그대로 포함."
}

규칙:
- answer는 반드시 아래 [문서]에 명시된 내용에만 근거할 것
- [문서]에 없는 수치·날짜·기관명·절차는 절대 생성하지 말 것
- **[문서]에 수치·기간·날짜가 있으면 반드시 answer에 포함** (생략 금지)
  예) 격리 기간이 "5일"이면 → "5일간 격리하셔야 합니다" (숫자 명시)
      항체 형성 기간이 "2주"이면 → "접종 후 약 2주 후 항체가 형성됩니다" (숫자 명시)
      치료율이 "70~90%"이면 → "치료율은 70~90%입니다" (범위 그대로)
- [문서]에 명확한 답이 없으면 반드시: "관련 지침에서 명확한 내용을 찾지 못했습니다."
- 말투: 상담사가 고객에게 직접 말하는 구어체 ('~입니다', '~하시면 됩니다')
- 지침 원문을 그대로 붙여넣지 말고, 핵심만 쉽게 재서술할 것
- '병원 방문 권유', '진료 받으세요', '전문의 상담' 등 일반 의학 조언은 절대 추가하지 말 것
- 아래 문구는 절대 사용 금지 (여기가 질병관리청 콜센터이므로 의미 없음):
  "질병관리청에 문의하시면", "질병관리청으로 문의", "질병관리청 홈페이지 참고",
  "관련 기관에 문의", "담당 기관에 문의", "자세한 사항은 ~에 문의"
  위 표현이 나오면 해당 문장을 통째로 삭제하고 핵심 답변만 남길 것"""


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
        "disease_name":   c.get("disease_name", ""),
        "section_title":  c.get("section_title", ""),
        "data_id":        c.get("data_id", ""),
        "chunk_text":     c.get("chunk_text", "")[:300],
    }


async def _call_llm(system: str, user: str, max_tokens: int = 300) -> dict:
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
    category: str | None = None,
) -> dict:
    """
    retrieve_all() 결과 → ai_guidance dict

    파라미터:
      query        — STEP 1 정제 쿼리
      is_oos       — STEP 1 출력
      oos_type     — "action_required" | "realtime_local" | "transfer" | "unrelated" | None
      oos_reason   — OOS 사유 (is_oos=true 시)
      disease_name — STEP 1 출력, nullable
      retrieval    — retrieve_all() 반환값
      category     — llm_session 매핑 카테고리 (api_pending 분기용)

    반환 (status별):
      success:     {status, query, disease_name, intent, answer, sources, [emergency]}
      api_pending: {status, category, query, [emergency]}
      oos:         {status, oos_type, oos_reason, [emergency]}
      no_result:   {status, query, [emergency]}
    """
    is_emergency = _is_emergency(query)

    # ── API 예정 카테고리 처리 ─────────────────────────────────
    if category in API_PENDING_CATEGORIES:
        card = {
            "status":   "api_pending",
            "category": category,
            "query":    query,
        }
        if is_emergency:
            card["emergency"] = True
        return card

    # ── OOS 처리 ──────────────────────────────────────────────
    if is_oos:
        card = {
            "status":     "oos",
            "oos_type":   oos_type,
            "oos_reason": oos_reason,
        }
        if is_emergency:
            card["emergency"] = True
        return card

    # ── disease_name 없으면 전체 검색 대신 병명 확인 요청 ────────
    if not disease_name:
        card = {
            "status":  "no_result",
            "query":   query,
            "message": "고객에게 정확한 감염병명을 확인해 주세요. 병명을 알면 관련 지침을 안내해드릴 수 있습니다.",
        }
        if is_emergency:
            card["emergency"] = True
        return card

    # ── 2-A 결과 확인 ──────────────────────────────────────────
    step2a = retrieval.get("step2a", [])

    if not step2a:
        card = {
            "status": "no_result",
            "query":  query,
        }
        if is_emergency:
            card["emergency"] = True
        return card

    # ── 유사도 임계값 체크 (top-5 중 최대 similarity ≤ 0.5 → no_result) ──
    # step2a는 RRF 점수 기준 정렬 → top-1이 BM25에 의해 낮은 유사도일 수 있음
    SIMILARITY_THRESHOLD = 0.45
    top_sim = max((c.get("similarity", 0.0) for c in step2a[:5]), default=0.0)
    if top_sim <= SIMILARITY_THRESHOLD:
        card = {
            "status":  "no_result",
            "query":   query,
            "message": "관련 지침을 찾지 못했습니다.",
        }
        if is_emergency:
            card["emergency"] = True
        return card

    # ── LLM 카드 생성 ──────────────────────────────────────────
    top_chunks = step2a[:5]
    chunks_text = "\n\n".join(
        f"[{_chunk_label(c)}]\n{c.get('chunk_text', '')[:500]}"
        for c in top_chunks
    )
    user_msg = f"고객 문의: {query}\n\n[문서]\n{chunks_text}"
    llm = await _call_llm(RAG_SYSTEM, user_msg)

    FALLBACK = "관련 지침에서 명확한 내용을 찾지 못했습니다."
    raw_answer = (llm.get("answer") or "").strip()

    # 금지 문구 후처리 제거
    _BANNED = [
        "질병관리청에 문의", "질병관리청으로 문의", "질병관리청 홈페이지",
        "관련 기관에 문의", "담당 기관에 문의", "자세한 사항은",
    ]
    for banned in _BANNED:
        if banned in raw_answer:
            # 해당 문장만 제거 (문장 단위로 분리 후 필터)
            sentences = [s.strip() for s in raw_answer.replace("。", ".").split(".") if s.strip()]
            sentences = [s for s in sentences if not any(b in s for b in _BANNED)]
            raw_answer = ". ".join(sentences).strip()
            if raw_answer and not raw_answer.endswith("."):
                raw_answer += "."
            break

    answer = raw_answer if raw_answer and raw_answer != FALLBACK else FALLBACK

    card = {
        "status":       "success",
        "query":        query,
        "disease_name": disease_name,
        "intent":       llm.get("intent", ""),
        "answer":       answer,
        "sources":      [_make_source(c) for c in top_chunks],
    }
    if is_emergency:
        card["emergency"] = True
    return card

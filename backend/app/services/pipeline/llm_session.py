"""
LLM 기반 실시간 상담 보조 (v6)
발화 하나씩 입력 → READY 판단 + OOS 판정 + query/disease_name/category 반환

변경사항 (v6):
  - category_major, category_mid 제거 (후처리 단계에서 분류)
  - 예방접종 / 해외/검역 정보 문의 / 감염병 통계·현황 → 독립 최상위 category
  - is_oos=false이지만 RAG 미대상 카테고리를 명확히 구분

화자 분리 연동:
  - 고객 발화: LLM 호출 트리거 + 컨텍스트 누적
  - 상담사 발화: 컨텍스트 누적만 (LLM 호출 없음)

category 매핑:
  is_oos=false, category_type=infectious    → '감염병'            (RAG)
  is_oos=false, category_type=vaccination   → '예방접종'           (API 예정)
  is_oos=false, category_type=statistics    → '감염병 통계·현황'    (API 예정)
  is_oos=false, category_type=quarantine    → '해외/검역 정보 문의' (API 예정)
  is_oos=true,  oos_type=action_required    → category=null, 접수처리
  is_oos=true,  oos_type=realtime_local     → category=null, 실시간·지역정보
  is_oos=true,  oos_type=unrelated          → category=null, 범위외

RAG 실행 조건: category='감염병'
"""

import json
import asyncio
import numpy as np
from openai import AsyncOpenAI
from app.core.config import settings

_client: AsyncOpenAI | None = None

EMBEDDING_MODEL = "text-embedding-3-small"
DUPLICATE_THRESHOLD = 0.90   # 이 이상 유사하면 중복으로 판단


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def _embed_async(text: str) -> np.ndarray:
    resp = await _get_client().embeddings.create(
        model=EMBEDDING_MODEL, input=[text[:8000]]
    )
    return np.array(resp.data[0].embedding, dtype=np.float32)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def _derive_category(is_oos: bool, category_type: str | None) -> str | None:
    """is_oos + category_type → category 매핑 (is_oos=true이면 None)"""
    if is_oos:
        return None
    if category_type == "vaccination":  return "예방접종"
    if category_type == "statistics":   return "감염병 통계·현황"
    if category_type == "quarantine":   return "해외/검역 정보 문의"
    return "감염병"


SYSTEM_PROMPT = """당신은 질병관리청 콜센터 상담사를 보조하는 AI입니다.
실시간으로 들어오는 상담 대화를 보고, 상담사가 답변해야 할 질문이 파악되면 알려주세요.

입력 형식: 각 발화 앞에 [고객] 또는 [상담사] 레이블이 붙습니다.

## READY 판단 기준
- [고객]의 질문/요청이 구체적으로 파악되면 ready: true (업무 범위 외 문의·일반 의료 질문도 포함)
- 아직 파악이 안 됐거나 인사/잡담이면 ready: false
- [상담사]가 이미 답변한 내용을 고객이 재확인하는 것이면 ready: false
- 컨텍스트에 "이미 카드로 전달됨" 표시가 있는 질문을 고객이 단순 확인하는 것이면 ready: false
- "네", "아니요", "그렇습니다", "맞아요" 등 단순 응답만 있는 발화는 ready: false
- 고객의 발화가 이전 질문의 연속(보충 설명, 단순 동의/부정)이면 ready: false
  (단, 대화 흐름상 새로운 질문/요청이 명확히 추가된 경우는 ready: true)

## 분류 체계 (ready=true 시에만 판단)

### is_oos=false — 질병관리청 업무 범위 내
※ 코로나19·감염병·방역과 조금이라도 관련되면 반드시 is_oos=false

category_type으로 세분:

**infectious** — 감염병 정보 및 방역 (RAG로 답변):
  · 특정 법정감염병의 정의·병원체·전파경로·잠복기·임상증상·진단기준
  · 방역지침·위생수칙·격리 수칙·소독 방법·치료 방법·치료제 정보
  · 신고 기준·신고 대상·신고 의무 (※ 시스템 사용 방법이 아닌, "신고해야 하나요?" 류)
  · 격리 기간·역학조사 절차·접촉자 관리 기준
  · 감염병 관련 경제지원·생활지원금·보상·심리상담
  · 일반 건강·의료 질문 (감염병과 관련될 수 있는 증상·건강 상태 문의)

**vaccination** — 예방접종·백신 (외부 API 예정):
  · 백신 종류·무료접종 대상·접종 시기·접종 방법·이상반응·접종 기관 위치
  ※ 치료제 정보(약 처방·복용·비용)는 infectious로 분류

**statistics** — 감염병 통계·현황 (외부 API 예정):
  · 일별/누적 확진자·사망자 수, 지역별 발생 현황, 감시 통계

**quarantine** — 해외/검역 정보 (외부 API 예정):
  · 해외 감염병 위험도, 출입국 검역 절차, 여행 전 주의사항

### is_oos=true — 업무 범위 외 또는 별도 처리 필요

**action_required** — 접수처리 (시스템·행정 처리):
  · 질병보건통합관리시스템 권한 신청·승인·오류
  · 감염병 신고 시스템 입력 방법·접수·수정·취소·오류
  · 시스템 로그인 오류, 검사 의뢰 조회, 사례조사서 작성·수정
  ※ 구분 기준: "신고 기준·대상?" → infectious / "시스템에 어떻게 입력?" → action_required

**realtime_local** — 실시간·지역 정보:
  · 선별진료소·병원·보건소 위치·연락처·운영시간
  · 지역별 백신 재고·수량, 검사 비용, 담당 부서 연락처

**unrelated** — 범위외:
  · 질병·방역 업무와 전혀 무관한 문의
  ※ 애매하면 반드시 is_oos=false (unrelated는 명백히 무관한 경우만)

---

반드시 아래 JSON 형식으로만 출력하세요. 다른 텍스트는 절대 포함하지 마세요.

ready=false일 때:
{"ready": false, "is_oos": null, "category_type": null, "oos_type": null, "oos_reason": null, "disease_name": null, "query": null}

ready=true, is_oos=false일 때:
{"ready": true, "is_oos": false, "category_type": "infectious", "oos_type": null, "oos_reason": null, "disease_name": "질병관리청 공식 병명 또는 null", "query": "검색용 핵심 질문 한 문장"}
  → category_type은 반드시: infectious / vaccination / statistics / quarantine

ready=true, is_oos=true일 때:
{"ready": true, "is_oos": true, "category_type": null, "oos_type": "action_required", "oos_reason": "사유 한 문장", "disease_name": null, "query": "핵심 질문 한 문장"}
  → oos_type은 반드시: action_required / realtime_local / unrelated

query 규칙:
- 반드시 검색 엔진에 단독으로 입력해도 의미가 통하는 완전한 한 문장으로 작성
- 고객 발화에 주어(병명·주제)가 생략됐으면 대화 맥락에서 반드시 보완

disease_name 규칙 (is_oos=false 시에만):
- 특정 감염병명이 명확히 언급된 경우: 질병관리청 공식 병명으로 정규화
- 특정 병명이 없거나 불분명한 경우: null

주요 정규화 목록:
  "코로나", "코로나19" → "코로나바이러스감염증-19"
  "메르스" → "중동호흡기증후군(MERS)"
  "에이즈", "HIV" → "후천성면역결핍증(AIDS)"
  "독감" → "인플루엔자"
  "볼거리" → "유행성이하선염"
  "수족구" → "수족구병"
  "노로" → "노로바이러스 감염증"
"""


class LLMSession:
    def __init__(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._llm_call_count = 0
        self._last_query_vec: np.ndarray | None = None   # 중복 필터용

    async def on_utterance(
        self,
        text: str,
        role: str = "고객",
        call_on_all: bool = False,
    ) -> dict | None:
        """
        발화 하나 처리.
        role: "고객" | "상담사"
        call_on_all: True이면 상담사 발화도 LLM 호출 (실험용)

        반환:
          None  → ready=false (아직 READY 아님) 또는 중복 쿼리
          {
            "ready": True,
            "is_oos": bool,
            "oos_type": "action_required"|"realtime_local"|"unrelated"|None,
            "oos_reason": str | None,
            "disease_name": str | None,
            "query": str,
            "category": "감염병"|"예방접종"|"감염병 통계·현황"|"해외/검역 정보 문의"|None,
            "_query_vec": ndarray,  # RAG 임베딩 재사용용
          }
        """
        self.messages.append({"role": "user", "content": f"[{role}] {text}"})

        if role != "고객" and not call_on_all:
            return None

        self._llm_call_count += 1
        resp = await _get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=self.messages,
            temperature=0,
            max_tokens=150,
            response_format={"type": "json_object"},
        )

        raw = resp.choices[0].message.content.strip()
        self.messages.append({"role": "assistant", "content": raw})

        result = json.loads(raw)
        if not result.get("ready"):
            return None

        # ── 중복 쿼리 필터링 ──────────────────────────
        query = result.get("query", "")
        query_vec = await _embed_async(query)

        if self._last_query_vec is not None:
            sim = _cosine_sim(query_vec, self._last_query_vec)
            if sim >= DUPLICATE_THRESHOLD:
                return None

        self._last_query_vec = query_vec

        # ── 처리 완료 표시 (중복 READY 방지) ─────────
        self.messages.append({
            "role": "system",
            "content": (
                f'위 질문("{query}")은 이미 상담사 화면에 카드로 전달됐습니다. '
                "이후 고객 발화는 새로운 질문으로 판단하세요."
            ),
        })

        # ── category 자동 매핑 (category_type 내부 처리 후 제거) ───
        result["category"] = _derive_category(
            result["is_oos"],
            result.pop("category_type", None),
        )
        result["_query_vec"] = query_vec

        return result

    def flush(self) -> None:
        """상담 종료 / 초기화"""
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._llm_call_count = 0
        self._last_query_vec = None

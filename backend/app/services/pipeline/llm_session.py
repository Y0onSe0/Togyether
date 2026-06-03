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
  is_oos=true,  oos_type=transfer           → category=null, 타기관 이관
  is_oos=true,  oos_type=unrelated          → category=null, 범위외

RAG 실행 조건: category='감염병'
"""

import json
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
- 판단이 애매하면 ready: true로 판단 (미발동보다 과발동이 낫다)
- 아직 파악이 안 됐거나 인사/잡담이면 ready: false
- [상담사]가 이미 답변한 내용을 고객이 단순히 재확인하는 것이면 ready: false
  (단, 재확인이라도 명확히 새로운 질문/요청이 추가됐으면 ready: true)
- 컨텍스트에 "이미 카드로 전달됨" 표시가 있는 질문을 고객이 단순 확인하는 것이면 ready: false
- "네", "아니요", "그렇습니다", "맞아요" 등 단순 응답만 있는 발화는 ready: false
- 고객의 발화가 단순 동의/부정 또는 이전 발화의 보충 설명에 불과하면 ready: false
  (단, 대화 흐름상 새로운 질문/요청이 명확히 추가된 경우는 ready: true)

## 분류 체계 (ready=true 시에만 판단)

### 핵심 판단 기준
질병관리청 발간 **고정 지침(PDF)**으로 답할 수 있는가?
  YES → infectious   (RAG로 검색 가능)
  NO  → 아래 다른 category (실시간·변동·지역 의존 정보)

### is_oos=false — 질병관리청 업무 범위 내
※ 코로나19·감염병·방역과 조금이라도 관련되면 반드시 is_oos=false

category_type으로 세분:

**infectious** — 감염병 정보 및 방역 (RAG로 답변):
  · PDF 지침에 고정 수록된 정보: 병원체·전파경로·잠복기·임상증상·진단기준
  · 방역지침·위생수칙·격리 수칙·소독 방법·치료 방법·치료제 정보
  · 신고 기준·신고 대상·신고 의무 (※ 시스템 사용 방법이 아닌, "신고해야 하나요?" 류)
  · 격리 기간·역학조사 절차·접촉자 관리 기준
  · 확진자 동선 공개 기준·정책·범위 (어떤 장소가 공개되는가, 방역 후 공개 여부, 개인정보 비공개 기준)
  · 감염병 관련 경제지원·생활지원금·보상·심리상담
  · 일반 건강·의료 질문 (감염병과 관련될 수 있는 증상·건강 상태 문의)
  예) "결핵 격리 기간은?", "볼거리 의심환자도 신고해야 하나요?", "코로나 소독 방법은?",
      "수족구 격리는 어떻게 하나요?", "C형간염 환자도 계속 신고 대상인가요?",
      "코로나 치료제 처방 기준은?", "기침이 2주째인데 결핵인가요?",
      "확진자 다녀간 식당 공개되나요?", "방역하면 동선 다 공개하나요?", "어떤 경우에 동선이 공개되나요?"

**vaccination** — 예방접종·백신 (매 시즌 변동, 외부 API 예정):
  · 접종 시기·무료접종 대상·접종 방법·이상반응·백신 효과 지속 기간 등
    (접종 일정·대상은 연도별·시즌별로 변경되므로 고정 PDF로 답 불가)
  예) "독감 백신 언제 맞아야 하나요?", "A형간염 무료접종 대상이 누구인가요?",
      "접종 후 항체는 언제 형성되나요?", "소아는 몇 월에 접종하는 게 좋나요?",
      "백신 맞았는데 면역 효과가 얼마나 가나요?"
  ※ 치료제 정보(약 처방·복용·비용)는 infectious로 분류
  ※ 대화가 특정 감염병을 다루고 있어도, 현재 발화가 접종 시기·접종 대상·이상반응·백신 효과를 묻는다면 반드시 vaccination으로 분류

**statistics** — 감염병 통계·현황 (매일 갱신, 외부 API 예정):
  · 기관이 발표하는 집계 데이터: 일별/누적 확진자·사망자 수, 지역별·연령별 발생 현황, 주간 감시 통계
  예) "오늘 코로나 확진자 몇 명이에요?", "최근 결핵 발생 현황 알 수 있나요?",
      "지역별 확진자 현황 알 수 있나요?", "연령대별 감염 통계를 알고 싶어요"

**quarantine** — 해외/검역 정보 (외부 API 예정):
  · 해외 감염병 위험도, 출입국 검역 절차, 여행 전 주의사항
  · 해외 입국 금지·완화 현황, 특정 국가 여행 가능 여부, 귀국 후 격리 기준
  예) "동남아 여행 시 주의해야 할 감염병은?", "해외 입국 시 검역 절차는?",
      "동남아 입국 금지 언제 풀려요?", "해외 여행 지금 가능한가요?",
      "해외여행 금지 아직도 되나요?", "입국 후 어떻게 해야 하나요?"
  ※ 상담사가 외교부 등 타 기관을 안내하더라도, 고객 질문이 해외 여행·입국·검역에 관한 것이면 반드시 is_oos=false, category_type=quarantine
  ※ quarantine은 oos_type이 아닌 category_type입니다 (is_oos=false 필수)
  ※ 병원·보건소·의료기관이 감염병 관리를 위해 입국자 감염 정보를 조회·보고하는 절차는 quarantine이 아닌 infectious로 분류
    (quarantine은 개인 여행자의 해외 출입국·검역에 관한 질문에만 적용)

### is_oos=true — 업무 범위 외 또는 별도 처리 필요

**action_required** — 접수처리 (시스템·행정 처리):
  · 질병보건통합관리시스템(방역통합정보시스템) 권한 신청·승인·오류
  · 감염병 신고 시스템 입력 방법·접수·수정·취소·오류 (※ 시스템 조작 문의)
  · 시스템 로그인 오류, 검사 의뢰 조회, 사례조사서 작성·수정
  · 기타 행정 민원·접수처리
  예) "시스템 로그인이 안 돼요", "A형간염 환자 신고를 어떻게 시스템에 입력하나요?",
      "신고서 제출했는데 오류가 나요", "권한 신청은 어떻게 하나요?",
      "검사 의뢰를 취소하려면 어떻게 하나요?"
  ※ 구분 기준: "신고 기준·대상이 어떻게 되나요?" → infectious
               "신고를 어떻게 시스템에 입력/접수하나요?" → action_required

**realtime_local** — 위치 기반 시설·정보 안내:
  · 고객이 자신의 위치(지역)를 언급하며 근처 시설을 찾거나 지역별 정보를 요청하는 경우
  · 선별진료소·보건소·접종기관 위치·연락처·운영시간 안내
  · 특정 지역(우리 동네, ○○구 등) 확진자 동선·이동경로 확인 요청
  예) "근처 선별진료소 어디예요?", "관할 보건소 연락처 알려주세요",
      "우리 동네 독감 접종 어디서 해요?", "가까운 보건소 어떻게 가요?",
      "우리 동네 확진자 동선 언제 알 수 있어요?", "도봉구 확진자 동선 어디서 확인해요?"
  ※ 위치(지역명)가 언급되거나 지역 특정 정보를 원해야 realtime_local
  ※ 단순히 "어디로 연락하나요?", "연락처 알려주세요" (위치 언급 없음) → transfer로 분류
  ※ 지역별 확진자 수·통계 현황은 statistics로 분류

**transfer** — 타 기관·부서 이관:
  · 현재 콜센터 담당 범위 밖으로 다른 기관·담당 부서로 연결·안내가 필요한 경우
  · 상담사가 "저희 담당이 아닙니다"라고 한 후 고객이 담당 기관을 묻는 경우
  · 특정 부서·기관의 연락처·전화번호를 직접 요청하는 경우
  · 전화 이관 중 고객이 이관 상대방 기관의 정체를 확인하거나 바로 연결을 요청하는 경우
  예) "그러면 어디로 전화해야 하나요?", "담당 부서 연락처 알려주세요",
      "헬프데스크 번호 알 수 있을까요?", "○○기관 어디로 연락하면 되나요?",
      "연락처 알 수 있을까요?", "어디로 연락해야 해요?",
      "여기가 어디예요?" (이관처 확인), "전화 돌려주시면 안 되나요?"
  ※ 고객이 위치(지역명)를 언급하며 근처 시설을 찾는 경우는 realtime_local로 분류

**unrelated** — 범위외:
  · 질병·방역 업무와 전혀 무관한 문의 (비자 발급, 정치적 발언, 잘못 연결된 전화)
  · 애매하면 반드시 is_oos=false로 분류 (unrelated는 명백히 무관한 경우만)
  예) "코로나 때문에 집회 금지인가요?" → unrelated (정치·행정)
      "의료계 붕괴 가능성은요?" → unrelated
  ※ 범위외도 ready=true로 처리

### 분류 원칙
**고객의 발화 내용**을 기준으로 분류합니다.
상담사가 "안내 어렵다", "다른 기관으로 문의하세요", 외부 홈페이지를 안내하더라도,
고객의 질문 자체가 질병관리청 업무 범위 내라면 반드시 is_oos=false로 분류하세요.

## 주의사항
"신고해야 하나요? / 누가 신고하나요? / 몇 급인가요?" → 지식 질문 → infectious
"어떻게 입력하나요? / 오류가 나요 / 취소하려면?" → 시스템 조작 → action_required

---

반드시 아래 JSON 형식으로만 출력하세요. 다른 텍스트는 절대 포함하지 마세요.

ready=false일 때:
{"ready": false, "is_oos": null, "category_type": null, "oos_type": null, "oos_reason": null, "disease_name": null, "query": null}

ready=true, is_oos=false일 때:
{"ready": true, "is_oos": false, "category_type": "infectious", "oos_type": null, "oos_reason": null, "disease_name": "질병관리청 공식 병명 또는 null", "query": "검색용 핵심 질문 한 문장"}
  → category_type은 반드시: infectious / vaccination / statistics / quarantine

ready=true, is_oos=true일 때:
{"ready": true, "is_oos": true, "category_type": null, "oos_type": "action_required", "oos_reason": "사유 한 문장", "disease_name": null, "query": "핵심 질문 한 문장"}
  → oos_type은 반드시: action_required / realtime_local / transfer / unrelated

query 규칙:
- 반드시 검색 엔진에 단독으로 입력해도 의미가 통하는 완전한 한 문장으로 작성
- 앞의 대화 맥락을 반영해서 **병명과 구체적인 질문으로 완성**
- 가장중요한건 질문에 해당하는 병명을 꼭 쿼리에 넣는 것
- 고객 발화에 주어(병명·주제)가 생략됐으면 대화 맥락에서 반드시 보완
  예: 인플루엔자 대화 중 "임상증상은 무엇이 있나요?" → "인플루엔자 임상증상은 무엇이 있나요?"
- 구어체는 검색에 적합한 표현으로 변환 (단, 병명은 정규화된 공식 병명 사용)
- is_oos=true인 경우에도 query는 작성 (상담사 참고용)

disease_name 규칙 (is_oos=false 시에만):
- 특정 감염병명이 명확히 언급된 경우: 질병관리청 공식 병명으로 정규화
- 특정 병명이 없거나 불분명한 경우: null

주요 정규화 목록 (구어체 → 공식 병명):
  "코로나", "코로나19", "코비드" → "코로나바이러스감염증-19"
  "메르스" → "중동호흡기증후군(MERS)"
  "에이즈", "HIV", "에이치아이브이" → "후천성면역결핍증(AIDS)"
  "독감" → "인플루엔자"
  "에이형 간염", "에이간염", "A형 간염" → "A형간염"
  "비형 간염", "B형 간염", "비간염" → "B형간염"
  "씨형 간염", "씨간염", "C형 간염" → "C형간염"
  "이형 간염", "E형 간염" → "E형간염"
  "볼거리" → "유행성이하선염"
  "수족구" → "수족구병"
  "노로" → "노로바이러스 감염증"
  "살모넬라" → "살모넬라균 감염증"
  "장티푸스" → "장티푸스"
  "결핵" → "결핵" (변경 없음)
  "씨알이", "CRE", "카바페넴" → "카바페넴내성장내세균목(CRE) 감염증"
  "씨피이", "CPE" → "카바페넴내성장내세균목(CRE) 감염증"
  "브이알이", "VRE" → "반코마이신내성장알균(VRE) 감염증"
  "브이에스알에이", "VRSA" → "반코마이신내성황색포도알균(VRSA) 감염증"
  "엠알에이비", "MRAB" → "다제내성아시네토박터바우마니균(MRAB) 감염증"
  "루벨라" → "풍진"
  "캄필로박터" → "캄필로박터균 감염증"
  "브루셀라" → "브루셀라증"
  "임질" → "임질"
  "매독" → "매독"
  "1기 매독", "매독 1기", "일기 매독" → "매독(1기)"
  "2기 매독", "매독 2기", "이기 매독" → "매독(2기)"
  "3기 매독", "매독 3기", "삼기 매독" → "매독(3기)"
  "선천성 매독", "매독 선천성" → "매독(선천성)"
  "잠복 매독", "매독 잠복" → "매독(잠복)"
  "선천성 풍진", "풍진 선천성" → "풍진(선천성)"
  "후천성 풍진", "풍진 후천성" → "풍진(후천성)"
  "에볼라", "에볼라 바이러스" → "에볼라바이러스병"
  "마버그", "마버그 바이러스" → "마버그열"
  "라싸", "라싸 바이러스" → "라싸열"
  "니파", "니파 바이러스" → "니파바이러스감염증"
  "크리미안콩고", "크리미아콩고출혈열" → "크리미안콩고출혈열"
  "리프트밸리", "리프트 밸리열" → "리프트밸리열"
  "마이코플라스마", "마이코플라스마 폐렴" → "마이코플라스마 폐렴균 감염증"
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
            "oos_type": "action_required"|"realtime_local"|"transfer"|"unrelated"|None,
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

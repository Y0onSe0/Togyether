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
실시간 상담 대화를 분석해 카드를 전달합니다.
입력 형식: 각 발화 앞에 [고객] 또는 [상담사] 레이블이 붙습니다.

## READY 판단

### ★ 응급 키워드 → 무조건 ready: true
경련, 의식을 잃, 의식이 없, 의식없, 의식불명, 심정지, 심폐소생, 쓰러, 실신,
호흡곤란, 숨을 못, 숨쉬기 힘, 숨이 안, 흉통, 가슴 통증, 가슴이 아파, 가슴이 너무 아파,
다량 출혈, 피가 안 멈, 피가 너무, 출혈이 심, 위급, 생명이 위험

### 기본 원칙
- 고객이 무언가를 묻거나 요청하면 **주제 불문 ready: true**
- **판단이 애매하면 반드시 ready: true** (미발동보다 과발동이 낫다)

### ready: false는 아래만
- 단순 인사: "안녕하세요", "여보세요", "감사합니다", "수고하세요"
- 단순 응답: "네", "아니요", "맞아요", "알겠어요"
- 이미 답변한 내용을 단순 재확인하는 경우 (새 질문 추가 시 ready: true)
- 컨텍스트에 "이미 카드로 전달됨" 표시가 있는 질문을 단순 확인하는 경우

※ "~문의하려고요", "~여쭤보려고요", "~알고 싶어요", "~궁금한데요" 등
   주제가 포함된 문의 의향 표현은 **반드시 ready: true**
   예) "건강보험 보험료 문의하려고요" → ready: true
       "결핵 격리 기간 여쭤보려고요" → ready: true

## 분류 체계 (ready=true 시)

고객 질문이 **지식·정보** → is_oos=false
고객 질문이 **시스템 조작·위치 안내·타기관 이관** → is_oos=true (감염병 관련이더라도)
분류 기준은 **고객 발화**. 상담사가 "다른 기관 문의하세요"라고 해도 고객 질문이 지식·정보면 is_oos=false.

### is_oos=false

**infectious** — 고정 PDF 지침으로 답 가능한 감염병 정보:
  병원체·전파경로·잠복기·증상·진단기준, 방역지침·격리수칙·소독·치료제,
  신고 기준·역학조사·접촉자 관리, 확진자 동선 공개 기준, 경제지원·생활지원금
  예) "결핵 격리 기간은?", "수족구 격리는?", "코로나 소독 방법은?", "볼거리 신고 기준은?"
      "에이즈 환자가 있는데 신고해야 하나요?" → infectious (신고 기준 지식)
      "이 경우 신고 대상인가요?" → infectious
      의료기관 종사자가 신고 기준·의무를 묻는 경우도 반드시 infectious
  ※ "신고해야 하나요?" / "신고 대상인가요?" / "몇 급 감염병인가요?" → infectious
     "어떻게 시스템에 입력하나요?" / "신고서 제출 방법은?" → action_required

**vaccination** — 매 시즌 변동 접종 정보 (고정 PDF로 답 불가):
  접종 시기·무료접종 대상·이상반응·백신 효과 지속기간
  예) "독감 백신 언제 맞아요?", "A형간염 무료접종 대상은?", "접종 후 항체 언제 생겨요?"
  ※ 치료제(약 처방·복용·비용) → infectious

**statistics** — 매일 갱신되는 집계 데이터:
  일별/누적 확진자·사망자, 지역별·연령별 발생 현황, 주간 감시 통계
  예) "오늘 코로나 확진자 몇 명?", "최근 결핵 발생 현황은?", "연령대별 감염 통계 알려주세요"

**quarantine** — 개인 여행자의 해외 출입국·검역:
  해외 감염병 위험도, 검역 절차, 입국 금지·완화, 귀국 후 격리 기준
  예) "베트남 여행 다녀왔는데 검역은요?", "동남아 여행 주의 감염병은?", "해외 입국 검역 절차는?", "귀국 후 어떻게 해요?"
  ※ 해외 국가명(베트남, 태국, 중국 등)이 언급되더라도 검역·입국 관련이면 반드시 quarantine (is_oos=false)
  ※ 의료기관의 입국자 감염 정보 조회·보고 → infectious

### is_oos=true

**action_required** — 시스템·행정 처리:
  질병보건통합관리시스템 로그인·권한·오류, 신고서 입력·수정·취소, 사례조사서 작성
  예) "로그인이 안 돼요", "권한 신청은 어떻게?", "신고서 오류가 나요", "검사 의뢰 취소하려면?"
  ※ 주의: "신고해야 하나요?", "신고 대상인가요?" 는 시스템 조작이 아닌 지식 질문 → infectious

**realtime_local** — 국내 위치 기반 시설 찾기:
  "근처", "우리 동네", "○○구/시" 등 국내 지역을 언급하며 시설 위치·연락처·운영시간을 묻는 경우
  선별진료소·보건소·접종기관 위치 안내
  예) "근처 선별진료소 어디예요?", "우리 동네 보건소 연락처는?", "○○구 접종기관 어디예요?"
  ※ 반드시 국내 지역명("근처", "우리 동네", "○○시/구") 포함 시에만 해당
  ※ 해외 국가명(베트남, 태국 등) 언급 → quarantine (is_oos=false)
  ※ 위치 언급 없이 연락처만 요청 → transfer

**transfer** — 타 기관·부서 연결 요청:
  담당 기관 연락처 요청, 다른 부서 연결, 이관 대상 기관 확인
  예) "어디로 전화하면 되나요?", "담당 부서 연락처는?", "헬프데스크 번호는?", "전화 돌려주세요"
  ※ 국내 지역 언급하며 근처 시설 찾는 경우 → realtime_local
  ※ 해외 국가명 + 검역 관련 → quarantine

**unrelated** — 감염병·의료·방역과 전혀 무관:
  날씨, 비자, 주식, 잘못 연결된 전화 등 완전히 동떨어진 문의
  예) "날씨 어때요?", "비자 발급 어디서?", "주식 어떻게 해요?", "여기 음식점인가요?"
  ※ 애매하면 unrelated 대신 다른 카테고리로

---

반드시 아래 JSON 형식으로만 출력하세요.

ready=false:
{"ready": false, "is_oos": null, "category_type": null, "oos_type": null, "oos_reason": null, "disease_name": null, "query": null}

ready=true, is_oos=false:
{"ready": true, "is_oos": false, "category_type": "infectious", "oos_type": null, "oos_reason": null, "disease_name": "공식 병명 또는 null", "query": "검색용 핵심 질문 한 문장"}
→ category_type: infectious / vaccination / statistics / quarantine

ready=true, is_oos=true:
{"ready": true, "is_oos": true, "category_type": null, "oos_type": "action_required", "oos_reason": "사유 한 문장", "disease_name": null, "query": "핵심 질문 한 문장"}
→ oos_type: action_required / realtime_local / transfer / unrelated

query 규칙:
- **[병명] + [핵심개념]** 형태의 명사구로 작성 (구어체 금지)
- 병명은 반드시 포함, 공식 병명 사용
- 주어·조사·어미 제거하고 핵심 개념만 남기기
  예) "수족구 걸렸는데 어린이집 며칠 쉬어야 해요?" → "수족구병 격리기간 등원중지 기준"
      "에이즈 환자가 있는데 신고해야 하나요?" → "후천성면역결핍증 신고의무 신고기준"
      "코로나 소독은 어떻게 해요?" → "코로나바이러스감염증-19 소독방법 방역지침"
      "결핵 접촉자는 어떻게 관리하나요?" → "결핵 접촉자관리 검진기준"
- 맥락에서 병명이 생략됐으면 반드시 보완
- is_oos=true에도 query 작성 (상담사 참고용, 동일 규칙 적용)

disease_name (is_oos=false 시에만):
- 특정 감염병명 명확히 언급 시 공식 병명으로 정규화, 없으면 null

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


# ── 키워드 선처리 ─────────────────────────────────────────────────────────────
# 명확한 케이스는 LLM 호출 없이 즉시 분류
# 반환: (is_oos, oos_type, category) 또는 None (LLM에 위임)

_KW_ACTION_REQUIRED = [
    "로그인", "로그 인", "비밀번호", "아이디", "권한 신청", "권한신청",
    "권한 요청", "권한요청", "시스템 오류", "시스템오류", "시스템 에러",
    "사례조사서", "신고서 수정", "신고서 취소", "접수 취소", "접수취소",
    "검사 의뢰 취소", "검사의뢰취소", "방역통합", "질병보건통합",
    "신고를 어떻게 입력", "어떻게 입력", "어떻게 접수",
]

_KW_REALTIME_LOCAL = [
    "선별진료소", "보건소 위치", "보건소 어디", "보건소 연락처",
    "가까운 보건소", "근처 보건소", "우리 동네", "우리동네",
    "근처", "가까운", "어디 있어", "어디 있나요", "어디예요",
]
# realtime_local은 위치성 키워드가 있을 때만 (단독 "연락처"는 transfer)
_KW_REALTIME_LOCAL_REQUIRE = [
    "선별진료소", "보건소", "접종기관", "우리 동네", "우리동네",
    "근처", "가까운", "○○구", "동네",
]

_KW_TRANSFER = [
    "건강보험", "보험료", "건강보험공단",
    "국민연금", "연금 문의", "연금공단",
    "복지 서비스", "복지급여", "복지로",
    "진료비 심사", "비급여", "심사평가원",
    "고용보험", "실업급여", "산재",
]

_KW_UNRELATED = [
    "날씨", "비자 발급", "비자발급", "주식", "로또", "복권",
    "부동산", "축구", "야구", "배구",
    "배달", "택배", "환율",
]


def _keyword_prefilter(text: str) -> dict | None:
    """
    키워드 기반 선처리.
    명확한 케이스 → 즉시 분류 결과 반환 (LLM 스킵)
    애매한 케이스 → None 반환 (LLM에 위임)
    """
    # action_required: 시스템·행정 처리 키워드
    if any(kw in text for kw in _KW_ACTION_REQUIRED):
        return {
            "ready": True, "is_oos": True,
            "oos_type": "action_required",
            "oos_reason": "시스템·행정 처리 문의",
            "disease_name": None,
            "category_type": None,
        }

    # realtime_local: 위치성 키워드 포함 시
    if any(kw in text for kw in _KW_REALTIME_LOCAL_REQUIRE):
        return {
            "ready": True, "is_oos": True,
            "oos_type": "realtime_local",
            "oos_reason": "위치 기반 시설·정보 문의",
            "disease_name": None,
            "category_type": None,
        }

    # transfer: 타 기관 이관 키워드
    if any(kw in text for kw in _KW_TRANSFER):
        return {
            "ready": True, "is_oos": True,
            "oos_type": "transfer",
            "oos_reason": "타 기관 담당 문의",
            "disease_name": None,
            "category_type": None,
        }

    # unrelated: 완전 무관 키워드
    if any(kw in text for kw in _KW_UNRELATED):
        return {
            "ready": True, "is_oos": True,
            "oos_type": "unrelated",
            "oos_reason": "질병·방역과 무관한 문의",
            "disease_name": None,
            "category_type": None,
        }

    return None  # LLM에 위임


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

        # ── 키워드 선처리 (LLM 호출 전) ──────────────
        kw_result = _keyword_prefilter(text)
        if kw_result is not None:
            result = {**kw_result, "query": text}  # 원문을 query로
        else:
            # ── LLM 호출 (애매한 경우만) ──────────────
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

"""
STEP 1: LLM 기반 READY 판정 + 카테고리 분류
발화 하나씩 입력 → READY 판단 + 라우팅 + refined_query 반환

카테고리: 감염병 | 접수처리 | 범위외
중복 쿼리 필터링: 임베딩 코사인 유사도 >= 0.90 이면 무시
"""
import json
import numpy as np
from openai import AsyncOpenAI
from app.core.config import settings

_client: AsyncOpenAI | None = None
EMBEDDING_MODEL = "text-embedding-3-small"
DUPLICATE_THRESHOLD = 0.90


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


SYSTEM_PROMPT = """당신은 질병관리청 콜센터 상담사를 보조하는 AI입니다.
실시간으로 들어오는 상담 대화를 분석해, 고객의 요청/질문이 명확히 파악되면 ready: true를 반환하세요.
범위외(타 기관 소관) 질문도 고객 의도가 명확하면 반드시 ready: true입니다.

입력 형식: 각 발화 앞에 [고객] 또는 [상담사] 레이블이 붙습니다.

## READY 판단 기준
ready: true → 고객 의도가 명확함 (감염병·시스템·범위외 구분 없이)
ready: false → 인사·잡담·단순응답("네"/"아니요")·의도불명확

예시:
[고객] 실업급여 어디에 신청하나요? → {"ready": true, "category": "범위외", "refined_query": "실업급여 신청 방법 문의"}
[고객] 코로나 격리기간이 얼마나 되나요? → {"ready": true, "category": "감염병", "refined_query": "코로나19 격리기간 문의"}
[고객] 안녕하세요 → {"ready": false}
[고객] 네 → {"ready": false}

## 카테고리 (반드시 하나 선택)
- 감염병: 감염병·전염병 관련 정보 문의
  · 일반 시민: 증상, 잠복기, 전파경로, 격리기간, 예방접종, 소독, 예방수칙 등
  · 의료기관 종사자: 감염병 신고 방법, 역학조사, 환자격리기준, 방역지침, 검사기준 등
  · 해외/검역 관련: 여행 감염병, 입국 검역 등
- 접수처리: 상담사가 시스템에서 직접 처리하는 업무
  · 권한 신청·승인, 시스템 오류·메뉴 안내
  · 감염병 신고 접수, 환자정보 확인·변경
  · 기타 행정 처리
- 범위외: 질병관리청 소관이 아닌 모든 문의
  · 타 기관 소관 (지원금·생활비·고용보험·돌봄서비스·정부정책·복지급여 등)
  · 타 기관 연락처·담당자 문의
  · 질병관리청 업무와 전혀 무관한 문의
  ※ 주의: 감염병 정보 문의는 반드시 감염병으로 분류 (코로나, 독감 등 포함)
  ※ 주의: 타 기관으로 연결 요청하거나 담당자 연락처를 묻는 것은 범위외

반드시 아래 JSON 형식으로만 출력하세요. 다른 텍스트는 절대 포함하지 마세요.

ready=false일 때:
{"ready": false}

ready=true, category=감염병일 때:
{"ready": true, "category": "감염병", "refined_query": "핵심 질문 한 문장", "disease_name": "질병관리청 공식 병명 또는 null"}

ready=true, category=접수처리|범위외일 때:
{"ready": true, "category": "접수처리"|"범위외", "refined_query": "핵심 질문 한 문장"}

disease_name 규칙:
- 대화에서 특정 감염병명이 명확히 언급된 경우: 질병관리청 공식 병명으로 정규화 (예: "코로나" → "코로나19", "노로" → "노로바이러스 감염증", "에이즈" → "HIV/AIDS", "메르스" → "중동호흡기증후군")
- 특정 병명이 없거나 불분명한 경우: null"""


class LLMSession:
    def __init__(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._last_query_vec: np.ndarray | None = None

    async def on_utterance(self, text: str, role: str = "고객") -> dict | None:
        """
        발화 하나 처리.
        role: "고객" | "상담사"

        반환:
          None  → 아직 READY 아님 (또는 상담사 발화)
          dict  → {"ready": True, "category": ..., "refined_query": ..., "_query_vec": ...}
        """
        self.messages.append({"role": "user", "content": f"[{role}] {text}"})

        if role != "고객":
            return None

        resp = await _get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=self.messages,
            temperature=0,
            max_tokens=120,
            response_format={"type": "json_object"},
        )

        raw = resp.choices[0].message.content.strip()
        self.messages.append({"role": "assistant", "content": raw})

        result = json.loads(raw)
        if not result.get("ready"):
            return None

        refined_query = result.get("refined_query", "")
        query_vec = await _embed_async(refined_query)

        # 중복 쿼리 필터링
        if self._last_query_vec is not None:
            if _cosine_sim(query_vec, self._last_query_vec) >= DUPLICATE_THRESHOLD:
                return None

        self._last_query_vec = query_vec

        # 처리 완료 표시 (중복 READY 방지)
        self.messages.append({
            "role": "system",
            "content": (
                f'위 질문("{refined_query}")은 이미 상담사 화면에 카드로 전달됐습니다. '
                "이후 고객 발화는 새로운 질문으로 판단하세요."
            ),
        })

        result["_query_vec"] = query_vec
        return result

    def flush(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._last_query_vec = None

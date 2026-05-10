"""
LLM 기반 실시간 상담 보조 (v3)
발화 하나씩 입력 → READY 판단 + OOS 판정 + query/disease_name 반환

변경사항 (v3):
  - 출력 스키마: category/refined_query → is_oos/oos_type/oos_reason/query (RTL-LLM-001)
  - category는 코드에서 is_oos+oos_type 기반으로 자동 매핑
  - keywords 제거 (STEP 1 출력 아님)
  - ready=false 시 모든 필드 명시적 null 반환
  - 중복 필터 기준 필드: refined_query → query

화자 분리 연동:
  - 고객 발화: LLM 호출 트리거 + 컨텍스트 누적
  - 상담사 발화: 컨텍스트 누적만 (LLM 호출 없음)

category 자동 매핑 (RTL-LLM-001):
  is_oos=false                          → '감염병'
  is_oos=true, oos_type=action_required → '접수처리'
  is_oos=true, oos_type=unrelated       → '범위외'
"""

import json
import os
import asyncio
import numpy as np
from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None

EMBEDDING_MODEL = "text-embedding-3-small"
DUPLICATE_THRESHOLD = 0.90   # 이 이상 유사하면 중복으로 판단


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


async def _embed_async(text: str) -> np.ndarray:
    resp = await _get_client().embeddings.create(
        model=EMBEDDING_MODEL, input=[text[:8000]]
    )
    return np.array(resp.data[0].embedding, dtype=np.float32)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def _derive_category(is_oos: bool, oos_type: str | None) -> str:
    """is_oos + oos_type → category 자동 매핑 (RTL-LLM-001)"""
    if not is_oos:
        return "감염병"
    if oos_type == "action_required":
        return "접수처리"
    return "범위외"


SYSTEM_PROMPT = """당신은 질병관리청 콜센터 상담사를 보조하는 AI입니다.
실시간으로 들어오는 상담 대화를 보고, 상담사가 답변해야 할 질문이 파악되면 알려주세요.

입력 형식: 각 발화 앞에 [고객] 또는 [상담사] 레이블이 붙습니다.

## READY 판단 기준
- [고객]의 질문/요청이 구체적으로 파악되면 ready: true
- 아직 파악이 안 됐거나 인사/잡담이면 ready: false
- [상담사]가 이미 답변한 내용을 고객이 재확인하는 것이면 ready: false
- 컨텍스트에 "이미 카드로 전달됨" 표시가 있는 질문을 고객이 단순 확인하는 것이면 ready: false
- "네", "아니요", "그렇습니다", "맞아요" 등 단순 응답만 있는 발화는 ready: false
- 고객의 발화가 이전 질문의 연속(보충 설명, 단순 동의/부정)이면 ready: false
  (단, 대화 흐름상 새로운 질문/요청이 명확히 추가된 경우는 ready: true)

## is_oos 판단 기준 (ready=true 시에만 판단)
is_oos=false (업무 범위 내):
  - 감염병·전염병 관련 정보 문의 (증상, 잠복기, 격리, 예방접종, 소독, 예방수칙 등)
  - 의료기관 종사자 감염병 신고·역학조사·방역지침 문의
  - 해외/검역 관련 문의
  ※ 코로나, 독감 등 감염병 정보 문의는 반드시 is_oos=false

is_oos=true, oos_type="action_required" (접수처리):
  - 상담사가 내부 시스템에서 직접 처리해야 하는 업무
  - 권한 신청·승인, 시스템 오류·메뉴 안내
  - 감염병 신고 접수, 환자정보 확인·변경, 기타 행정 처리

is_oos=true, oos_type="unrelated" (범위외):
  - 질병관리청 소관이 아닌 모든 문의
  - 타 기관 소관 (지원금·생활비·고용보험·돌봄서비스·정부정책·복지급여 등)
  - 타 기관 연락처·담당자 문의
  - 질병관리청 업무와 전혀 무관한 문의
  ※ 타 기관 연결 요청·담당자 연락처는 반드시 unrelated

반드시 아래 JSON 형식으로만 출력하세요. 다른 텍스트는 절대 포함하지 마세요.

ready=false일 때:
{"ready": false, "is_oos": null, "oos_type": null, "oos_reason": null, "disease_name": null, "query": null}

ready=true, is_oos=false일 때:
{"ready": true, "is_oos": false, "oos_type": null, "oos_reason": null, "disease_name": "질병관리청 공식 병명 또는 null", "query": "검색용 핵심 질문 한 문장"}

ready=true, is_oos=true일 때:
{"ready": true, "is_oos": true, "oos_type": "action_required"|"unrelated", "oos_reason": "범위외 사유 한 문장", "disease_name": null, "query": "핵심 질문 한 문장"}

disease_name 규칙 (is_oos=false 시에만):
- 특정 감염병명이 명확히 언급된 경우: 질병관리청 공식 병명으로 정규화
  예: "코로나" → "코로나19", "노로" → "노로바이러스 감염증", "에이즈" → "HIV/AIDS", "메르스" → "중동호흡기증후군"
- 특정 병명이 없거나 불분명한 경우: null"""


class CallSession:
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
            "oos_type": "action_required" | "unrelated" | None,
            "oos_reason": str | None,
            "disease_name": str | None,
            "query": str,
            "category": str,       # 코드 매핑: 감염병|접수처리|범위외
            "_query_vec": ndarray  # RAG 임베딩 재사용용
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

        # ── category 자동 매핑 ────────────────────────
        result["category"] = _derive_category(result["is_oos"], result.get("oos_type"))
        result["_query_vec"] = query_vec

        return result

    def flush(self) -> None:
        """상담 종료 / 초기화"""
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._llm_call_count = 0
        self._last_query_vec = None


# ─────────────────────────────────────────
# CLI 테스트
# ─────────────────────────────────────────
async def _test_session(session_id: str, turns: list[dict]):
    session = CallSession()
    print(f"\n{'='*60}")
    print(f"[{session_id}]")

    ready_count = 0
    for turn in turns:
        role = turn["role"]
        text = turn["text"]
        print(f"  [{role}] {text}")

        result = await session.on_utterance(text, role)
        if result:
            ready_count += 1
            out = {k: v for k, v in result.items() if k != "_query_vec"}
            print(f"  ★ READY → {out}")

    print(f"  → READY {ready_count}회 / LLM {session._llm_call_count}회 호출")


async def main():
    import sys
    from pathlib import Path

    data_path = Path(__file__).parent.parent / "dialog_with_meta.json"
    if not data_path.exists():
        turns = [
            {"role": "고객",   "text": "안녕하세요"},
            {"role": "상담사", "text": "네 안녕하세요, 무엇을 도와드릴까요?"},
            {"role": "고객",   "text": "코로나 걸렸는데 격리 며칠 해야 해요?"},
            {"role": "상담사", "text": "현재 코로나19는 7일 격리 권고입니다."},
            {"role": "고객",   "text": "감사합니다. 그리고 권한 신청은 어떻게 하나요?"},
        ]
        await _test_session("내장테스트", turns)
        return

    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    for session in data[:n]:
        await _test_session(session["대화셋일련번호"], session["dialog"])


if __name__ == "__main__":
    asyncio.run(main())

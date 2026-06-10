"""
Part 2 — RAG 응답 평가 (eval_v8) — LLM-as-judge
test_qa_dataset_v6_prep.json (432개)

절차:
  1. coverage_raw.json에서 정제 쿼리 + 임베딩 결과 재활용
  2. retrieve_all() → card_generator.generate_card() → RAG 답변 생성
     - no_result → RAG 점수 0점
  3. gold answer (상담사 답변) → gpt-4o-mini 채점
  4. RAG 생성 답변 → gpt-4o-mini 채점
  5. 비교

채점 기준 (1~5점):
  - 정확성(accuracy):    답변 내용이 질문에 맞는가
  - 완전성(completeness): 핵심 정보를 충분히 담았는가
  - 유용성(usefulness):  실제 콜센터 상담에서 쓸 수 있는 수준인가
  - 종합(overall):       전체 품질

출력: eval_v8/results/response_raw.json
      eval_v8/results/response_summary.txt
"""

import sys, os, json, asyncio, statistics
from pathlib import Path
from collections import defaultdict

# ── 경로 설정 ─────────────────────────────────────────────
BACKEND_ROOT = "/Users/juwon-i/2026/2026-1 캡스톤/Togyether/backend"
EVAL_ROOT    = Path(__file__).parent
DATASET      = EVAL_ROOT / "test_qa_dataset_v6_filtered.json"
COVERAGE_RAW = EVAL_ROOT / "results" / "coverage_raw.json"
RESULTS_DIR  = EVAL_ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)
OUT_RAW      = RESULTS_DIR / "response_raw.json"
OUT_SUMMARY  = RESULTS_DIR / "response_summary.txt"

if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

os.environ.setdefault("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))
os.environ.setdefault("DATABASE_URL", os.getenv("DATABASE_URL", ""))
os.environ.setdefault("JWT_SECRET_KEY", "eval-secret")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRE_MINUTES", "480")

import asyncpg
import numpy as np
from openai import AsyncOpenAI
from rank_bm25 import BM25Okapi
import app.services.pipeline.retrieval as _rtl
from app.services.pipeline.card_generator import generate_card

DB_URL = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "")
BATCH  = 5
CLIENT = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

SCORE_FIELDS = ["accuracy", "completeness", "usefulness", "overall"]

ZERO_SCORE = {"accuracy": 0, "completeness": 0, "usefulness": 0, "overall": 0}


# ── DB 로드 ───────────────────────────────────────────────
async def load_db():
    conn = await asyncpg.connect(DB_URL)
    rows = await conn.fetch("""
        SELECT chunk_index::text AS chunk_id,
               data_id, document_title, chapter, section_title,
               disease_name, knowledge_type,
               chunk_text,
               embedding::text AS embedding
        FROM knowledge_chunks ORDER BY chunk_index
    """)
    await conn.close()

    vecs, meta = [], []
    for r in rows:
        emb = np.array(json.loads(r["embedding"]), dtype=np.float32)
        vecs.append(emb)
        meta.append({k: r[k] for k in
            ["chunk_id", "data_id", "document_title", "chapter", "section_title",
             "disease_name", "knowledge_type", "chunk_text"]})

    _rtl._all_vecs = np.stack(vecs)
    _rtl._all_meta = meta
    corpus = [_rtl._tokenize_ko(_rtl._clean_content(c["chunk_text"])) for c in meta]
    _rtl._bm25_index = BM25Okapi(corpus)
    _rtl._bm25_meta  = meta
    print(f"[DB] 로드 완료: {len(meta):,}개 청크")


# ── 임베딩 ────────────────────────────────────────────────
async def embed(text: str) -> np.ndarray:
    resp = await CLIENT.embeddings.create(
        model="text-embedding-3-small", input=[text[:8000]]
    )
    return np.array(resp.data[0].embedding, dtype=np.float32)


# ── LLM 채점 ─────────────────────────────────────────────
JUDGE_PROMPT = """당신은 질병관리청 1339 콜센터 답변 품질 평가자입니다.
아래 질문과 답변을 보고 각 항목을 1~5점으로 채점하세요.

[질문]
{question}

[답변]
{answer}

채점 기준:
- accuracy(정확성, 1~5):      질문에 대한 내용이 사실적으로 맞는가
- completeness(완전성, 1~5):  핵심 정보를 충분히 담았는가
- usefulness(유용성, 1~5):    실제 콜센터 상담에서 바로 활용할 수 있는 수준인가
- overall(종합, 1~5):         전체적인 답변 품질

1점=매우 불량, 2점=불량, 3점=보통, 4점=양호, 5점=매우 우수

JSON만 반환:
{{"accuracy": int, "completeness": int, "usefulness": int, "overall": int, "reason": "한 줄 근거"}}"""


async def judge(question: str, answer: str) -> dict:
    try:
        resp = await CLIENT.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user",
                       "content": JUDGE_PROMPT.format(question=question, answer=answer)}],
            temperature=0, max_tokens=150,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        return {k: int(data.get(k, 0)) for k in SCORE_FIELDS} | {"reason": data.get("reason", "")}
    except Exception:
        return ZERO_SCORE | {"reason": "채점 오류"}


# ── 메인 ─────────────────────────────────────────────────
async def main():
    # coverage_raw 확인
    if not COVERAGE_RAW.exists():
        print(f"[오류] {COVERAGE_RAW} 없음. eval_coverage.py 먼저 실행하세요.")
        return

    await load_db()

    with open(DATASET) as f:
        dataset = json.load(f)
    with open(COVERAGE_RAW) as f:
        coverage = json.load(f)

    # question → coverage 매핑
    cov_map = {c["question"]: c for c in coverage}

    print(f"[데이터] {len(dataset)}개")

    results = []
    sem = asyncio.Semaphore(BATCH)
    done_count = {"n": 0}

    async def process(item):
        async with sem:
            question     = item["question"]
            gold_answer  = item.get("answer", "")
            gold_disease = item.get("disease_name")
            cov          = cov_map.get(question, {})
            refined_query   = cov.get("refined_query", question)
            disease_name    = cov.get("refined_disease")

            # ── RAG 답변 생성 ──────────────────────────────
            try:
                query_vec = await embed(refined_query)
                retrieval = await _rtl.retrieve_all(
                    query=refined_query,
                    is_oos=False,
                    disease_name=disease_name,
                    query_vec=query_vec,
                    top_k=5,
                )
                card = await generate_card(
                    query=refined_query,
                    is_oos=False,
                    oos_type=None,
                    oos_reason=None,
                    disease_name=disease_name,
                    retrieval=retrieval,
                    category="감염병",
                )
                if card.get("status") == "success":
                    rag_answer  = card.get("answer", "")
                    rag_status  = "success"
                else:
                    rag_answer  = ""
                    rag_status  = card.get("status", "no_result")
            except Exception as e:
                rag_answer = ""
                rag_status = "error"

            # ── 채점 ───────────────────────────────────────
            gold_score = await judge(question, gold_answer)

            if rag_status == "success" and rag_answer:
                rag_score = await judge(question, rag_answer)
            else:
                rag_score = ZERO_SCORE | {"reason": f"no_result ({rag_status})"}

            done_count["n"] += 1
            if done_count["n"] % 50 == 0:
                print(f"  [{done_count['n']}/{len(dataset)}] 진행 중...")

            return {
                "conversation_id": item.get("conversation_id"),
                "question":        question,
                "gold_disease":    gold_disease,
                "refined_query":   refined_query,
                "disease_name":    disease_name,
                "gold_answer":     gold_answer,
                "rag_answer":      rag_answer,
                "rag_status":      rag_status,
                "gold_score":      gold_score,
                "rag_score":       rag_score,
                "delta_overall":   rag_score["overall"] - gold_score["overall"],
            }

    tasks = [process(item) for item in dataset]
    for coro in asyncio.as_completed(tasks):
        r = await coro
        results.append(r)

    # ── 저장 ─────────────────────────────────────────────
    with open(OUT_RAW, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {OUT_RAW}")

    # ── 요약 ─────────────────────────────────────────────
    n = len(results)
    rag_success = [r for r in results if r["rag_status"] == "success"]
    rag_fail    = [r for r in results if r["rag_status"] != "success"]

    def avg(lst, key, subkey):
        vals = [r[key][subkey] for r in lst if r[key][subkey] > 0]
        return statistics.mean(vals) if vals else 0.0

    lines = []
    lines.append("=" * 55)
    lines.append("RAG 응답 평가 결과 (eval_v8)")
    lines.append(f"데이터셋: test_qa_dataset_v6_prep.json ({n}개)")
    lines.append("=" * 55)
    lines.append("")
    lines.append(f"[RAG 상태]")
    lines.append(f"  success   : {len(rag_success)}개 ({len(rag_success)/n*100:.1f}%)")
    lines.append(f"  no_result : {len(rag_fail)}개 ({len(rag_fail)/n*100:.1f}%) → 0점 처리")
    lines.append("")
    lines.append(f"{'항목':<14} {'Gold(상담사)':>12} {'RAG':>10} {'차이':>8}")
    lines.append("-" * 46)
    for field in SCORE_FIELDS:
        g = avg(results, "gold_score", field)
        r = avg(results, "rag_score",  field)
        d = r - g
        lines.append(f"  {field:<12} {g:>12.3f} {r:>10.3f} {d:>+8.3f}")
    lines.append("")
    lines.append("[전체 기준 비교 (overall, 0점 포함)]")
    rag_better = sum(1 for r in results if r["delta_overall"] > 0)
    rag_same   = sum(1 for r in results if r["delta_overall"] == 0)
    rag_worse  = sum(1 for r in results if r["delta_overall"] < 0)
    lines.append(f"  RAG > Gold : {rag_better}개 ({rag_better/n*100:.1f}%)")
    lines.append(f"  RAG = Gold : {rag_same}개 ({rag_same/n*100:.1f}%)")
    lines.append(f"  RAG < Gold : {rag_worse}개 ({rag_worse/n*100:.1f}%)")
    lines.append("")
    lines.append("[성공 케이스만 비교 (overall)]")
    if rag_success:
        g2 = statistics.mean(r["gold_score"]["overall"] for r in rag_success)
        r2 = statistics.mean(r["rag_score"]["overall"]  for r in rag_success)
        lines.append(f"  Gold 평균 : {g2:.3f}")
        lines.append(f"  RAG 평균  : {r2:.3f}")
        lines.append(f"  차이      : {r2-g2:+.3f}")
    lines.append("")

    summary = "\n".join(lines)
    print(summary)
    with open(OUT_SUMMARY, "w") as f:
        f.write(summary)
    print(f"[저장] {OUT_SUMMARY}")


if __name__ == "__main__":
    asyncio.run(main())

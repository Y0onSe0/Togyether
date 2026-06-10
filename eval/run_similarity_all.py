"""
good 품질 QA 전체 유사도 계산
test_qa_dataset_tagged.json → quality=good 4956개
→ 임베딩 + DB 검색 → top1_sim 계산
→ results/similarity_all.json
"""
import sys, os, json, asyncio
from pathlib import Path

BACKEND_ROOT = "/Users/juwon-i/2026/2026-1 캡스톤/Togyether/backend"
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

DB_URL = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "")
DATASET = Path("/Users/juwon-i/2026/2026-1 캡스톤/프로젝트/pipeline/evaluation/query_driven/datasets/test_qa_dataset_tagged.json")
RESULTS_DIR = Path("/Users/juwon-i/2026/2026-1 캡스톤/프로젝트/pipeline/evaluation/query_driven/results")
RESULTS_DIR.mkdir(exist_ok=True)
OUT = RESULTS_DIR / "similarity_all.json"

CLIENT = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
BATCH = 20


async def load_db():
    conn = await asyncpg.connect(DB_URL)
    rows = await conn.fetch("""
        SELECT chunk_index::text AS chunk_id, data_id, document_title, chapter,
               section_title, disease_name, knowledge_type, chunk_text,
               embedding::text AS embedding
        FROM knowledge_chunks ORDER BY chunk_index
    """)
    await conn.close()
    vecs, meta = [], []
    for r in rows:
        emb = np.array(json.loads(r["embedding"]), dtype=np.float32)
        vecs.append(emb)
        meta.append({k: r[k] for k in
            ["chunk_id","data_id","document_title","chapter","section_title",
             "disease_name","knowledge_type","chunk_text"]})
    _rtl._all_vecs = np.stack(vecs)
    _rtl._all_meta = meta
    corpus = [_rtl._tokenize_ko(_rtl._clean_content(c["chunk_text"])) for c in meta]
    _rtl._bm25_index = BM25Okapi(corpus)
    _rtl._bm25_meta  = meta
    print(f"[DB] 로드 완료: {len(meta):,}개 청크")


async def embed(text: str) -> np.ndarray:
    resp = await CLIENT.embeddings.create(
        model="text-embedding-3-small", input=[text[:8000]]
    )
    return np.array(resp.data[0].embedding, dtype=np.float32)


async def main():
    await load_db()

    with open(DATASET) as f:
        data = json.load(f)

    good = [d for d in data if d.get("quality") == "good"]
    print(f"[데이터] good 품질: {len(good)}개")

    results = []
    sem = asyncio.Semaphore(BATCH)
    done = {"n": 0}

    async def process(item):
        async with sem:
            question = item["question"]
            try:
                qvec = await embed(question)
                # dense 유사도만 계산 (retrieve_all 대신 직접)
                norms = np.linalg.norm(_rtl._all_vecs, axis=1)
                qnorm = np.linalg.norm(qvec)
                sims = (_rtl._all_vecs @ qvec) / (norms * qnorm + 1e-8)
                top1_sim = float(np.max(sims))
            except Exception as e:
                top1_sim = -1.0

            done["n"] += 1
            if done["n"] % 200 == 0:
                print(f"  [{done['n']}/{len(good)}] 진행 중...")

            return {
                "conversation_id": item.get("conversation_id"),
                "question": question,
                "disease_name": item.get("disease_name"),
                "top1_sim": top1_sim,
            }

    tasks = [process(item) for item in good]
    for coro in asyncio.as_completed(tasks):
        r = await coro
        results.append(r)

    results.sort(key=lambda x: x["top1_sim"], reverse=True)

    with open(OUT, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total = len(results)
    over06 = sum(1 for r in results if r["top1_sim"] >= 0.6)
    over05 = sum(1 for r in results if r["top1_sim"] >= 0.5)
    print(f"\n[결과]")
    print(f"  전체       : {total}개")
    print(f"  0.6 이상   : {over06}개 ({over06/total*100:.1f}%)")
    print(f"  0.5 이상   : {over05}개 ({over05/total*100:.1f}%)")
    print(f"\n[저장] {OUT}")

if __name__ == "__main__":
    asyncio.run(main())

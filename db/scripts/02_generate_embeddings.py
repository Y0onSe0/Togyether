"""
02_generate_embeddings.py
multilingual-e5-large 임베딩 생성 후 JSON 저장

선행 연구와의 차이:
  선행: OpenAI API 호출 (비용 발생, 인터넷 필요)
  우리: 로컬 모델 실행 (무료, 오프라인 가능)

실행:
    python 02_generate_embeddings.py               ← 전체
    python 02_generate_embeddings.py --target disease
    python 02_generate_embeddings.py --target faq
    python 02_generate_embeddings.py --target vacc
    python 02_generate_embeddings.py --target consult
    python 02_generate_embeddings.py --limit 50    ← 테스트용
"""

import sys
import json
import argparse
import re
from pathlib import Path
from collections import defaultdict

sys.path.append(str(Path(__file__).parent))
from config import (
    DISEASE_INFO_FILE, FAQ_FILE, DPORTAL_FAQ_FILE, VACC_INFO_FILE,
    CONSULTATION_FILE,
    EMBED_DISEASE_FILE, EMBED_FAQ_FILE, EMBED_VACC_FILE, EMBED_CONSULT_FILE,
)
from modules.embedder import embed_texts


# ── 1. 감염병 정보 임베딩 ──────────────────────────────────────────────────
def generate_disease_embeddings(limit: int = None):
    print("\n[임베딩] 감염병 정보 (disease_info)")

    with open(DISEASE_INFO_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if limit:
        data = data[:limit]

    # text 필드가 없으면 content 사용
    texts = [doc.get("text") or doc.get("content", "") for doc in data]
    embeddings = embed_texts(texts, prefix="passage")

    for doc, emb in zip(data, embeddings):
        doc["embedding"] = emb

    with open(EMBED_DISEASE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  ✓ {len(data)}개 저장 → {EMBED_DISEASE_FILE.name}")


# ── 2. FAQ 임베딩 ──────────────────────────────────────────────────────────
def generate_faq_embeddings(limit: int = None):
    print("\n[임베딩] FAQ")

    items = []
    for path, source in [(FAQ_FILE, "kdca_faq"), (DPORTAL_FAQ_FILE, "kdca_dportal_faq")]:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        for item in d.get("items", []):
            items.append({**item, "source": source})

    if limit:
        items = items[:limit]

    texts = [
        f"{it.get('category', '')} FAQ {it.get('question', '')} {it.get('answer', '')}"
        for it in items
    ]
    embeddings = embed_texts(texts, prefix="passage")

    result = []
    for idx, (item, emb) in enumerate(zip(items, embeddings), start=1):
        result.append({
            "id":        f"faq_{idx:04d}",
            "category":  item.get("category", ""),
            "question":  item.get("question", ""),
            "answer":    item.get("answer",   ""),
            "source":    item.get("source",   ""),
            "embedding": emb,
        })

    with open(EMBED_FAQ_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  ✓ {len(result)}개 저장 → {EMBED_FAQ_FILE.name}")


# ── 3. 예방접종 정보 임베딩 ───────────────────────────────────────────────
def generate_vacc_embeddings(limit: int = None):
    print("\n[임베딩] 예방접종 정보")

    with open(VACC_INFO_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = list(data.items())
    if limit:
        items = items[:limit]

    texts = []
    for vacc_name, info in items:
        paragraphs = info.get("paragraphs", [])
        table_lines = []
        for table in info.get("tables", []):
            for row in table:
                if len(row) == 2:
                    table_lines.append(f"{row[0]}: {row[1]}")
        body = " ".join(paragraphs + table_lines)
        texts.append(f"예방접종 {vacc_name} {body}")

    embeddings = embed_texts(texts, prefix="passage")

    result = []
    for idx, ((vacc_name, info), emb) in enumerate(zip(items, embeddings), start=1):
        result.append({
            "id":          f"vacc_info_{idx:03d}",
            "vaccine_name": vacc_name,
            "embedding":   emb,
        })

    with open(EMBED_VACC_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  ✓ {len(result)}개 저장 → {EMBED_VACC_FILE.name}")


# ── 4. 상담 사례 임베딩 ───────────────────────────────────────────────────
def generate_consult_embeddings(limit: int = None):
    print("\n[임베딩] 상담 사례")

    with open(CONSULTATION_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # 대화셋 단위로 묶기
    sessions = defaultdict(list)
    for row in raw_data:
        sessions[row["대화셋일련번호"]].append(row)

    session_list = list(sessions.items())
    if limit:
        session_list = session_list[:limit]

    # 각 세션을 문서로 변환
    docs = []
    for idx, (session_id, rows) in enumerate(session_list, start=1):
        intents = list(dict.fromkeys(
            r["고객의도"].strip() for r in rows if r.get("고객의도", "").strip()
        ))
        category   = rows[0].get("카테고리", "")
        source_file = rows[0].get("출처파일", "")

        turns = []
        for row in rows:
            speaker = row["화자"]
            q = row.get("고객질문(요청)", "").strip()
            a = row.get("상담사답변",     "").strip()
            if speaker == "고객"   and q:
                turns.append(f"고객: {q}")
            elif speaker == "상담사" and a:
                turns.append(f"상담사: {a}")

        content = "\n".join(turns)
        text    = f"{' '.join(intents)} " + " ".join(
            r.get("고객질문(요청)", "") for r in rows if r["화자"] == "고객"
        )
        main_intent = intents[1] if len(intents) > 1 else (intents[0] if intents else session_id)
        keywords    = list({
            w for w in re.findall(r'[가-힣]{2,}', text) if len(w) >= 2
        })[:15]

        docs.append({
            "id":          f"consult_doc_{idx:04d}",
            "session_id":  session_id,
            "category":    category,
            "title":       f"{category} - {main_intent}" if category else main_intent,
            "content":     content,
            "text":        text,
            "intents":     intents,
            "keywords":    keywords,
            "metadata":    {"turn_count": len(turns), "source_file": source_file},
            "source":      "kdca_callcenter",
        })

    # 임베딩 생성 (text 필드 기준)
    texts = [doc["text"] for doc in docs]
    embeddings = embed_texts(texts, prefix="passage")

    for doc, emb in zip(docs, embeddings):
        doc["embedding"] = emb

    with open(EMBED_CONSULT_FILE, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)

    print(f"  ✓ {len(docs)}개 저장 → {EMBED_CONSULT_FILE.name}")


# ── 메인 ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        choices=["disease", "faq", "vacc", "consult", "all"],
        default="all",
        help="임베딩 대상 선택"
    )
    parser.add_argument("--limit", type=int, default=None, help="테스트용 제한 수")
    args = parser.parse_args()

    targets = (
        ["disease", "faq", "vacc", "consult"]
        if args.target == "all"
        else [args.target]
    )

    for t in targets:
        if t == "disease":
            generate_disease_embeddings(args.limit)
        elif t == "faq":
            generate_faq_embeddings(args.limit)
        elif t == "vacc":
            generate_vacc_embeddings(args.limit)
        elif t == "consult":
            generate_consult_embeddings(args.limit)

    print("\n✓ 임베딩 생성 완료")


if __name__ == "__main__":
    main()

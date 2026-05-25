#!/usr/bin/env python3
"""
embed_and_merge.py

post_process_embed.py 로 embed_text/chunk_text가 정비된 parsed 파일 전체를
임베딩 생성 후 knowledge_chunks_embedded_v2.json 으로 저장.

교체 대상(REPLACE_IDS): 원본 JSON에서 해당 data_id를 제거하고 새 버전으로 대체.
DATA_16 (data_id 미정)은 원본 그대로 유지.

출력: C:/Users/jys72/Downloads/knowledge_chunks_embedded_v2.json
"""

import sys
import json
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from modules.embedder import embed_texts

# ── 경로 ─────────────────────────────────────────────────────────────────────
PARSED_DIR = Path(__file__).parent / "parsed"
ORIG_FILE  = Path(r"C:\Users\jys72\Downloads\knowledge_chunks_embedded.json")
OUT_FILE   = Path(r"C:\Users\jys72\Downloads\knowledge_chunks_embedded_v2.json")

# 임베딩할 파일 (data_id → parsed json 경로)
# DATA-006/007은 post_process_embed.py 스킵 대상이지만 재파싱 완료 → 재임베딩 포함
TO_EMBED: dict[str, Path] = {
    "DATA-001": PARSED_DIR / "DATA_001_chunks_covid.json",
    "DATA-002": PARSED_DIR / "DATA_002_chunks_diagnostic.json",
    "DATA-003": PARSED_DIR / "DATA_003_chunks_dupest.json",
    "DATA-004": PARSED_DIR / "DATA_004_chunks_hiv.json",
    "DATA-005": PARSED_DIR / "DATA_005_chunks_mers.json",
    "DATA-006": PARSED_DIR / "DATA_006_chunks_tb.json",
    "DATA-007": PARSED_DIR / "DATA_007_chunks_vhf.json",
    "DATA-008": PARSED_DIR / "DATA_008_chunks_질병관리청_FAQ.json",
    "DATA-009": PARSED_DIR / "DATA_009_chunks_crawl.json",
    "DATA-010": PARSED_DIR / "DATA_010_chunks_faq.json",
    "DATA-011": PARSED_DIR / "DATA_011_chunks_hiv_system.json",
    "DATA-012": PARSED_DIR / "DATA_012_chunks_covid19_system.json",
    "DATA-013": PARSED_DIR / "DATA_013_chunks_tb_system.json",
    "DATA-014": PARSED_DIR / "DATA_014_chunks_tb_hospital.json",
}

# 원본에서 제거할 data_id 집합
# DATA-015/016/017 = 원본 JSON의 구버전 ID
# (DATA-010/013/014로 재번호 매겨진 동일 컨텐츠)
REPLACE_IDS = set(TO_EMBED.keys()) | {"DATA-015", "DATA-016", "DATA-017"}


def embed_chunks(chunks: list[dict]) -> list[dict]:
    """embed_text 필드로 임베딩 생성 후 embedding 필드 채움."""
    texts = [c.get("embed_text") or c.get("chunk_text") or c.get("content", "") for c in chunks]
    embeddings = embed_texts(texts, prefix="passage")
    for chunk, emb in zip(chunks, embeddings):
        chunk["embedding"] = emb
    return chunks


def main():
    # 1. 원본 로드 (DATA_16 등 교체 대상이 아닌 것만 유지)
    print(f"[1] 원본 로드: {ORIG_FILE.name}")
    orig = json.loads(ORIG_FILE.read_text(encoding='utf-8'))
    orig_kept = [c for c in orig if c.get("data_id") not in REPLACE_IDS]
    print(f"    전체 {len(orig)}개 → 교체 대상 제외 후 {len(orig_kept)}개 유지")

    new_chunks: list[dict] = []

    # 2. 각 parsed 파일 임베딩 생성
    for step, (data_id, path) in enumerate(TO_EMBED.items(), start=2):
        if not path.exists():
            print(f"\n[{step}] {data_id} SKIP (파일 없음): {path.name}")
            continue
        raw_chunks = json.loads(path.read_text(encoding='utf-8'))
        print(f"\n[{step}] {data_id} 임베딩 생성: {path.name} ({len(raw_chunks)}개)")
        raw_chunks = embed_chunks(raw_chunks)
        new_chunks.extend(raw_chunks)
        print(f"    ✓ {len(raw_chunks)}개 완료")

    # 3. 병합: 유지된 원본 + 새 버전
    merged = orig_kept + new_chunks
    print(f"\n[병합] {len(orig_kept)} (유지) + {len(new_chunks)} (신규) = {len(merged)}개")

    # data_id별 카운트
    from collections import Counter
    cnt = Counter(c.get("data_id") for c in merged)
    for did in sorted(cnt):
        print(f"    {did}: {cnt[did]}개")

    # 4. 저장
    print(f"\n[저장] {OUT_FILE}")
    OUT_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')
    size_mb = OUT_FILE.stat().st_size / 1024 / 1024
    print(f"    ✓ 완료 ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()

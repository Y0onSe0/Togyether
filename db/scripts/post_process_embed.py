#!/usr/bin/env python3
"""
post_process_embed.py

embed_text / chunk_text 일괄 후처리.

embed_text 재생성 규칙:
    disease > chapter > section_title: clean(content[:400])
    - C1 제어문자 제거 (\x80-\x9f)
    - 특수 불릿 → 공백 (⚫⦁∙◦○▪•∘❖ 등)
    - 줄바꿈 → 공백
    - 연속 공백 → 단일 공백

chunk_text 클린 규칙:
    - C1 제어문자 제거
    - 줄 시작 특수 불릿 → '- '
    - 줄 중간 특수 불릿(공백 포함) → ' - '

스킵: DATA-006, DATA-007, DATA_16 (이미 수정 완료 / 알 수 없는 포맷)
FAQ 모드 (DATA-008, DATA-010): embed_text 기존 구조 유지, 클린만 적용
"""

import sys
import re
import json
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PARSED_DIR = Path(__file__).parent / "parsed"

# ── 스킵 대상 ─────────────────────────────────────────────────────────────────
SKIP_FILES = {
    "DATA_006_chunks_tb.json",       # 이미 재파싱 완료
    "DATA_007_chunks_vhf.json",      # 이미 재파싱 완료
    "DATA_16_acw_cards_all.json",    # 알 수 없는 포맷
    "mock_agents.json",
    "mock_calls.json",
}

# FAQ 포맷 (embed_text 구조 유지, 클린만)
FAQ_FILES = {
    "DATA_008_chunks_질병관리청_FAQ.json",
    "DATA_010_chunks_faq.json",
}

# ── 정규식 ─────────────────────────────────────────────────────────────────────
C1_RE     = re.compile(r'[\x80-\x9f]')
BULLET_RE = re.compile(r'[⚫⦁∙◦○▪•∘❖➤→►▶◆●■□△▽★☆※❑✓✔✗✘]')
NL_RE     = re.compile(r'[ \t]*\n[ \t]*')
MULTI_SP  = re.compile(r'[ \t]{2,}')

# chunk_text용: 줄 시작 불릿
BULLET_LINE_START = re.compile(
    r'(?m)^[⚫⦁∙◦○▪•∘❖➤→►▶◆●■□△▽★☆※❑✓✔✗✘]+\s*'
)
# chunk_text용: 나머지 불릿 (줄 중간, 위치 무관)
BULLET_REMAIN = re.compile(
    r'[⚫⦁∙◦○▪•∘❖➤→►▶◆●■□△▽★☆※❑✓✔✗✘]'
)

CONTENT_LIMIT = 400   # embed_text에 포함할 content 최대 길이


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _clean_for_embed(text: str) -> str:
    """embed_text용 텍스트 클린: C1·불릿 제거, 줄바꿈→공백, 연속공백 제거."""
    if not text:
        return ""
    text = C1_RE.sub("", text)
    text = BULLET_RE.sub(" ", text)
    text = NL_RE.sub(" ", text)
    text = MULTI_SP.sub(" ", text)
    return text.strip()


def _clean_for_chunk(text: str) -> str:
    """chunk_text용 텍스트 클린: C1 제거, 줄 시작 불릿 → '- ', 나머지 불릿 → 공백."""
    if not text:
        return ""
    text = C1_RE.sub("", text)
    # 줄 시작 불릿 → '- ' (리스트 구조 보존)
    text = BULLET_LINE_START.sub("- ", text)
    # 나머지 위치 불릿 → 공백 (표 내부, 줄 중간 등)
    text = BULLET_REMAIN.sub(" ", text)
    return text


def _clean_label(text: str) -> str:
    """prefix 라벨(disease/chapter/section) 클린: C1·불릿 제거, 연속공백 정리."""
    if not text:
        return ""
    text = C1_RE.sub("", text)
    text = BULLET_RE.sub(" ", text)
    text = MULTI_SP.sub(" ", text)
    return text.strip()


def _build_embed(chunk: dict) -> str:
    """
    embed_text 재생성:
        disease > chapter > section_title: clean(content[:400])
    prefix 라벨과 content 모두 클린 적용.
    """
    disease = _clean_label(chunk.get("disease_name") or "")
    chapter = _clean_label(chunk.get("chapter") or "")
    section = _clean_label(chunk.get("section_title") or "")
    content = (chunk.get("content") or "").strip()

    parts: list[str] = []
    if disease and disease.lower() != "none":
        parts.append(disease)
    if chapter:
        parts.append(chapter)
    # section이 chapter와 동일하면 중복 제거
    if section and section != chapter:
        parts.append(section)

    prefix = " > ".join(parts)
    clean_content = _clean_for_embed(content)[:CONTENT_LIMIT]

    if prefix:
        return f"{prefix}: {clean_content}"
    return clean_content


def _clean_embed_faq(text: str) -> str:
    """FAQ embed_text: 기존 구조 유지, 클린만."""
    return _clean_for_embed(text)


# ── 파일 처리 ──────────────────────────────────────────────────────────────────

def process_file(path: Path, faq_mode: bool) -> tuple[int, int]:
    """
    파일을 읽어 embed_text·chunk_text를 수정 후 덮어쓴다.
    반환: (embed_changed_count, chunk_changed_count)
    """
    raw = path.read_text(encoding="utf-8")
    chunks: list[dict] = json.loads(raw)

    if not chunks:
        return 0, 0

    data_id = chunks[0].get("data_id", "")
    if data_id in {"DATA-006", "DATA-007"}:
        print(f"  [SKIP data_id={data_id}]")
        return 0, 0

    embed_changed = chunk_changed = 0

    for c in chunks:
        # ── embed_text ─────────────────────────────────────────────────────────
        old_embed = c.get("embed_text") or ""
        new_embed = _clean_embed_faq(old_embed) if faq_mode else _build_embed(c)

        if new_embed != old_embed:
            c["embed_text"] = new_embed
            embed_changed += 1

        # ── chunk_text ─────────────────────────────────────────────────────────
        old_chunk = c.get("chunk_text") or ""
        new_chunk = _clean_for_chunk(old_chunk)

        if new_chunk != old_chunk:
            c["chunk_text"] = new_chunk
            chunk_changed += 1

    # 제자리 덮어쓰기 (필드 순서 등 구조 보존: json.dumps + indent=2)
    path.write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return embed_changed, chunk_changed


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    json_files = sorted(PARSED_DIR.glob("DATA_*.json"))

    total_embed = total_chunk = 0
    for path in json_files:
        fname = path.name

        if fname in SKIP_FILES:
            print(f"[SKIP ] {fname}")
            continue

        faq_mode = fname in FAQ_FILES
        tag = "FAQ " if faq_mode else "PROC"
        print(f"[{tag}] {fname}", end=" ... ", flush=True)

        try:
            ec, cc = process_file(path, faq_mode)
            print(f"embed={ec:4d}건 수정, chunk={cc:4d}건 수정")
            total_embed += ec
            total_chunk += cc
        except Exception as exc:
            print(f"ERROR: {exc}")

    print()
    print(f"완료: embed_text {total_embed}건, chunk_text {total_chunk}건 수정")
    print()
    print("※ 임베딩 재생성 필요: embed_and_merge.py 실행 (DATA-001~005, 007~014 포함)")


if __name__ == "__main__":
    main()

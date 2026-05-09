"""
parsers/DATA_006_parse_tb.py
2026 국가결핵관리지침 PDF → 3단계 계층 청킹 → JSON 저장

PDF 구조 (674페이지):
  PART Ⅰ   국가결핵관리사업
  PART Ⅱ   결핵 감시체계
  PART Ⅲ   결핵 역학조사
  PART Ⅳ   결핵의 검사
  PART Ⅴ   결핵환자 맞춤형 통합관리
  PART Ⅵ   대상별 결핵환자 관리
  PART Ⅶ   잠복결핵감염 검진 및 치료
  PART Ⅷ   인수공통결핵관리
  PART Ⅸ   결핵 검진 사업
  PART Ⅹ   결핵예방 홍보
  PART ⅩⅠ  결핵 치료제 등 수급관리
  PART ⅩⅡ  (국가결핵감시체계)
  PART ⅩⅢ  결 핵  (각론 — 병원체·임상·진단·치료)
  PART ⅩⅣ  부 록  ← 제외 (DATA-016/017과 분리)

PDF 노이즈:
  - 매 페이지 running header "2026 국가결핵관리지침" + "PART Ⅰ. 결핵관리사업" 반복
  - 해결: split_by_part() 후 merge_parts() 로 같은 PART 병합

청킹 단위: 절 → 숫자항목 → 800자 초과 시 문장 분할

출력: parsed/DATA_006_chunks_tb.json

실행:
    python parsers/DATA_006_parse_tb.py           ← JSON 저장
    python parsers/DATA_006_parse_tb.py --preview ← 샘플 출력만
    python parsers/DATA_006_parse_tb.py --toc     ← PART/절 구조만 출력
"""

import sys
import re
import json
from collections import Counter
import argparse
from pathlib import Path

import pdfplumber

sys.path.append(str(Path(__file__).parent.parent))
from config import GUIDELINE_PDF_DIR, CHUNK_SIZE

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 설정 ─────────────────────────────────────────────────────────────────
PDF_FILENAME = "2026 국가결핵관리지침.pdf"
PDF_PATH     = GUIDELINE_PDF_DIR / "완료" / PDF_FILENAME
DOC_TITLE    = "2026 국가결핵관리지침"
DISEASE_NAME     = "결핵"
OUTPUT_DIR       = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE      = OUTPUT_DIR / "DATA_006_chunks_tb.json"
DATA_ID          = "DATA-006"
SOURCE_CATEGORY  = "disease"
KNOWLEDGE_TYPE   = "disease_guideline"

# 목차/표지 스킵 (실제 본문 PART Ⅰ 시작 위치 ~15,353자)
TOC_END_POS = 14_500

# ── 제외 PART ────────────────────────────────────────────────────────────────
# 헤더 텍스트가 running-header 내용으로 덮여 "부록" 대신 절 제목이 올 수 있으므로
# 로마 숫자 키로도 직접 스킵
_SKIP_PART_KEYS: set[str] = {'ⅩⅣ'}          # PART ⅩⅣ 부록 (DATA-016/017)
_SKIP_PART_RE = [
    re.compile(r'부\s*록'),                    # 헤더에 "부록" 포함 시 대비
]


def skip_part(p: dict) -> bool:
    """해당 PART를 파싱에서 제외할지 판단."""
    key = normalize_part_key(p['header'])
    if key in _SKIP_PART_KEYS:
        return True
    return any(pat.search(p['header']) for pat in _SKIP_PART_RE)

# ── 헤더 정규식 ───────────────────────────────────────────────────────────
ROMAN_CHARS = 'ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ'

# PART 단위: "PART Ⅰ", "PART Ⅰ. 국가결핵관리사업", "PART Ⅰ. 국가결핵관리사업 | 제1절..."
PART_HDR_RE = re.compile(
    rf'^PART\s+[{ROMAN_CHARS}]+[^\n]{{0,80}}$',
    re.MULTILINE,
)

# 절 단위: "제1절 결핵 개요" / "제 1 절 ..."
SECT_HDR_RE = re.compile(
    r'^제\s*\d+\s*절[\.\s　 　][^\n]{0,80}$',
    re.MULTILINE,
)

# 숫자 단위: "1. 결핵이란"
NUM_HDR_RE = re.compile(
    r'^(\d{1,2})\.\s+([^\n]{1,80})$',
    re.MULTILINE,
)

# ── 노이즈 제거 패턴 ─────────────────────────────────────────────────────
SIDEBAR_PATTERNS = [
    # 페이지 헤더
    re.compile(r'^2026\s*국가결핵관리지침\s*$',       re.MULTILINE),
    re.compile(r'^국가결핵관리[^\n]{0,20}$',           re.MULTILINE),
    re.compile(r'^결핵관리[^\n]{0,20}$',              re.MULTILINE),
    re.compile(r'^Tuberculosis[^\n]{0,30}$',          re.MULTILINE),
    re.compile(r'^TB[^\n]{0,20}$',                    re.MULTILINE),
    re.compile(r'^www\.kdca\.go\.kr[^\n]*$',           re.MULTILINE),
    # 숫자/단독 한 글자 (페이지번호·세로 사이드바)
    re.compile(r'^\s*\d+\s*$',                        re.MULTILINE),
    re.compile(r'^\s*[가-힣]\s*$',                     re.MULTILINE),
    # 병합 후 본문 내 잔존 PART 러닝헤더 제거
    re.compile(rf'^PART\s+[{ROMAN_CHARS}]+[^\n]*$',  re.MULTILINE),
    # 본문 중간에 남는 사이드바 Roman numeral 라벨 (예: 'Ⅰ', 'Ⅴ' 단독 줄)
    re.compile(rf'^[{ROMAN_CHARS}]+\s*$',             re.MULTILINE),
    # 섹션 라벨 단독 줄
    re.compile(r'^\s*총론\s*$',                        re.MULTILINE),
    re.compile(r'^\s*각론\s*$',                        re.MULTILINE),
    re.compile(r'^\s*부록\s*$',                        re.MULTILINE),
    # 흐름도 화살표 단독 줄
    re.compile(r'^\s*[↓↑→←↔▶▷▼▲∘∙]\s*$',           re.MULTILINE),
]

_SENT_END_RE = re.compile(r'(?<=[다요함됨임])\.\s+')

STOPWORDS = {
    '관련', '통해', '경우', '대한', '따른', '위한', '통한', '기반',
    '따라서', '그러나', '하지만', '또한', '그리고', '이후', '이전',
    '이내', '이상', '이하', '가지', '있는', '있음', '있으며', '되어',
    '이를', '위해', '모든', '각각', '이후에', '경우에',
    '관리', '지침', '개요', '현황', '특성', '절차', '정의', '목적',
    '대상', '범위', '내용', '방향', '원칙', '기본', '방법', '기준',
    '환자', '발생', '실시', '진행', '시행', '사용', '여부', '수행',
    '제공', '확인', '통보', '신고', '조치', '판단', '검토', '결과',
    '수준', '기간', '필요', '해당', '포함',
    '질병관리청', '감염병', '대응지침', '관리지침',
    '결핵',
}


# ── 유틸 ─────────────────────────────────────────────────────────────────

def remove_nul(text: str) -> str:
    return text.replace('\x00', '')


def clean_header(text: str) -> str:
    """헤더에서 목차 점선/페이지 번호 제거."""
    text = re.sub(r'[\s·.]{2,}\d*\s*$', '', text)
    text = re.sub(r'\s+\d+\s*$', '', text)
    # | 이후 절 정보 제거 (러닝 헤더 "PART Ⅰ. xxx | 제1절 yyy" → "PART Ⅰ. xxx")
    text = re.sub(r'\s*\|\s*제\s*\d+\s*절.*$', '', text)
    return text.strip()


def clean_text(text: str) -> str:
    """사이드바·러닝헤더 제거 후 공백 정리."""
    for pat in SIDEBAR_PATTERNS:
        text = pat.sub('', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_pdf_text(pdf_path: Path) -> str:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        print(f"  총 {len(pdf.pages)}페이지")
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(remove_nul(text.strip()))
    return "\n\n".join(pages)


# ── PART 분리 + 병합 ──────────────────────────────────────────────────────

def normalize_part_key(header: str) -> str:
    """
    PART 헤더에서 로마 숫자 추출 (병합 키).
    "PART Ⅰ. 국가결핵관리사업 | 제1절 ..." → "Ⅰ"

    Unicode 단일 코드포인트(Ⅺ U+216A, Ⅻ U+216B)와
    두 글자 조합(ⅩⅠ, ⅩⅡ)을 동일 키로 정규화.
    """
    m = re.match(rf'PART\s+([{ROMAN_CHARS}]+)', header)
    if not m:
        return header[:10]
    key = m.group(1)
    # Ⅺ = U+216A ↔ ⅩⅠ = Ⅹ+Ⅰ, Ⅻ = U+216B ↔ ⅩⅡ = Ⅹ+Ⅱ
    key = key.replace('ⅩⅡ', 'Ⅻ').replace('ⅩⅠ', 'Ⅺ')
    return key


def split_by_part(text: str) -> list[dict]:
    """PART 헤더 기준 분리 (raw 텍스트에서 호출)."""
    matches = list(PART_HDR_RE.finditer(text))
    if not matches:
        return [{'header': '전체', 'body': text.strip()}]

    sections = []
    for i, m in enumerate(matches):
        header = clean_header(m.group(0).strip())
        start  = m.start()
        end    = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body   = text[start:end].strip()
        if len(body) > 30:
            sections.append({'header': header, 'body': body})
    return sections


_SECT_IN_HDR_RE = re.compile(r'제\s*\d+\s*절')  # 헤더 내 절 정보 포함 여부

def merge_parts(sections: list[dict]) -> list[dict]:
    """
    같은 PART 키의 섹션을 병합.
    매 페이지 러닝 헤더로 인해 쪼개진 수백 개 섹션 → 14개 PART로 합침.

    헤더 선택 우선순위:
      1) 절 정보(제N절) 없는 헤더 선호
      2) 동등 조건이면 더 긴 헤더 선택
      → 예: "PART ⅩⅣ. 부 록" > "PART ⅩⅣ. 제1절 결핵관리종합계획"
    """
    merged: dict[str, dict] = {}
    order:  list[str]       = []

    for s in sections:
        key    = normalize_part_key(s['header'])
        header = s['header']

        if key not in merged:
            merged[key] = {'header': header, 'body': s['body']}
            order.append(key)
        else:
            existing   = merged[key]['header']
            new_clean  = not _SECT_IN_HDR_RE.search(header)
            old_clean  = not _SECT_IN_HDR_RE.search(existing)
            # 절 정보 없는 새 헤더가 더 우선
            if new_clean and not old_clean:
                merged[key]['header'] = header
            elif new_clean and old_clean and len(header) > len(existing):
                merged[key]['header'] = header
            merged[key]['body'] += '\n\n' + s['body']

    return [merged[k] for k in order]


# ── 절/숫자 분리 ──────────────────────────────────────────────────────────

def split_by_section(text: str) -> list[dict]:
    """절 단위 분리 (clean_text 이후 호출)."""
    matches = list(SECT_HDR_RE.finditer(text))
    if not matches:
        return [{'header': '', 'body': text.strip()}]

    sections = []
    intro = text[:matches[0].start()].strip()
    if intro and len(intro) > 20:
        sections.append({'header': '', 'body': intro})

    for i, m in enumerate(matches):
        header = clean_header(m.group(0).strip())
        start  = m.start()
        end    = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body   = text[start:end].strip()
        if len(body) > 20:
            sections.append({'header': header, 'body': body})
    return sections


def split_by_number(text: str) -> list[dict]:
    """숫자항목 단위 분리 (최소 청크)."""
    matches = list(NUM_HDR_RE.finditer(text))
    if not matches:
        return [{'header': '', 'body': text.strip(), 'num': 0}]

    sections = []
    intro = text[:matches[0].start()].strip()
    if intro and len(intro) > 20:
        sections.append({'header': '', 'body': intro, 'num': 0})

    for i, m in enumerate(matches):
        num    = int(m.group(1))
        title  = clean_header(m.group(2))
        # 숫자 제목이 숫자로 시작하면 날짜/잔여물로 간주 스킵
        if re.match(r'^\d', title):
            continue
        header = f"{num}. {title}"
        start  = m.start()
        end    = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body   = text[start:end].strip()
        if len(body) > 20:
            sections.append({'header': header, 'body': body, 'num': num})
    return sections


# ── 크기 정제 ─────────────────────────────────────────────────────────────

def refine_content(text: str, max_size: int = CHUNK_SIZE) -> list[str]:
    if len(text) <= max_size:
        return [text] if text.strip() else []
    sentences = _SENT_END_RE.split(text)
    result, chunk = [], ''
    for sent in sentences:
        if len(chunk) + len(sent) + 1 <= max_size:
            chunk = (chunk + ' ' + sent).strip()
        else:
            if chunk:
                result.append(chunk)
            if len(sent) > max_size:
                for i in range(0, len(sent), max_size):
                    result.append(sent[i:i + max_size].strip())
                chunk = ''
            else:
                chunk = sent
    if chunk:
        result.append(chunk)
    return [r for r in result if r.strip()]


# ── 키워드 / 임베딩 유틸 ─────────────────────────────────────────────────

def extract_keywords(text: str, max_kw: int = 10) -> list[str]:
    kor_words = re.findall(r'[가-힣]{2,}', text)
    eng_words = re.findall(r'\b[A-Z]{2,}\b', text)
    freq = Counter(
        w for w in kor_words + eng_words
        if w not in STOPWORDS
    )
    return [w for w, _ in freq.most_common(max_kw)]


def build_embed_text(disease_name: str, section_title: str, content: str) -> str:
    parts = [p for p in [disease_name, section_title] if p]
    header = ' '.join(parts)
    combined = f"{header}: {content}" if header else content
    return combined[:500]


def is_garbage_chunk(content: str) -> bool:
    kor_chars = len(re.findall(r'[가-힣]', content))
    if kor_chars < 30:
        return True
    total = len(content.replace(' ', '').replace('\n', ''))
    if total > 0 and kor_chars / total < 0.4:
        return True
    return False


# ── 청크 빌더 ─────────────────────────────────────────────────────────────

def build_chunks(full_text: str) -> list[dict]:
    """
    ① split_by_part (raw) → ② merge_parts → ③ clean_text per-PART
    → ④ split_by_section → ⑤ split_by_number → ⑥ refine_content
    """
    body = full_text[TOC_END_POS:]

    # ① raw 텍스트에서 PART 분리
    raw_parts = split_by_part(body)

    # ② 같은 PART 병합 (러닝 헤더 제거)
    merged_parts = merge_parts(raw_parts)

    # 제외 PART 필터링
    target_parts = []
    for p in merged_parts:
        target_parts.append((p, skip_part(p)))

    print(f"\n  [구조] 병합 후 PART {len(merged_parts)}개")
    for p, skip in target_parts:
        flag = '⏭️  스킵' if skip else '✅'
        print(f"    {flag}  {p['header'][:70]}")

    target_parts = [p for p, skip in target_parts if not skip]
    print(f"\n  [필터] 파싱 대상: {len(target_parts)}개 PART\n")

    chunks     = []
    global_idx = 0

    for part in target_parts:
        part_title = part['header']

        # ③ PART 별로 clean_text (분리 후 정제)
        part_body = clean_text(part['body'])

        # ④ 절 분리
        sect_sections = split_by_section(part_body)
        print(f"  {part_title[:55]}  →  절 {len(sect_sections)}개")

        for sect in sect_sections:
            sect_title  = sect['header']
            num_sections = split_by_number(sect['body'])

            for num_sec in num_sections:
                num_title = num_sec['header']
                content   = num_sec['body']

                section_title = ' '.join(
                    filter(None, [sect_title, num_title])
                ).strip()

                sub_chunks = refine_content(content)

                for sub in sub_chunks:
                    sub = remove_nul(sub)
                    if not sub.strip() or len(sub) < 20:
                        continue

                    chunk_id   = f"tb_{global_idx:04d}"
                    chunk_text = f"{part_title} {DISEASE_NAME} {section_title}\n{sub}"

                    if is_garbage_chunk(sub):
                        global_idx += 1
                        continue

                    chunks.append({
                        'source_id':       chunk_id,
                        'data_id':         DATA_ID,
                        'source_category': SOURCE_CATEGORY,
                        'knowledge_type':  KNOWLEDGE_TYPE,
                        'disease_name':    DISEASE_NAME,
                        'document_title':  DOC_TITLE,
                        'chapter':         part_title,
                        'section_title':   section_title,
                        'content':         sub,
                        'chunk_text':      remove_nul(chunk_text),
                        'embed_text':      build_embed_text(DISEASE_NAME, section_title, sub),
                        'chunk_index':     global_idx,
                        'keywords':        extract_keywords(
                                               f"{part_title} {section_title} {sub}"
                                           ),
                        'source':          PDF_FILENAME,
                        'embedding':       None,
                    })
                    global_idx += 1

    return chunks


# ── 메인 ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='샘플 출력만, JSON 저장 없음')
    parser.add_argument('--toc',     action='store_true', help='PART/절 구조만 출력')
    args = parser.parse_args()

    print(f"[결핵 파서] 시작")
    print(f"  입력: {PDF_FILENAME}\n")

    if not PDF_PATH.exists():
        print(f"[오류] 파일 없음: {PDF_PATH}")
        return

    try:
        raw_text = extract_pdf_text(PDF_PATH)
    except Exception as e:
        print(f"[오류] 텍스트 추출 실패: {e}")
        return

    print(f"  추출 완료: {len(raw_text):,}자\n")

    # ① raw 텍스트에서 PART 분리 → 병합 (clean 전)
    body        = raw_text[TOC_END_POS:]
    raw_parts   = split_by_part(body)
    merged      = merge_parts(raw_parts)

    # 제외 필터
    targets = [p for p in merged if not skip_part(p)]

    if args.toc:
        print("── PART / 절 구조 (병합 후) ──────────────────────")
        for p in merged:
            skip = skip_part(p)
            flag = '⏭️ ' if skip else '✅'
            part_body = clean_text(p['body'])
            sects = split_by_section(part_body)
            print(f"\n  {flag} 📂  {p['header'][:75]}")
            for s in sects:
                if s['header']:
                    nums = split_by_number(s['body'])
                    print(f"      📄  {s['header'][:60]}  ({len(nums)}개 항목)")
        print(f"\n  파싱 대상: {len(targets)}개 PART / 전체: {len(merged)}개")
        return

    all_chunks = build_chunks(raw_text)
    total = len(all_chunks)
    print(f"\n[완료] 총 {total}개 청크\n")

    print("── 샘플 청크 (처음 5개) ────────────────────────")
    for c in all_chunks[:5]:
        print(f"  ID           : {c['source_id']}")
        print(f"  chapter      : {c['chapter']}")
        print(f"  section_title: {c['section_title']}")
        print(f"  content 길이 : {len(c['content'])}자")
        print(f"  chunk_text앞 : {c['chunk_text'][:80]!r}")
        print()

    if args.preview:
        print("[preview] JSON 저장 건너뜀")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    print(f"[완료] 저장: {OUTPUT_FILE}  ({total}청크)")


if __name__ == '__main__':
    main()

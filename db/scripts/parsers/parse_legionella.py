"""
parsers/parse_legionella.py
2025년도 레지오넬라증 관리지침 PDF
→ 총론/각론/환경관리 청킹 → JSON 저장

PDF 구조 (140페이지):
  전문/목차/개정이력
  단원 Ⅰ. 총론     (감시, 역학조사, 관리체계)
    1. 개요
    2. 수행 체계
    3. 감시 체계
    4. 검사 의뢰
    5. 역학조사
    6. 환자관리
  단원 Ⅱ. 각론     (레지오넬라증 기본 정보)
    1. 개요
    2. 병원체
    3. 발생현황
    4. 역학적 특성 및 임상 양상
    5. 실험실 검사
    6. 치료
    7. 예방
  단원 Ⅲ. 레지오넬라 환경관리
    1. 주요 시설 관계부처
    2. 일반 환경 관리
    3. 시설별 환경 관리
    4. 다중이용시설 레지오넬라증 환경검사 계획
    5. Q&A
  단원 Ⅳ. 부 록  ← 제외

출력: parsed/chunks_legionella.json

실행:
    python parsers/parse_legionella.py           ← JSON 저장
    python parsers/parse_legionella.py --preview ← 샘플 출력만
"""

import sys
import re
import json
import argparse
from pathlib import Path

import pdfplumber

sys.path.append(str(Path(__file__).parent.parent))
from config import GUIDELINE_PDF_DIR

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 설정 ─────────────────────────────────────────────────────────────────
PDF_FILENAME  = "2025년도 레지오넬라증 관리지침_05.pdf"
PDF_PATH      = GUIDELINE_PDF_DIR / "완료" / "총론-각론-부록" / PDF_FILENAME
DOC_TITLE     = "2025년도 레지오넬라증 관리지침"
DISEASE_NAME  = "레지오넬라증"
CONTENT_TYPE  = "management"
OUTPUT_DIR    = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE   = OUTPUT_DIR / "chunks_legionella.json"

# ── 섹션 경계 패턴 ───────────────────────────────────────────────────────
# 각 섹션 시작 마커 ("단원 Ⅰ. 총론" 등)
CHONRON_RE    = re.compile(r'단원\s*Ⅰ\.\s*총\s*론')
KAKRON_RE     = re.compile(r'단원\s*Ⅱ\.\s*각\s*론')
HWANKYUNG_RE  = re.compile(r'단원\s*Ⅲ\.\s*레지오넬라\s*환경\s*관리')
APPENDIX_RE   = re.compile(r'단원\s*Ⅳ\.\s*부\s*록')

# 서브섹션: "1 개요", "2 수행 체계" 등 (숫자 공백 한글)
# 레지오넬라는 "1. 개요" 와 "1 개요" 두 형식 혼재
SECTION_RE = re.compile(
    r'\n(\d+)[.\s]\s+([가-힣·\s&Q]{2,25})\n',
    re.MULTILINE
)

# 사이드바 노이즈 패턴
# 레지오넬라는 Ⅰ총론/Ⅱ각론/Ⅲ레지오넬라환경관리/Ⅳ부록 세로 사이드바가 있음
SIDEBAR_PATTERNS = [
    # 페이지 헤더
    re.compile(r'^2025년도 레지오넬라증 관리지침[^\n]*$', re.MULTILINE),
    re.compile(r'^www\.kdca\.go\.kr[^\n]*$', re.MULTILINE),
    # 페이지 번호 단독 줄
    re.compile(r'^\s*\d+\s*$', re.MULTILINE),
    # 세로 사이드바 글자 단독 줄
    re.compile(r'^\s*[ⅠⅡⅢ]\s*$', re.MULTILINE),
    re.compile(r'^\s*단원\s*$', re.MULTILINE),
    re.compile(r'^\s*총\s*$', re.MULTILINE),
    re.compile(r'^\s*론\s*$', re.MULTILINE),
    re.compile(r'^\s*각\s*$', re.MULTILINE),
    re.compile(r'^\s*부\s*$', re.MULTILINE),
    re.compile(r'^\s*록\s*$', re.MULTILINE),
    re.compile(r'^\s*레\s*$', re.MULTILINE),
    re.compile(r'^\s*지\s*$', re.MULTILINE),
    re.compile(r'^\s*오\s*$', re.MULTILINE),
    re.compile(r'^\s*넬\s*$', re.MULTILINE),
    re.compile(r'^\s*라\s*$', re.MULTILINE),
    re.compile(r'^\s*환\s*$', re.MULTILINE),
    re.compile(r'^\s*경\s*$', re.MULTILINE),
    re.compile(r'^\s*관\s*$', re.MULTILINE),
    re.compile(r'^\s*리\s*$', re.MULTILINE),
    re.compile(r'^\s*Ⅳ\s*$', re.MULTILINE),
    # 연속 사이드바 패턴
    re.compile(r'[ⅠⅡⅢⅣ]\s*\n\s*[총각부단]'),
    re.compile(r'\n총\n론\n'),
    re.compile(r'\n각\n론\n'),
    re.compile(r'\n부\n록\n'),
    # 레지오넬라 사이드바 연속 (레\n지\n오\n넬\n라\n환\n경\n관\n리)
    re.compile(r'레\n지\n오\n넬\n라\n환\n경\n관\n리'),
]


# ── NUL 제거 ─────────────────────────────────────────────────────────────
def remove_nul(text: str) -> str:
    return text.replace('\x00', '')


# ── 노이즈 제거 ──────────────────────────────────────────────────────────
def clean_text(text: str) -> str:
    for pat in SIDEBAR_PATTERNS:
        text = pat.sub('', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── PDF 전체 텍스트 추출 ──────────────────────────────────────────────────
def extract_full_text(pdf_path: Path) -> str:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        print(f"  총 {len(pdf.pages)}페이지")
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(remove_nul(text.strip()))
    return "\n\n".join(pages)


# ── 섹션 경계 탐색 (앵커 기반) ───────────────────────────────────────────
def _find_anchor(pattern: re.Pattern, text: str, after: int = 0) -> int | None:
    """
    pattern이 처음 매칭되는 위치를 after 이후에서 찾아 반환.
    None이면 미발견.
    """
    m = pattern.search(text, after)
    return m.start() if m else None


def split_sections(full_text: str) -> dict[str, str]:
    """
    단원별 텍스트 반환.
    keys: '총론', '각론', '환경관리'
    부록(단원 Ⅳ) 이후는 제외.
    """
    # 각 경계 위치 탐색 (처음 매칭 사용)
    p_chonron   = _find_anchor(CHONRON_RE,   full_text)
    p_kakron    = _find_anchor(KAKRON_RE,    full_text, (p_chonron or 0) + 100)
    p_hwankyung = _find_anchor(HWANKYUNG_RE, full_text, (p_kakron  or 0) + 100)
    p_appendix  = _find_anchor(APPENDIX_RE,  full_text, (p_hwankyung or 0) + 100)

    print(f"  단원 Ⅰ 총론    : pos={p_chonron}")
    print(f"  단원 Ⅱ 각론    : pos={p_kakron}")
    print(f"  단원 Ⅲ 환경관리: pos={p_hwankyung}")
    print(f"  단원 Ⅳ 부록    : pos={p_appendix}")

    end = p_appendix if p_appendix else len(full_text)

    sections = {}
    if p_chonron is not None:
        chonron_end = p_kakron if p_kakron else (p_hwankyung or end)
        sections['총론'] = full_text[p_chonron:chonron_end]

    if p_kakron is not None:
        kakron_end = p_hwankyung if p_hwankyung else end
        sections['각론'] = full_text[p_kakron:kakron_end]

    if p_hwankyung is not None:
        sections['환경관리'] = full_text[p_hwankyung:end]

    if not sections:
        print("  [경고] 섹션 경계 미발견 → 전체를 총론으로 처리")
        sections['총론'] = full_text[:end]

    return sections


# ── 서브섹션 분할 ─────────────────────────────────────────────────────────
def split_by_section(text: str) -> list[dict]:
    matches = list(SECTION_RE.finditer(text))
    if not matches:
        return [{'sec_no': 0, 'sec_title': '전체', 'content': text.strip()}]
    sections = []
    for i, m in enumerate(matches):
        sec_no    = int(m.group(1))
        sec_title = m.group(2).strip()
        start     = m.start()
        end       = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content   = text[start:end].strip()
        if content and len(content) > 30:
            sections.append({'sec_no': sec_no, 'sec_title': sec_title, 'content': content})
    return sections


# ── 키워드 추출 ───────────────────────────────────────────────────────────
def extract_keywords(text: str, max_kw: int = 12) -> list[str]:
    words = re.findall(r'[가-힣]{2,}', text)
    seen, result = set(), []
    stopwords = {'감염병', '관리', '지침', '경우', '관련', '통해', '대한', '경우에', '레지오넬라'}
    for w in words:
        if w not in seen and w not in stopwords:
            seen.add(w)
            result.append(w)
        if len(result) >= max_kw:
            break
    return result


# ── 청크 생성 (단락+크기 기반) ───────────────────────────────────────────
CHUNK_SIZE = 1200
_SENT_END_RE = re.compile(r'(?<=[다요함됨임])\.\s+')


def _split_paragraphs(text: str) -> list[str]:
    raw = re.split(r'\n{2,}', text)
    paragraphs = []
    header_re = re.compile(
        r'^(\d{1,2}[.\s]\s+\S|[가나다라마바사아]\.\s|[①②③④⑤]\s|[○●▶■]\s)'
    )
    for block in raw:
        block = block.strip()
        if not block:
            continue
        lines, current = block.split('\n'), []
        for line in lines:
            if current and header_re.match(line.strip()):
                paragraphs.append(' '.join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            paragraphs.append(' '.join(current))
    return [p.strip() for p in paragraphs if p.strip()]


def _refine_chunks(paragraphs: list[str]) -> list[str]:
    merged, buf = [], ''
    for para in paragraphs:
        if not buf:
            buf = para
        elif len(buf) + len(para) + 1 <= CHUNK_SIZE:
            buf = buf + ' ' + para
        else:
            merged.append(buf)
            buf = para
    if buf:
        merged.append(buf)

    result = []
    for para in merged:
        if len(para) <= CHUNK_SIZE:
            result.append(para)
            continue
        sentences = _SENT_END_RE.split(para)
        chunk = ''
        for sent in sentences:
            if len(chunk) + len(sent) + 1 <= CHUNK_SIZE:
                chunk = (chunk + ' ' + sent).strip()
            else:
                if chunk:
                    result.append(chunk)
                if len(sent) > CHUNK_SIZE:
                    for i in range(0, len(sent), CHUNK_SIZE):
                        result.append(sent[i:i + CHUNK_SIZE].strip())
                    chunk = ''
                else:
                    chunk = sent
        if chunk:
            result.append(chunk)
    return [r for r in result if r.strip()]


def build_section_chunks(
    text: str,
    chapter_label: str,  # '총론', '각론', '환경관리'
    source: str,
    id_prefix: str,
) -> list[dict]:
    """
    섹션 텍스트를 서브섹션으로 분할 후 청킹.
    서브섹션 분할이 안 되면 단락+크기 기반 청킹.
    """
    cleaned  = clean_text(text)
    sections = split_by_section(cleaned)

    chunks = []

    # 서브섹션 분할이 잘 된 경우 (섹션 2개 이상, 각 섹션이 충분한 크기)
    if len(sections) >= 2 and all(len(s['content']) > 100 for s in sections):
        for sec in sections:
            content = remove_nul(sec['content'])
            if not content.strip() or len(content) < 30:
                continue
            # 서브섹션 내용이 너무 크면 재분할
            if len(content) > CHUNK_SIZE * 2:
                sub_paragraphs = _split_paragraphs(content)
                sub_chunks     = _refine_chunks(sub_paragraphs)
                for j, sub in enumerate(sub_chunks):
                    sub = remove_nul(sub)
                    cid  = f"{id_prefix}_{chapter_label}_sec{sec['sec_no']:02d}_{j:02d}"
                    ctxt = f"{DOC_TITLE} {DISEASE_NAME} {chapter_label} {sec['sec_title']}\n{sub}"
                    chunks.append(_make_chunk(cid, chapter_label, sec['sec_title'], sub, ctxt, len(chunks), source))
            else:
                cid  = f"{id_prefix}_{chapter_label}_sec{sec['sec_no']:02d}"
                ctxt = f"{DOC_TITLE} {DISEASE_NAME} {chapter_label} {sec['sec_title']}\n{content}"
                chunks.append(_make_chunk(cid, chapter_label, sec['sec_title'], content, ctxt, len(chunks), source))
    else:
        # 서브섹션 미발견 → 단락+크기 기반
        paragraphs = _split_paragraphs(cleaned)
        text_chunks = _refine_chunks(paragraphs)
        for i, content in enumerate(text_chunks):
            content = remove_nul(content)
            cid  = f"{id_prefix}_{chapter_label}_{i:03d}"
            ctxt = f"{DOC_TITLE} {DISEASE_NAME} {chapter_label}\n{content}"
            chunks.append(_make_chunk(cid, chapter_label, '전체', content, ctxt, i, source))

    return chunks


def _make_chunk(
    chunk_id: str,
    chapter: str,
    section_title: str,
    content: str,
    chunk_text: str,
    chunk_index: int,
    source: str,
) -> dict:
    return {
        'id':             chunk_id,
        'disease_name':   DISEASE_NAME,
        'document_title': DOC_TITLE,
        'chapter':        chapter,
        'section_title':  section_title,
        'content':        content,
        'chunk_text':     remove_nul(chunk_text),
        'chunk_index':    chunk_index,
        'keywords':       extract_keywords(f"{DISEASE_NAME} {section_title} {content}"),
        'source':         source,
        'content_type':   CONTENT_TYPE,
        'metadata':       None,
    }


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='샘플 출력만, JSON 저장 없음')
    args = parser.parse_args()

    print(f"[레지오넬라증 파서] 시작")
    print(f"  입력: {PDF_FILENAME}\n")

    print("[1단계] PDF 텍스트 추출 중...")
    full_text = extract_full_text(PDF_PATH)
    print(f"  추출 완료: {len(full_text):,}자\n")

    print("[2단계] 섹션 분리 중...")
    sections = split_sections(full_text)
    for name, text in sections.items():
        print(f"  {name}: {len(text):,}자")
    print()

    print("[3단계] 청크 생성 중...")
    all_chunks = []
    chapter_map = {
        '총론':    'leg',
        '각론':    'leg',
        '환경관리': 'leg',
    }
    for chapter_label, section_text in sections.items():
        prefix = chapter_map.get(chapter_label, 'leg')
        cks = build_section_chunks(section_text, chapter_label, PDF_FILENAME, prefix)
        print(f"  {chapter_label}: {len(cks)}개 청크")
        all_chunks.extend(cks)

    print(f"  전체: {len(all_chunks)}개\n")

    print("── 샘플 청크 (처음 5개) ─────────────────────")
    for c in all_chunks[:5]:
        print(f"  ID           : {c['id']}")
        print(f"  chapter      : {c['chapter']}")
        print(f"  section_title: {c['section_title']}")
        print(f"  content 길이 : {len(c['content'])}자")
        print()

    if args.preview:
        print("[preview] JSON 저장 건너뜀")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    print(f"[완료] 저장: {OUTPUT_FILE}")
    print(f"  전체 청크 {len(all_chunks)}개")


if __name__ == '__main__':
    main()

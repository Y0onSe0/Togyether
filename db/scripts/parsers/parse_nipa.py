"""
parsers/parse_nipa.py
제1급감염병 니파바이러스감염증 대응지침(제1판) PDF
→ 총론/각론 청킹 → JSON 저장

PDF 구조 (209페이지):
  전문/목차
  제1장 총 론  (Part Ⅰ. 니파바이러스감염증 대응 개요 실행 헤더)
    Ⅰ. 니파바이러스감염증 대응 개요
    Ⅱ. 사례 정의
    Ⅲ. 의심 시 대응
    Ⅳ. 확진 시 대응
    Ⅴ. 실험실 검사 관리
    Ⅵ. 유행 역학조사 및 보고
    (이하 추가 섹션)
  제2장 각 론
    Ⅰ. 니파바이러스감염증 개요
  제3장 부 록  ← 제외
  제4장 서 식  ← 제외

출력: parsed/chunks_nipa.json

실행:
    python parsers/parse_nipa.py           ← JSON 저장
    python parsers/parse_nipa.py --preview ← 샘플 출력만
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
PDF_FILENAME  = "++제1급감염병 니파바이러스감염증 대응 지침(제1판)_전자배포.pdf"
PDF_PATH      = GUIDELINE_PDF_DIR / "완료" / "총론-각론-부록" / PDF_FILENAME
DOC_TITLE     = "제1급감염병 니파바이러스감염증 대응지침"
DISEASE_NAME  = "니파바이러스감염증"
DISEASE_GROUP = "니파바이러스감염증"
CONTENT_TYPE  = "management"
OUTPUT_DIR    = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE   = OUTPUT_DIR / "chunks_nipa.json"

# ── 패턴 ─────────────────────────────────────────────────────────────────
# 목차 영역 끝 추정 위치 (TOC 페이지들은 보통 앞 1/15 이내)
TOC_END_POS = 12_000

# 총론 시작: "Part Ⅰ. 니파바이러스감염증 대응 개요" (총론 running header)
# 각론 Part Ⅰ.과의 차이: 총론은 "대응 개요", 각론은 "(Nipah virus infection) 개요"
CHONRON_START_RE = re.compile(
    r'Part\s*[ⅠI]\.\s*니파바이러스감염증\s*대응\s*개요',
    re.IGNORECASE
)

# 각론 시작: "Part Ⅰ. 니파바이러스감염증(Nipah virus infection) 개요"
# 총론과 달리 영문명 (Nipah virus infection)이 포함됨
# 페이지 95 기준 pos≈89,635
KAKRON_RE = re.compile(
    r'Part\s*[ⅠI]\.\s*니파바이러스감염증\s*\(Nipah',
    re.IGNORECASE
)

# 부록 시작: "부 록\n1. 검역..." 또는 "3\n제 장\n부 록"
APPENDIX_RE = re.compile(
    r'부\s*록\s*\n1\.\s*검역|3\n제\s*장\n부\s*록',
    re.MULTILINE
)

# 총론/각론 내 Part 섹션: "Part Ⅰ./Ⅱ./..." running header 변경을 섹션 경계로 사용
PART_SECTION_RE = re.compile(
    r'Part\s*([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩiIvVxX]+)\.\s+([가-힣A-Za-z\(\)\s·]{2,40})',
    re.MULTILINE
)

# 각론 내 로마자 섹션: "Ⅰ./Ⅱ." 단독 섹션
ROMAN_SECTION_RE = re.compile(
    r'\n([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])\.\s+([가-힣A-Za-z\s·\(\)]{2,40})\n',
    re.MULTILINE
)

# 서브섹션: "1. 목적", "2. 법적근거" 등
SECTION_RE = re.compile(r'\n(\d+)\.\s+([가-힣·\s·A-Za-z]{2,25})\n', re.MULTILINE)

# 사이드바 노이즈
SIDEBAR_PATTERNS = [
    # 페이지 헤더
    re.compile(r'^제1급감염병 니파바이러스감염증[^\n]*$', re.MULTILINE),
    re.compile(r'^제1급감염병 니파바이러스감염증\s*대응지침[^\n]*$', re.MULTILINE),
    re.compile(r'^www\.kdca\.go\.kr[^\n]*$', re.MULTILINE),
    # Part Ⅰ. running header
    re.compile(r'^Part\s*[ⅠI]\.\s*니파바이러스감염증\s*대응\s*개요\s*$', re.MULTILINE),
    # 세로 사이드바 글자
    re.compile(r'^\s*[ⅠⅡⅢⅣⅤ]\s*$', re.MULTILINE),
    re.compile(r'^제\s*\d+\s*급\s*감염병\s*$', re.MULTILINE),
    re.compile(r'^\s*총\s*$', re.MULTILINE),
    re.compile(r'^\s*각\s*$', re.MULTILINE),
    re.compile(r'^\s*론\s*$', re.MULTILINE),
    re.compile(r'^\s*부\s*$', re.MULTILINE),
    re.compile(r'^\s*록\s*$', re.MULTILINE),
    re.compile(r'^\s*서\s*$', re.MULTILINE),
    re.compile(r'^\s*식\s*$', re.MULTILINE),
    # 글자 단독줄 사이드바 연속 패턴
    re.compile(r'제\n\d+\n장\n[총각부서]\n'),
    re.compile(r'[ⅠⅡⅢⅣⅤ]\n?[총각부서]\n?론?\n?'),
    # 페이지 번호
    re.compile(r'^\s*\d+\s*$', re.MULTILINE),
    # [일  러  두  기] 등 전문 노이즈
    re.compile(r'^\[일\s+러\s+두\s+기\]\s*$', re.MULTILINE),
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


# ── 총론/각론 경계 분리 ───────────────────────────────────────────────────
def split_sections(full_text: str) -> tuple[str, str]:
    """
    총론 텍스트, 각론 텍스트 반환.
    전략: TOC 영역 이후에서 총론·각론·부록 경계를 탐색.
    """
    # 총론 실제 시작 (TOC 이후)
    chonron_start = TOC_END_POS
    m_chonron = CHONRON_START_RE.search(full_text, TOC_END_POS)
    if m_chonron:
        chonron_start = m_chonron.start()
        print(f"  총론 시작: pos={chonron_start}")
    else:
        print(f"  [경고] Part Ⅰ. 헤더 미발견 → pos={TOC_END_POS}부터 총론으로 처리")

    # 각론 시작
    m_kakron = KAKRON_RE.search(full_text, chonron_start + 100)
    if m_kakron:
        kakron_start = m_kakron.start()
        print(f"  각론 시작: pos={kakron_start}")
    else:
        kakron_start = len(full_text)
        print("  [경고] 각론 경계 미발견 → 각론 없음으로 처리")

    # 부록 시작 (각론 내에서 탐색)
    m_appendix = APPENDIX_RE.search(full_text, kakron_start + 50)
    kakron_end = m_appendix.start() if m_appendix else len(full_text)
    print(f"  부록 시작: {'pos=' + str(kakron_end) if m_appendix else '미발견(문서 끝)'}")

    chonron_text = full_text[chonron_start:kakron_start]
    kakron_text  = full_text[kakron_start:kakron_end]
    return chonron_text, kakron_text


# ── 로마자 섹션 분할 (총론용) ─────────────────────────────────────────────
def split_by_roman_section(text: str) -> list[dict]:
    """
    Ⅰ./Ⅱ./Ⅲ. 등 로마자 섹션으로 분할.
    미발견 시 숫자 서브섹션으로 분할 시도.
    """
    matches = list(ROMAN_SECTION_RE.finditer(text))
    if matches:
        sections = []
        for i, m in enumerate(matches):
            sec_no    = m.group(1)
            sec_title = m.group(2).strip()
            start     = m.start()
            end       = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content   = text[start:end].strip()
            if content and len(content) > 30:
                sections.append({'sec_no': i + 1, 'sec_title': f"{sec_no}. {sec_title}", 'content': content})
        if sections:
            return sections

    # fallback: 숫자 서브섹션
    return split_by_section(text)


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
    stopwords = {'감염병', '관리', '지침', '경우', '관련', '통해', '대한', '경우에', '바이러스'}
    for w in words:
        if w not in seen and w not in stopwords:
            seen.add(w)
            result.append(w)
        if len(result) >= max_kw:
            break
    return result


# ── 총론 청크 생성 ────────────────────────────────────────────────────────
CHONRON_CHUNK_SIZE = 1200
_SENT_END_RE = re.compile(r'(?<=[다요함됨임])\.\s+')


def _split_paragraphs(text: str) -> list[str]:
    raw = re.split(r'\n{2,}', text)
    paragraphs = []
    header_re = re.compile(
        r'^(\d{1,2}\.\s+\S|[가나다라마바사아]\.\s|[①②③④⑤]\s|[○●▶■]\s|[ⅠⅡⅢⅣⅤⅥ]\.\s)'
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
        elif len(buf) + len(para) + 1 <= CHONRON_CHUNK_SIZE:
            buf = buf + ' ' + para
        else:
            merged.append(buf)
            buf = para
    if buf:
        merged.append(buf)

    result = []
    for para in merged:
        if len(para) <= CHONRON_CHUNK_SIZE:
            result.append(para)
            continue
        sentences = _SENT_END_RE.split(para)
        chunk = ''
        for sent in sentences:
            if len(chunk) + len(sent) + 1 <= CHONRON_CHUNK_SIZE:
                chunk = (chunk + ' ' + sent).strip()
            else:
                if chunk:
                    result.append(chunk)
                if len(sent) > CHONRON_CHUNK_SIZE:
                    for i in range(0, len(sent), CHONRON_CHUNK_SIZE):
                        result.append(sent[i:i + CHONRON_CHUNK_SIZE].strip())
                    chunk = ''
                else:
                    chunk = sent
        if chunk:
            result.append(chunk)
    return [r for r in result if r.strip()]


def build_chonron_chunks(chonron_text: str, source: str) -> list[dict]:
    if not chonron_text.strip():
        return []
    cleaned    = clean_text(chonron_text)
    paragraphs = _split_paragraphs(cleaned)
    chunks_txt = _refine_chunks(paragraphs)

    chunks = []
    for i, content in enumerate(chunks_txt):
        content    = remove_nul(content)
        chunk_text = remove_nul(f"{DOC_TITLE} {DISEASE_NAME} 총론\n{content}")
        chunks.append({
            'id':             f"nipa_chonron_{i:03d}",
            'disease_name':   DISEASE_NAME,
            'document_title': DOC_TITLE,
            'chapter':        '총론',
            'section_title':  '대응절차',
            'content':        content,
            'chunk_text':     chunk_text,
            'chunk_index':    i,
            'keywords':       extract_keywords(content),
            'source':         source,
            'content_type':   CONTENT_TYPE,
            'metadata':       None,
        })
    return chunks


# ── 각론 청크 생성 ────────────────────────────────────────────────────────
def build_kakron_chunks(kakron_text: str, source: str) -> list[dict]:
    """
    각론은 단일 질병 개요 섹션 (~5,000자).
    로마자 섹션 패턴 먼저 시도, 실패 시 단락+크기 기반 분할.
    """
    if not kakron_text.strip():
        return []
    cleaned  = clean_text(kakron_text)
    sections = split_by_roman_section(cleaned)

    # 섹션 분할이 실질적으로 안 된 경우 → 단락+크기 기반
    if len(sections) == 1 and len(sections[0]['content']) > CHONRON_CHUNK_SIZE:
        paragraphs  = _split_paragraphs(cleaned)
        text_chunks = _refine_chunks(paragraphs)
        chunks = []
        for i, content in enumerate(text_chunks):
            content    = remove_nul(content)
            chunk_text = remove_nul(f"{DOC_TITLE} {DISEASE_NAME} 각론 질병개요\n{content}")
            chunks.append({
                'id':             f"nipa_kakron_{i:03d}",
                'disease_name':   DISEASE_NAME,
                'document_title': DOC_TITLE,
                'chapter':        '각론',
                'section_title':  '질병개요',
                'content':        content,
                'chunk_text':     chunk_text,
                'chunk_index':    i,
                'keywords':       extract_keywords(f"{DISEASE_NAME} 각론 {content}"),
                'source':         source,
                'content_type':   CONTENT_TYPE,
                'metadata':       None,
            })
        return chunks

    # 로마자 섹션별 청크
    chunks = []
    for sec in sections:
        content = remove_nul(sec['content'])
        if not content.strip() or len(content) < 30:
            continue
        chunk_id   = f"nipa_kakron_sec{sec['sec_no']:02d}"
        chunk_text = remove_nul(f"{DOC_TITLE} {DISEASE_NAME} 각론 {sec['sec_title']}\n{content}")
        chunks.append({
            'id':             chunk_id,
            'disease_name':   DISEASE_NAME,
            'document_title': DOC_TITLE,
            'chapter':        '각론',
            'section_title':  sec['sec_title'],
            'content':        content,
            'chunk_text':     chunk_text,
            'chunk_index':    sec['sec_no'],
            'keywords':       extract_keywords(f"{DISEASE_NAME} {sec['sec_title']} {content}"),
            'source':         source,
            'content_type':   CONTENT_TYPE,
            'metadata':       None,
        })
    return chunks


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='샘플 출력만, JSON 저장 없음')
    args = parser.parse_args()

    print(f"[니파바이러스감염증 파서] 시작")
    print(f"  입력: {PDF_FILENAME}\n")

    print("[1단계] PDF 텍스트 추출 중...")
    full_text = extract_full_text(PDF_PATH)
    print(f"  추출 완료: {len(full_text):,}자\n")

    print("[2단계] 총론/각론 분리 중...")
    chonron_text, kakron_text = split_sections(full_text)
    print(f"  총론: {len(chonron_text):,}자 / 각론: {len(kakron_text):,}자\n")

    print("[3단계] 청크 생성 중...")
    all_chunks  = build_chonron_chunks(chonron_text, PDF_FILENAME)
    all_chunks += build_kakron_chunks(kakron_text, PDF_FILENAME)
    c_cnt = len([c for c in all_chunks if c['chapter'] == '총론'])
    k_cnt = len([c for c in all_chunks if c['chapter'] != '총론'])
    print(f"  총론 청크: {c_cnt}개")
    print(f"  각론 청크: {k_cnt}개")
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

"""
parsers/parse_respiratory.py
2026년도 호흡기감염병 관리지침(일부개정판) PDF
→ 질병별/섹션별 청킹 → JSON 저장

PDF 구조:
  단원 I  총론   ← 공통 관리 절차
  단원 II 각론
    수막구균 감염증
    성홍열
    아데노바이러스 감염증
    사람 보카바이러스 감염증
    파라인플루엔자 바이러스 감염증
    호흡기세포융합바이러스 감염증
    리노바이러스 감염증
    사람 메타뉴모바이러스 감염증
    사람 코로나바이러스 감염증
    마이코플라스마 폐렴균 감염증
    클라미디아 폐렴균 감염증
  단원 III 부록  ← 제외

각론 질병 구분자: 페이지 헤더 "단원 Ⅱ 각 론－{질병명}" 패턴 이용

출력: parsed/chunks_respiratory.json

실행:
    python parsers/parse_respiratory.py           ← JSON 저장
    python parsers/parse_respiratory.py --preview ← 샘플 출력만
"""

import sys
import re
import json
import argparse
from pathlib import Path

import pdfplumber

sys.path.append(str(Path(__file__).parent.parent))
from config import GUIDELINE_PDF_DIR

# ── 설정 ─────────────────────────────────────────────────────────────────
PDF_FILENAME  = "2026년도 호흡기감염병 관리지침(일부개정판).pdf"
PDF_PATH      = GUIDELINE_PDF_DIR / "완료" / "총론-각론" / PDF_FILENAME
DOC_TITLE     = "2026년도 호흡기감염병 관리지침"
DISEASE_GROUP = "호흡기감염병"
CONTENT_TYPE  = "management"
OUTPUT_DIR    = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE   = OUTPUT_DIR / "chunks_respiratory.json"

# ── 패턴 ─────────────────────────────────────────────────────────────────
# 총론 페이지 헤더 (각 페이지마다 반복)
CHONRON_HEADER_RE = re.compile(r'단원\s*[ⅠI]\s*총\s*론', re.MULTILINE)

# 각론 질병 페이지 헤더: "단원 Ⅱ 각 론－수막구균 감염증"
DISEASE_HEADER_RE = re.compile(
    r'단원\s*Ⅱ\s*각\s*론[^가-힣\n]{0,10}(성홍열|[가-힣][가-힣 ]*감염증)',
    re.MULTILINE
)

# 부록 시작 (단원 Ⅲ 또는 단원 III)
APPENDIX_RE = re.compile(r'단원\s*(Ⅲ|III)\s*부\s*록', re.MULTILINE)

# 서브섹션: "1. 개요", "2. 발생현황" 등
SECTION_RE = re.compile(r'\n(\d+)\.\s+([가-힣·\s&Q]{2,20})\n', re.MULTILINE)

# 사이드바 노이즈 패턴
SIDEBAR_PATTERNS = [
    re.compile(r'^2026년도 호흡기감염병 관리지침[^\n]*$', re.MULTILINE),
    re.compile(r'^www\.kdca\.go\.kr[^\n]*$', re.MULTILINE),
    re.compile(r'^\s*\d+\s*$', re.MULTILINE),           # 페이지 번호
    re.compile(r'^단원\s*[ⅠI]\s*총\s*론\s*$', re.MULTILINE),
    re.compile(r'^단원\s*Ⅱ\s*각\s*론[^\n]*$', re.MULTILINE),
    re.compile(r'^\s*[ⅠⅡⅢ]\s*$', re.MULTILINE),
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


# ── 총론/각론/부록 분리 ───────────────────────────────────────────────────
def split_sections(full_text: str) -> tuple[str, str]:
    """
    총론 텍스트, 각론 텍스트 반환.
    - 총론: 문서 시작 ~ 마지막 단원Ⅰ 총론 헤더 직후
    - 각론: 이후 ~ 부록 시작 전
    """
    # 총론 헤더 마지막 위치
    chonron_all = list(CHONRON_HEADER_RE.finditer(full_text))
    if chonron_all:
        kakron_start = chonron_all[-1].end()
    else:
        # 첫 번째 각론 질병 헤더 위치로 대체
        m = DISEASE_HEADER_RE.search(full_text)
        kakron_start = m.start() if m else 0
        print("  [경고] 총론 헤더 미발견 → 각론 질병 헤더로 경계 설정")

    # 부록 시작 위치
    appendix_m = APPENDIX_RE.search(full_text, kakron_start + 100)
    kakron_end = appendix_m.start() if appendix_m else len(full_text)
    print(f"  각론 끝 경계: {'부록 앵커 감지' if appendix_m else '문서 끝'}")

    chonron_text = full_text[:kakron_start]
    kakron_text  = full_text[kakron_start:kakron_end]
    return chonron_text, kakron_text


# ── 각론 질병별 분리 ──────────────────────────────────────────────────────
def split_by_disease(kakron_text: str) -> list[dict]:
    """
    페이지 헤더 "단원 Ⅱ 각 론－{질병명}" 패턴이 변경되는 위치를 기준으로 질병 분리.
    """
    headers = list(DISEASE_HEADER_RE.finditer(kakron_text))
    if not headers:
        print("  [경고] 질병 헤더 미발견 → 전체를 단일 블록으로 처리")
        return [{'disease_name': DISEASE_GROUP, 'text': kakron_text}]

    # 질병명이 바뀌는 첫 위치만 추출
    boundaries = []
    prev_name = None
    for h in headers:
        name = h.group(1).strip()
        if name != prev_name:
            boundaries.append((h.start(), name))
            prev_name = name

    diseases = []
    for i, (start, name) in enumerate(boundaries):
        end  = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(kakron_text)
        text = clean_text(kakron_text[start:end])
        if len(text) > 100:
            diseases.append({'disease_name': name, 'text': text})

    return diseases


# ── 서브섹션 분할 ─────────────────────────────────────────────────────────
def split_by_section(disease_text: str) -> list[dict]:
    matches = list(SECTION_RE.finditer(disease_text))
    if not matches:
        return [{'sec_no': 0, 'sec_title': '전체', 'content': disease_text.strip()}]

    sections = []
    for i, m in enumerate(matches):
        sec_no    = int(m.group(1))
        sec_title = m.group(2).strip()
        start     = m.start()
        end       = matches[i + 1].start() if i + 1 < len(matches) else len(disease_text)
        content   = disease_text[start:end].strip()
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


# ── 각론 청크 생성 ────────────────────────────────────────────────────────
def build_chunks(diseases: list[dict], source: str) -> list[dict]:
    chunks = []
    for dis in diseases:
        dname    = dis['disease_name']
        sections = split_by_section(dis['text'])
        safe_name = re.sub(r'[^\w가-힣]', '', dname)[:20]

        for sec in sections:
            sec_no    = sec['sec_no']
            sec_title = sec['sec_title']
            content   = remove_nul(sec['content'])
            if not content.strip() or len(content) < 30:
                continue

            chunk_id   = f"resp_{safe_name}_sec{sec_no:02d}"
            chunk_text = f"{DOC_TITLE} {dname} {sec_title}\n{content}"

            chunks.append({
                'id':             chunk_id,
                'disease_name':   dname,
                'document_title': DOC_TITLE,
                'chapter':        '각론',
                'section_title':  sec_title,
                'content':        content,
                'chunk_text':     remove_nul(chunk_text),
                'chunk_index':    sec_no,
                'keywords':       extract_keywords(f"{dname} {sec_title} {content}"),
                'source':         source,
                'content_type':   CONTENT_TYPE,
                'metadata':       None,
            })
    return chunks


# ── 총론 청킹 ─────────────────────────────────────────────────────────────
CHONRON_CHUNK_SIZE = 1200
_SENT_END_RE = re.compile(r'(?<=[다요함됨임])\.\s+')


def _split_paragraphs(text: str) -> list[str]:
    raw = re.split(r'\n{2,}', text)
    paragraphs = []
    header_re = re.compile(
        r'^(\d{1,2}\.\s+\S|[가나다라마바사아]\.\s|[①②③④⑤]\s|[○●▶■]\s)'
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
    cleaned     = clean_text(chonron_text)
    paragraphs  = _split_paragraphs(cleaned)
    text_chunks = _refine_chunks(paragraphs)

    chunks = []
    for i, content in enumerate(text_chunks):
        content    = remove_nul(content)
        chunk_text = remove_nul(f"{DOC_TITLE} {DISEASE_GROUP} 총론\n{content}")
        chunks.append({
            'id':             f"resp_chonron_{i:03d}",
            'disease_name':   DISEASE_GROUP,
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


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='샘플 출력만, JSON 저장 없음')
    args = parser.parse_args()

    print(f"[호흡기감염병 파서] 시작")
    print(f"  입력: {PDF_FILENAME}\n")

    print("[1단계] PDF 텍스트 추출 중...")
    full_text = extract_full_text(PDF_PATH)
    print(f"  추출 완료: {len(full_text):,}자\n")

    print("[2단계] 총론/각론 분리 중...")
    chonron_text, kakron_text = split_sections(full_text)
    print(f"  총론: {len(chonron_text):,}자 / 각론: {len(kakron_text):,}자\n")

    print("[3단계] 질병별 분리 중...")
    diseases = split_by_disease(kakron_text)
    print(f"  질병 {len(diseases)}개 감지:")
    for d in diseases:
        print(f"    {d['disease_name']} ({len(d['text']):,}자)")
    print()

    print("[4단계] 청크 생성 중...")
    all_chunks  = build_chonron_chunks(chonron_text, PDF_FILENAME)
    all_chunks += build_chunks(diseases, PDF_FILENAME)
    c_cnt = len([c for c in all_chunks if c['chapter'] == '총론'])
    k_cnt = len([c for c in all_chunks if c['chapter'] != '총론'])
    print(f"  총론 청크: {c_cnt}개")
    print(f"  각론 청크: {k_cnt}개")
    print(f"  전체: {len(all_chunks)}개\n")

    # 미리보기
    print("── 샘플 청크 (각론 처음 5개) ─────────────────────")
    kakron_chunks = [c for c in all_chunks if c['chapter'] != '총론']
    for c in kakron_chunks[:5]:
        print(f"  ID           : {c['id']}")
        print(f"  disease_name : {c['disease_name']}")
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
    print(f"  질병 {len(diseases)}개 / 전체 청크 {len(all_chunks)}개")


if __name__ == '__main__':
    main()

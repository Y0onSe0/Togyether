"""
parsers/parse_std.py
2026년 성매개감염병 관리지침 PDF
→ 질병별/섹션별 청킹 → JSON 저장

⚠️  이 PDF는 이미지(스캔) 기반 PDF입니다.
    pdfplumber로는 텍스트 추출이 불가능하므로 OCR을 사용합니다.

OCR 전처리 요구사항:
    pip install pdf2image pytesseract
    ① Tesseract OCR 설치 (한국어 언어팩 kor 포함)
       Windows: https://github.com/UB-Mannheim/tesseract/wiki
       설치 후 PATH 추가 또는 TESSERACT_CMD 환경변수 설정
    ② Poppler 설치 (pdf2image 의존)
       Windows: https://github.com/oschwartz10612/poppler-windows/releases
       설치 후 poppler/bin 을 PATH 에 추가

PDF 구조 (추정 - 총론/각론 형식):
  총론   ← 공통 관리 절차
  각론
    매독
    임질
    클라미디아 감염증
    성기단순포진
    첨규콘딜롬
    연성하감
    (기타 포함 가능)
  부록   ← 제외

출력: parsed/chunks_std.json

실행:
    python parsers/parse_std.py              ← OCR 추출 후 JSON 저장
    python parsers/parse_std.py --preview    ← 샘플 출력만, JSON 저장 없음
    python parsers/parse_std.py --diagnose   ← OCR 텍스트 저장 + 패턴 검출 결과 출력
    python parsers/parse_std.py --from-txt PATH ← 기존 OCR 텍스트 파일로부터 파싱
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
PDF_FILENAME  = "2026년 성매개감염병 관리지침.pdf"
PDF_PATH      = GUIDELINE_PDF_DIR / "완료" / "총론-각론" / PDF_FILENAME
DOC_TITLE     = "2026년 성매개감염병 관리지침"
DISEASE_GROUP = "성매개감염병"
CONTENT_TYPE  = "management"
OUTPUT_DIR    = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE   = OUTPUT_DIR / "chunks_std.json"
OCR_TEXT_FILE = OUTPUT_DIR / "ocr_std_raw.txt"   # --diagnose 시 저장

# ── 패턴 ─────────────────────────────────────────────────────────────────
# 총론 헤더 (페이지마다 반복)
CHONRON_HEADER_RE = re.compile(
    r'총\s*론|제\s*1\s*장\s*총\s*론|단원\s*[ⅠI1]\s*총\s*론',
    re.MULTILINE
)

# 각론 시작 앵커 (여러 표기 허용)
KAKRON_RE = re.compile(
    r'각\s*론|제\s*\d+\s*장\s*(매독|임질|클라미디아|성기단순포진|첨규콘딜롬|연성하감|사람유두종)',
    re.MULTILINE
)

# 부록 시작 앵커
APPENDIX_RE = re.compile(
    r'부\s*록|서\s*식|별\s*지|APPENDIX',
    re.MULTILINE | re.IGNORECASE
)

# 각론 질병 챕터 — "제N장 질병명" 형식
CHAPTER_RE = re.compile(
    r'제\s*(\d+)\s*장\s*[.\s]\s*'
    r'(매독|임질|클라미디아\s*감염증?|성기단순포진|첨규콘딜롬|연성하감|'
    r'사람유두종바이러스\s*감염증?|사람유두종바이러스|'
    r'성매개감염병\s*개요|총론)',
    re.MULTILINE
)

# 페이지 헤더 기반 질병 감지 (CHAPTER_RE 미검출 시 fallback)
# "단원 Ⅱ 각 론－매독" 또는 "[각론] 매독" 등 형태
HEADER_DISEASE_RE = re.compile(
    r'(?:각\s*론\s*[-－―]\s*|각\s*론\s*\n\s*)'
    r'(매독|임질|클라미디아\s*감염증?|성기단순포진|첨규콘딜롬|연성하감|'
    r'사람유두종바이러스\s*감염증?)',
    re.MULTILINE
)

# 서브섹션: "1. 개요", "2. 발생현황" 등
SECTION_RE = re.compile(r'\n(\d+)\.\s+([가-힣·\s&Q]{2,20})\n', re.MULTILINE)

# 사이드바 노이즈 패턴
SIDEBAR_PATTERNS = [
    re.compile(r'^2026년\s*성매개감염병\s*관리지침[^\n]*$', re.MULTILINE),
    re.compile(r'^www\.kdca\.go\.kr[^\n]*$', re.MULTILINE),
    re.compile(r'^\s*\d+\s*$', re.MULTILINE),         # 페이지 번호
    re.compile(r'^총\s*론\s*$', re.MULTILINE),
    re.compile(r'^각\s*론\s*$', re.MULTILINE),
    re.compile(r'^부\s*록\s*$', re.MULTILINE),
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


# ── pdfplumber 추출 시도 ──────────────────────────────────────────────────
def _try_pdfplumber(pdf_path: Path) -> str:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text and text.strip():
                pages.append(remove_nul(text.strip()))
    return "\n\n".join(pages)


# ── OCR 추출 (pdf2image + pytesseract) ───────────────────────────────────
def _ocr_extract(pdf_path: Path) -> str:
    """
    pdf2image로 PDF 페이지를 이미지로 변환 후 pytesseract로 OCR.
    한국어(kor)+영어(eng) 혼합 모드 사용.
    """
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError as e:
        print(f"\n[오류] OCR 라이브러리 미설치: {e}")
        print("  pip install pdf2image pytesseract")
        print("  Tesseract OCR (kor 언어팩 포함) 및 Poppler 설치 필요")
        sys.exit(1)

    # Tesseract 경로 (환경변수 미설정 시 직접 지정)
    # pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

    print(f"  OCR 변환 중 (시간이 걸릴 수 있습니다)...")
    try:
        images = convert_from_path(str(pdf_path), dpi=300)
    except Exception as e:
        print(f"\n[오류] PDF→이미지 변환 실패: {e}")
        print("  Poppler가 PATH에 있는지 확인하세요.")
        sys.exit(1)

    print(f"  총 {len(images)}페이지 OCR 처리 중...")
    pages = []
    for i, img in enumerate(images):
        if (i + 1) % 10 == 0 or i == 0:
            print(f"    {i+1}/{len(images)}페이지...")
        text = pytesseract.image_to_string(img, lang='kor+eng')
        if text.strip():
            pages.append(remove_nul(text.strip()))

    return "\n\n".join(pages)


# ── PDF 전체 텍스트 추출 ──────────────────────────────────────────────────
def extract_full_text(pdf_path: Path) -> str:
    """pdfplumber 우선 시도 → 실패 시 OCR"""
    print("  pdfplumber 추출 시도...")
    text = _try_pdfplumber(pdf_path)
    if text and len(text) > 500:
        print(f"  pdfplumber 성공: {len(text):,}자")
        return text

    print("  텍스트 추출 불가 → OCR 모드로 전환")
    text = _ocr_extract(pdf_path)
    print(f"  OCR 완료: {len(text):,}자")
    return text


# ── 텍스트 파일에서 읽기 (--from-txt 옵션) ───────────────────────────────
def load_text_from_file(txt_path: str) -> str:
    p = Path(txt_path)
    if not p.exists():
        print(f"[오류] 텍스트 파일 미발견: {txt_path}")
        sys.exit(1)
    with open(p, encoding='utf-8') as f:
        return f.read()


# ── 총론/각론/부록 분리 ───────────────────────────────────────────────────
def split_sections(full_text: str) -> tuple[str, str]:
    """
    총론 텍스트, 각론 텍스트 반환.
    전략 A: 각론 앵커(KAKRON_RE)로 분리
    전략 B: 총론 헤더 마지막 위치로 분리
    """
    # 각론 앵커 탐색
    m_kakron = KAKRON_RE.search(full_text)

    if m_kakron:
        kakron_start = m_kakron.start()
        print(f"  각론 시작 앵커: pos={kakron_start} [{full_text[kakron_start:kakron_start+40].strip()!r}]")
    else:
        # 총론 헤더 마지막 위치로 대체
        chonron_all = list(CHONRON_HEADER_RE.finditer(full_text))
        if chonron_all:
            kakron_start = chonron_all[-1].end()
            print(f"  [경고] 각론 앵커 미발견 → 총론 마지막 헤더 이후를 각론으로 처리")
        else:
            kakron_start = 0
            print(f"  [경고] 각론/총론 앵커 모두 미발견 → 전체를 각론으로 처리")

    # 부록 시작 탐색 (각론 시작 이후에서 검색)
    m_appendix = APPENDIX_RE.search(full_text, kakron_start + 200)
    kakron_end = m_appendix.start() if m_appendix else len(full_text)
    print(f"  각론 끝 경계: {'부록 앵커 감지' if m_appendix else '문서 끝'}")

    chonron_text = full_text[:kakron_start]
    kakron_text  = full_text[kakron_start:kakron_end]
    return chonron_text, kakron_text


# ── 각론 질병별 분리 ──────────────────────────────────────────────────────
def split_by_disease(kakron_text: str) -> list[dict]:
    """
    전략 A: "제N장 질병명" 챕터 헤더 탐색
    전략 B: 페이지 헤더 변경(HEADER_DISEASE_RE)으로 탐색
    """
    # 전략 A: 챕터 번호
    matches = list(CHAPTER_RE.finditer(kakron_text))
    if matches:
        print(f"  전략 A (제N장 패턴): {len(matches)}개 검출")
        diseases = []
        for i, m in enumerate(matches):
            chap_no      = int(m.group(1))
            disease_name = m.group(2).strip()
            # 총론 챕터 제외
            if '총론' in disease_name:
                continue
            start = m.start()
            end   = matches[i + 1].start() if i + 1 < len(matches) else len(kakron_text)
            text  = clean_text(kakron_text[start:end])
            if len(text) > 100:
                diseases.append({
                    'chapter_no':  chap_no,
                    'disease_name': disease_name,
                    'text':        text,
                })
        if diseases:
            return diseases

    # 전략 B: 페이지 헤더 변경 감지
    headers = list(HEADER_DISEASE_RE.finditer(kakron_text))
    if headers:
        print(f"  전략 B (헤더 변경 패턴): {len(headers)}개 검출")
        boundaries, prev_name = [], None
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
                diseases.append({
                    'chapter_no':  i + 1,
                    'disease_name': name,
                    'text':        text,
                })
        if diseases:
            return diseases

    # 전략 C: 전체를 단일 블록
    print("  [경고] 질병 구분 패턴 미발견 → 전체를 단일 블록으로 처리")
    return [{'chapter_no': 0, 'disease_name': DISEASE_GROUP, 'text': kakron_text}]


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
    stopwords = {'감염병', '관리', '지침', '경우', '관련', '통해', '대한', '경우에', '성매개'}
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
        dname     = dis['disease_name']
        chap_no   = dis.get('chapter_no', 0)
        sections  = split_by_section(dis['text'])
        safe_name = re.sub(r'[^\w가-힣]', '', dname)[:20]

        for sec in sections:
            sec_no    = sec['sec_no']
            sec_title = sec['sec_title']
            content   = remove_nul(sec['content'])
            if not content.strip() or len(content) < 30:
                continue

            chunk_id   = f"std_ch{chap_no:02d}_{safe_name}_sec{sec_no:02d}"
            chunk_text = f"{DOC_TITLE} {dname} {sec_title}\n{content}"

            chunks.append({
                'id':             chunk_id,
                'disease_name':   dname,
                'document_title': DOC_TITLE,
                'chapter':        f"제{chap_no}장 {dname}" if chap_no else '각론',
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
            'id':             f"std_chonron_{i:03d}",
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


# ── 패턴 진단 출력 (--diagnose) ───────────────────────────────────────────
def diagnose(full_text: str):
    print("\n=== 패턴 진단 결과 ===")

    print("\n[총론 헤더 패턴]")
    for m in CHONRON_HEADER_RE.finditer(full_text):
        snippet = full_text[m.start():m.start()+60].replace('\n', '↵')
        print(f"  pos={m.start():>8}: {snippet!r}")

    print("\n[각론 앵커 패턴]")
    for m in KAKRON_RE.finditer(full_text):
        snippet = full_text[m.start():m.start()+60].replace('\n', '↵')
        print(f"  pos={m.start():>8}: {snippet!r}")

    print("\n[질병 챕터 패턴 (제N장)]")
    for m in CHAPTER_RE.finditer(full_text):
        snippet = full_text[m.start():m.start()+60].replace('\n', '↵')
        print(f"  pos={m.start():>8}: ch={m.group(1)}, name={m.group(2).strip()!r}")

    print("\n[헤더 질병명 패턴]")
    for m in HEADER_DISEASE_RE.finditer(full_text):
        snippet = full_text[m.start():m.start()+60].replace('\n', '↵')
        print(f"  pos={m.start():>8}: {snippet!r}")

    print("\n[부록 앵커 패턴]")
    for m in APPENDIX_RE.finditer(full_text):
        snippet = full_text[m.start():m.start()+60].replace('\n', '↵')
        print(f"  pos={m.start():>8}: {snippet!r}")
        break  # 첫 번째만

    print(f"\n전체 텍스트: {len(full_text):,}자")
    print("OCR 텍스트 샘플 (처음 1000자):")
    print(full_text[:1000])
    print("\n--- (중간 생략) ---\n")
    print("OCR 텍스트 샘플 (중간 1000자):")
    mid = len(full_text) // 2
    print(full_text[mid:mid+1000])


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview',   action='store_true', help='샘플 출력만, JSON 저장 없음')
    parser.add_argument('--diagnose',  action='store_true', help='OCR 텍스트 저장 + 패턴 진단 출력')
    parser.add_argument('--from-txt',  metavar='PATH',      help='기존 OCR 텍스트 파일 경로 (OCR 생략)')
    args = parser.parse_args()

    print(f"[성매개감염병 파서] 시작")
    print(f"  입력: {PDF_FILENAME}\n")

    # ① 텍스트 획득
    print("[1단계] 텍스트 획득 중...")
    if args.from_txt:
        print(f"  텍스트 파일 로드: {args.from_txt}")
        full_text = load_text_from_file(args.from_txt)
    else:
        full_text = extract_full_text(PDF_PATH)
    print(f"  완료: {len(full_text):,}자\n")

    # --diagnose: 패턴 확인 후 종료
    if args.diagnose:
        OUTPUT_DIR.mkdir(exist_ok=True)
        with open(OCR_TEXT_FILE, 'w', encoding='utf-8') as f:
            f.write(full_text)
        print(f"\n  OCR 텍스트 저장: {OCR_TEXT_FILE}")
        diagnose(full_text)
        return

    # ② 총론/각론 분리
    print("[2단계] 총론/각론 분리 중...")
    chonron_text, kakron_text = split_sections(full_text)
    print(f"  총론: {len(chonron_text):,}자 / 각론: {len(kakron_text):,}자\n")

    # ③ 질병별 분리
    print("[3단계] 질병별 분리 중...")
    diseases = split_by_disease(kakron_text)
    print(f"  질병 {len(diseases)}개 감지:")
    for d in diseases:
        print(f"    제{d.get('chapter_no',0)}장. {d['disease_name']} ({len(d['text']):,}자)")
    print()

    # ④ 청크 생성
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

"""
parsers/parse_covid.py
2025년도 코로나19 관리지침 PDF → 3단계 계층 청킹 → JSON 저장

PDF 구조:
  총론                      ← 총론/각론 단위
    제1장 코로나19 개요      ← 장 단위
      1. 정의                ← 번호 단위 (최소 청크)
      2. 병원체
      3. 임상적 특성
    제2장 역학적 특성
      1. 국내 발생 현황
      ...
  각론
    제1장 감시 및 신고
      1. 신고 대상
      2. 신고 방법
    제2장 격리
      1. 격리 기준
      가. 확진자
      나. 접촉자
      ...

파싱 대상: 총론 + 각론 (부록 제외)
청킹 단위: 번호 항목 or 가나다 항목 → 800자 초과 시 문장 단위 재분할

출력: parsed/chunks_covid.json

실행:
    python parsers/parse_covid.py           ← JSON 저장
    python parsers/parse_covid.py --preview ← 샘플 출력만
    python parsers/parse_covid.py --toc     ← 총론/각론/장 구조 확인
"""

import sys
import re
import json
from collections import Counter
import argparse
from pathlib import Path

import pdfplumber
import fitz  # pymupdf

sys.path.append(str(Path(__file__).parent.parent))
from config import GUIDELINE_PDF_DIR, CHUNK_SIZE

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── OCR 설정 (이미지 PDF 대응) ────────────────────────────────────────────
try:
    import pytesseract
    from PIL import Image
    import io

    # Windows Tesseract 기본 설치 경로
    _TESSERACT_PATHS = [
        r"C:\Users\jys72\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for _p in _TESSERACT_PATHS:
        if Path(_p).exists():
            pytesseract.pytesseract.tesseract_cmd = _p
            break

    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# ── 설정 ─────────────────────────────────────────────────────────────────
PDF_FILENAME = "++2025년도 코로나19 관리지침_최종-전자용.pdf"
PDF_PATH     = GUIDELINE_PDF_DIR / "완료" / PDF_FILENAME
DOC_TITLE    = "2025년도 코로나19 관리지침"
DISEASE_NAME     = "코로나19"
OUTPUT_DIR       = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE      = OUTPUT_DIR / "DATA_001_chunks_covid.json"
DATA_ID          = "DATA-001"
SOURCE_CATEGORY  = "disease"
KNOWLEDGE_TYPE   = "disease_guideline"

# 앞부분 목차/표지 스킵
TOC_END_POS = 8_000

# ── 헤더 정규식 ───────────────────────────────────────────────────────────

# 총론 / 각론 / 부록 (단독 줄)
PART_HDR_RE = re.compile(
    r'^(총\s*론|각\s*론|부\s*록)\s*$',
    re.MULTILINE,
)

# 제X장: "제1장 개요" / "제 1 장 ..."
CHAPTER_HDR_RE = re.compile(
    r'^(제\s*\d+\s*장[\.\s　].{0,80})$',
    re.MULTILINE,
)

# 번호 항목: "1. 정의" / "10. ..."
NUM_HDR_RE = re.compile(
    r'^(\d{1,2})\.\s+([^\n]{1,80})$',
    re.MULTILINE,
)

# 가나다 항목: "가. 확진자"
KOR_HDR_RE = re.compile(
    r'^([가나다라마바사아자차카타파하])\.\s+([^\n]{1,80})$',
    re.MULTILINE,
)

# 파싱 대상 (부록 제외)
TARGET_PARTS = ['총론', '각론']

# ── 노이즈 제거 ───────────────────────────────────────────────────────────
SIDEBAR_PATTERNS = [
    re.compile(r'^코로나19[^\n]{0,15}$',       re.MULTILINE),
    re.compile(r'^COVID[-\s]?19[^\n]{0,15}$',  re.MULTILINE),
    re.compile(r'^www\.kdca\.go\.kr[^\n]*$',   re.MULTILINE),
    re.compile(r'^\s*\d+\s*$',                 re.MULTILINE),  # 페이지 번호
    re.compile(r'^\s*[가-힣]\s*$',              re.MULTILINE),  # 세로 한 글자
    # 사이드바 섹션 라벨 (※ 총론/각론/부록 단독 줄은 제거하지 않음 → PART 구분자로 사용)
    re.compile(r'^\s*문구수정\s*$',              re.MULTILINE),
    # 사이드바가 본문 앞에 붙어버린 경우만 제거 ("총론총론..." 형태)
    re.compile(r'총론(?=총론)',                  re.MULTILINE),
    re.compile(r'각론(?=각론)',                  re.MULTILINE),
]

_SENT_END_RE = re.compile(r'(?<=[다요함됨임])\.\s+')

STOPWORDS = {
    # 문법/접속어
    '관련', '통해', '경우', '대한', '따른', '위한', '통한', '기반',
    '따라서', '그러나', '하지만', '또한', '그리고', '이후', '이전',
    '이내', '이상', '이하', '가지', '있는', '있음', '있으며', '되어',
    '이를', '위해', '모든', '각각', '이후에', '경우에',
    # 문서 구조어
    '관리', '지침', '개요', '현황', '특성', '절차', '정의', '목적',
    '대상', '범위', '내용', '방향', '원칙', '기본', '방법', '기준',
    # 고빈도 의료/행정어
    '환자', '발생', '실시', '진행', '시행', '사용', '여부', '수행',
    '제공', '확인', '통보', '신고', '조치', '판단', '검토', '결과',
    '수준', '기간', '필요', '해당', '포함',
    # 질병관리청 문서 반복어
    '질병관리청', '감염병', '대응지침', '관리지침',
    # 코로나19 파서 전용
    '코로나',
}


# ── 유틸 ─────────────────────────────────────────────────────────────────

def remove_nul(text: str) -> str:
    return text.replace('\x00', '')


def clean_header(text: str) -> str:
    """목차 점선(......) 및 페이지 번호 제거
    예: "제1장 개요 ················· 3"  → "제1장 개요"
        "1. 정의 .......... 15"           → "1. 정의"
    """
    text = re.sub(r'[\s·.]{2,}\d*\s*$', '', text)
    text = re.sub(r'\s+\d+\s*$', '', text)
    return text.strip()


def clean_sidebar(text: str) -> str:
    for pat in SIDEBAR_PATTERNS:
        text = pat.sub('', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_pdf_text(pdf_path: Path) -> str:
    """텍스트 레이어 → 없으면 OCR 자동 폴백"""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        print(f"  총 {total}페이지")
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(remove_nul(text.strip()))

    if pages:
        print(f"  텍스트 레이어 추출 완료")
        return "\n\n".join(pages)

    # 텍스트 레이어 없음 → OCR 시도
    print(f"  [경고] 텍스트 레이어 없음 → OCR 모드로 전환")
    return extract_pdf_text_ocr(pdf_path)


def _fix_ocr_spacing(text: str) -> str:
    """OCR에서 한국어 글자 사이에 불필요하게 삽입된 공백 제거
    예: "코 로 나 19 변 이" → "코로나19 변이"
    """
    KO = r'[가-힯㄰-㆏]'  # 완성형 + 자모
    # 한글↔한글 사이 공백
    text = re.sub(rf'(?<={KO[1:-1]})\s+(?={KO[1:-1]})', '', text)
    # 한글↔숫자/영문 사이 공백 (짧은 단일 공백만 제거)
    text = re.sub(rf'(?<={KO[1:-1]}) (?=[\dA-Za-z])', '', text)
    text = re.sub(rf'(?<=[\dA-Za-z]) (?={KO[1:-1]})', '', text)
    return text


def extract_pdf_text_ocr(pdf_path: Path) -> str:
    """pymupdf로 페이지를 이미지 렌더링 → pytesseract로 OCR (한국어)"""
    if not OCR_AVAILABLE:
        print("  [오류] OCR 불가 — pytesseract 미설치")
        print("  → pip install pytesseract  후  Tesseract-OCR(kor) 설치 필요")
        print("  → https://github.com/UB-Mannheim/tesseract/wiki")
        return ""

    try:
        pytesseract.get_tesseract_version()
    except Exception:
        print("  [오류] Tesseract 바이너리 미발견")
        print("  → https://github.com/UB-Mannheim/tesseract/wiki 에서 설치")
        print("  → 설치 시 'Korean' 언어 팩 체크 필수")
        return ""

    doc = fitz.open(str(pdf_path))
    pages = []
    total = len(doc)
    print(f"  OCR 시작: {total}페이지 (시간 소요)…")

    for i, page in enumerate(doc):
        if i % 10 == 0:
            print(f"    {i+1}/{total}페이지…")
        # 300 DPI 수준으로 렌더 (3배 스케일 = 정확도↑)
        pix      = page.get_pixmap(matrix=fitz.Matrix(3, 3))
        img      = Image.open(io.BytesIO(pix.tobytes("png")))
        # 전처리: 그레이스케일 → 대비 강화 → 이진화 (한글 인식률↑)
        from PIL import ImageEnhance
        img_gray = img.convert("L")
        img_enh  = ImageEnhance.Contrast(img_gray).enhance(2.0)
        img_bin  = img_enh.point(lambda x: 255 if x > 140 else 0, "1")
        text = pytesseract.image_to_string(
            img_bin, lang='kor+eng',
            config='--psm 3 --oem 1',   # 완전 자동 레이아웃, LSTM 전용
        )
        text = _fix_ocr_spacing(text)
        if text.strip():
            pages.append(remove_nul(text.strip()))

    doc.close()
    print(f"  OCR 완료: {len(pages)}페이지 텍스트 추출")
    return "\n\n".join(pages)


# ── 3단계 분리 ────────────────────────────────────────────────────────────

def split_by_part(text: str) -> list[dict]:
    """총론 / 각론 / 부록 분리"""
    matches = list(PART_HDR_RE.finditer(text))
    if not matches:
        return [{'header': '전체', 'body': text.strip()}]

    sections = []
    for i, m in enumerate(matches):
        header = m.group(1).strip()
        start  = m.start()
        end    = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body   = text[start:end].strip()
        if len(body) > 50:
            sections.append({'header': header, 'body': body})
    return sections


def split_by_chapter(text: str) -> list[dict]:
    """제X장 분리"""
    matches = list(CHAPTER_HDR_RE.finditer(text))
    if not matches:
        return [{'header': '', 'body': text.strip()}]

    sections = []

    # 장 헤더 이전 도입부
    intro = text[:matches[0].start()].strip()
    if intro and len(intro) > 20:
        sections.append({'header': '', 'body': intro})

    for i, m in enumerate(matches):
        header = clean_header(m.group(1))
        start  = m.start()
        end    = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body   = text[start:end].strip()
        if len(body) > 20:
            sections.append({'header': header, 'body': body})
    return sections


def split_by_item(text: str) -> list[dict]:
    """번호(1.) → 가나다 순으로 최소 단위 분리
    번호 항목 내에 가나다가 있으면 가나다까지 쪼갬
    없으면 번호 항목 자체가 청크
    """
    num_matches = list(NUM_HDR_RE.finditer(text))

    # 번호 항목 자체가 없으면 전체를 하나로
    if not num_matches:
        return [{'header': '', 'body': text.strip(), 'section_title': ''}]

    items = []

    # 번호 이전 도입부
    intro = text[:num_matches[0].start()].strip()
    if intro and len(intro) > 20:
        items.append({'header': '', 'body': intro, 'section_title': ''})

    for i, m in enumerate(num_matches):
        num        = int(m.group(1))
        title      = clean_header(m.group(2))
        num_header = f"{num}. {title}"
        start      = m.start()
        end        = num_matches[i + 1].start() if i + 1 < len(num_matches) else len(text)
        body       = text[start:end].strip()

        # 번호 항목 내 가나다 존재 여부 확인
        kor_matches = list(KOR_HDR_RE.finditer(body))
        if kor_matches:
            # 가나다 이전 도입부
            kor_intro = body[:kor_matches[0].start()].strip()
            if kor_intro and len(kor_intro) > 20:
                items.append({
                    'header':        num_header,
                    'body':          kor_intro,
                    'section_title': num_header,
                })
            for j, km in enumerate(kor_matches):
                kor       = km.group(1)
                kor_title = clean_header(km.group(2))
                kor_hdr   = f"{kor}. {kor_title}"
                ks        = km.start()
                ke        = kor_matches[j + 1].start() if j + 1 < len(kor_matches) else len(body)
                kor_body  = body[ks:ke].strip()
                if len(kor_body) > 20:
                    items.append({
                        'header':        kor_hdr,
                        'body':          kor_body,
                        'section_title': f"{num_header} {kor_hdr}",
                    })
        else:
            if len(body) > 20:
                items.append({
                    'header':        num_header,
                    'body':          body,
                    'section_title': num_header,
                })

    return items


# ── 크기 정제 ─────────────────────────────────────────────────────────────

def refine_content(text: str, max_size: int = CHUNK_SIZE) -> list[str]:
    """800자 초과 시 문장 단위 분할 → 강제 슬라이싱"""
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


# ── 키워드 추출 / 임베딩 유틸 ─────────────────────────────────────────────

def extract_keywords(text: str, max_kw: int = 10) -> list[str]:
    """
    빈도 기반 키워드 추출.
    한글 2글자 이상 단어 + 대문자 영문 약어를 Counter로 집계,
    STOPWORDS 제거 후 빈도 내림차순 상위 max_kw개를 반환한다.
    """
    kor_words = re.findall(r'[가-힣]{2,}', text)
    eng_words = re.findall(r'\b[A-Z]{2,}\b', text)
    freq = Counter(
        w for w in kor_words + eng_words
        if w not in STOPWORDS
    )
    return [w for w, _ in freq.most_common(max_kw)]


def build_embed_text(disease_name: str, section_title: str, content: str) -> str:
    """임베딩 핵심 텍스트 생성 (500자 이내)."""
    parts = [p for p in [disease_name, section_title] if p]
    header = ' '.join(parts)
    combined = f"{header}: {content}" if header else content
    return combined[:500]


def is_garbage_chunk(content: str) -> bool:
    """가비지 청크 판별.
    한글 30자 미만이거나 한글 비율이 40% 미만이면 True.
    """
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
    총론/각론 → 제X장 → 번호/가나다 항목 순으로 분해
    부록 제외
    """
    body = full_text[TOC_END_POS:]

    # 1단계: 총론/각론/부록 분리
    part_sections = split_by_part(body)
    print(f"  [구조] 총론/각론 {len(part_sections)}개 감지")
    for s in part_sections:
        flag = '✅' if s['header'] in TARGET_PARTS or s['header'] == '전체' else '⏭️  스킵'
        print(f"    {flag}  {s['header']}")
    print()

    # 2단계: 대상만 필터
    target_parts = [
        s for s in part_sections
        if s['header'] in TARGET_PARTS or s['header'] == '전체'
    ]

    chunks     = []
    global_idx = 0

    for part in target_parts:
        part_title    = part['header']
        chap_sections = split_by_chapter(part['body'])
        print(f"  {part_title}  →  제X장 {len(chap_sections)}개")

        for chap in chap_sections:
            chap_title = chap['header']
            items      = split_by_item(chap['body'])

            for item in items:
                content       = item['body']
                section_title = item['section_title'] or chap_title

                sub_chunks = refine_content(content)

                for sub in sub_chunks:
                    sub = remove_nul(sub)
                    if not sub.strip() or len(sub) < 20:
                        continue

                    chunk_id   = f"covid_{global_idx:04d}"
                    chunk_text = (
                        f"{part_title} {chap_title} {section_title}\n{sub}"
                    )

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
                        'chapter':         f"{part_title} {chap_title}".strip(),
                        'section_title':   section_title,
                        'content':         sub,
                        'chunk_text':      remove_nul(chunk_text),
                        'embed_text':      build_embed_text(DISEASE_NAME, section_title, sub),
                        'chunk_index':     global_idx,
                        'keywords':        extract_keywords(
                                               f"{part_title} {chap_title} {section_title} {sub}"
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
    parser.add_argument('--toc',     action='store_true', help='총론/각론/장 구조만 출력')
    args = parser.parse_args()

    print(f"[코로나19 파서] 시작")
    print(f"  입력: {PDF_FILENAME}\n")

    if not PDF_PATH.exists():
        print(f"[오류] 파일 없음: {PDF_PATH}")
        return

    try:
        raw_text = extract_pdf_text(PDF_PATH)
    except Exception as e:
        print(f"[오류] 텍스트 추출 실패: {e}")
        return

    raw_text = clean_sidebar(raw_text)
    print(f"  추출 완료: {len(raw_text):,}자\n")

    # --toc: 구조 확인만 하고 종료
    if args.toc:
        body = raw_text[TOC_END_POS:]
        parts = split_by_part(body)
        print("── 총론/각론 구조 ────────────────────────")
        for p in parts:
            flag = '✅' if p['header'] in TARGET_PARTS or p['header'] == '전체' else '⏭️'
            print(f"\n  {flag}  [{p['header']}]")
            chaps = split_by_chapter(p['body'])
            for c in chaps:
                if c['header']:
                    items = split_by_item(c['body'])
                    print(f"      📄  {c['header'][:60]}  ({len(items)}개 항목)")
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
        print()

    if args.preview:
        print("[preview] JSON 저장 건너뜀")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    print(f"[완료] 저장: {OUTPUT_FILE}")
    print(f"  청크 {total}개")


if __name__ == '__main__':
    main()

"""
parsers/DATA_004_parse_hiv.py
2026년 HIV/AIDS 관리지침 PDF → 청킹 → JSON 저장

PDF 구조:
  Ⅰ. 총론
    1. HIV 검진
      가. 목적 및 근거
  Ⅱ. HIV 감염인 관리·지원
    1. 개요
      가. 목적 및 근거
  Ⅳ. HIV/AIDS 교육·홍보
  Ⅴ. HIV/AIDS (각론 — 병원체·임상·진단·치료·예방·FAQ)

파싱 대상:
  ✅ Ⅰ. 총론
  ✅ Ⅱ. HIV 감염인 관리·지원
  ✅ Ⅳ. HIV/AIDS 교육·홍보
  ✅ Ⅴ. HIV/AIDS (각론)
  ⏭️  Ⅲ. 민간보조사업 및 위탁사업  (파싱 제외)
  ⏭️  Ⅵ. 서식                      (파싱 제외)
  ⏭️  Ⅶ. 부록                      (파싱 제외)
  ⏭️  "문구 수정" 챕터               (개정 비교표 전용 — 파싱 제외)
  ⏭️  마. 의료기관 자체판정 등록 방법 (DATA_012 system_manual 중복 — 파싱 제외)

PDF 노이즈 유형 및 해결책:
  - 매 페이지 running header 반복 → 같은 로마자 단원 병합
  - "문구 수정" 챕터(개정 비교표) → 스킵
  - 제목/줄 내 구문 반복 → dedup_inline()
  - 개정사유 컬럼 잔여물 → clean_comparison_artifacts()
  - 페이지 번호 인라인 삽입 → _COMPARISON_PATTERNS
  - section_title에 우측 열 텍스트 → clean_section_title_field() 트리밍

출력: parsed/DATA_004_chunks_hiv.json
"""

import sys
import re
import json
from collections import Counter, defaultdict
import argparse
from pathlib import Path

import pdfplumber

sys.path.append(str(Path(__file__).parent.parent))
from config import GUIDELINE_PDF_DIR, CHUNK_SIZE

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 설정 ─────────────────────────────────────────────────────────────────
PDF_FILENAME     = "2026년 HIVAIDS 관리지침.pdf"
PDF_PATH         = GUIDELINE_PDF_DIR / "완료" / PDF_FILENAME
DOC_TITLE        = "2026년 HIV/AIDS 관리지침"
DISEASE_NAME     = "후천성면역결핍증(AIDS)"
OUTPUT_DIR       = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE      = OUTPUT_DIR / "DATA_004_chunks_hiv.json"
DATA_ID          = "DATA-004"
SOURCE_CATEGORY  = "disease"
KNOWLEDGE_TYPE   = "disease_guideline"

TOC_END_POS = 8_000

# ── 대상 / 제외 단원 ──────────────────────────────────────────────────────
TARGET_KEYWORDS = ['총론', 'HIV', 'AIDS', '에이즈', '후천성면역']

# 제외할 챕터 패턴
_SKIP_CHAPTER_RE = [
    re.compile(r'민간보조사업'),
    re.compile(r'서\s*식'),
    re.compile(r'부\s*록'),
    re.compile(r'문구\s*수정'),   # 개정 비교표 챕터
]

# 제외할 섹션 패턴 (가나다 항목 수준)
# DATA_012에서 system_manual 타입으로 별도 파싱하는 섹션
_SKIP_SECTION_RE = [
    re.compile(r'의료기관\s*자체판정\s*등록'),  # 마. 의료기관 자체판정 등록 방법(에이즈지원시스템)
]

# ── 헤더 정규식 ───────────────────────────────────────────────────────────
ROMAN_CHARS = 'ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ'
ROMAN_HDR_RE = re.compile(
    rf'^([{ROMAN_CHARS}]+[. \t·]*[^\n]{{0,80}})$',
    re.MULTILINE,
)
NUM_HDR_RE = re.compile(
    r'^(\d{1,2})\.\s+([^\n]{1,80})$',
    re.MULTILINE,
)
KOR_HDR_RE = re.compile(
    r'^([가나다라마바사아자차카타파하])\.\s+([^\n]{1,60})$',
    re.MULTILINE,
)

# ── STOPWORDS ─────────────────────────────────────────────────────────────
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
    '에이즈',
}

# ── 사이드바 노이즈 패턴 ─────────────────────────────────────────────────
_SIDEBAR_PATTERNS = [
    re.compile(r'^www\.kdca\.go\.kr[^\n]*$',   re.MULTILINE),
    re.compile(r'^\s*[ivxIVX]+\s*$',           re.MULTILINE),   # 로마자 페이지
    re.compile(r'^\s*\d+\s*$',                 re.MULTILINE),   # 숫자 페이지
    re.compile(r'^\s*[가-힣]\s*$',              re.MULTILINE),   # 세로 한 글자
    re.compile(r'^\s*총론\s*$',                 re.MULTILINE),
    re.compile(r'^\s*각론\s*$',                 re.MULTILINE),
    re.compile(r'^\s*부록\s*$',                 re.MULTILINE),
    re.compile(r'[●◆■]{1,3}\s*2026[^\n]*관리지침[^\n]*', re.MULTILINE),
]

# ── 개정 비교표 잔여물 패턴 ──────────────────────────────────────────────
_COMPARISON_PATTERNS = [
    re.compile(r'구분\s+변경\s*전\s+변경\s*후(\s+개정사유)?'),
    re.compile(r'[·•ㆍ]\s*(문구\s*수정|삭제|추가|변경|현행화|반영|신설)[^\n]{0,60}'),
    re.compile(r'\(신설\)|\(삭제\)|\(추가\)|\(변경\)|\(이동\)|\(현행화\)'),
    re.compile(r'\s+(삭제|추가|반영|현행화)\s*$', re.MULTILINE),
    re.compile(r'^\d{1,3}(?:~\d{1,3})?\s+[·•ㆍ]', re.MULTILINE),
    re.compile(r'^\d{1,3}(?:~\d{1,3})?\s+(?=[가-힣A-Z])', re.MULTILINE),
]

_SENT_END_RE = re.compile(r'(?<=[다요함됨임])\.\s+')


# ── 유틸 ─────────────────────────────────────────────────────────────────

def remove_nul(text: str) -> str:
    return text.replace('\x00', '')


def normalize_roman(header: str) -> str:
    """로마자 단원 정규화 키 (병합용) — 앞의 로마자만 추출."""
    m = re.match(rf'^([{ROMAN_CHARS}]+)', header.strip())
    if m:
        return m.group(1)
    return re.sub(r'\s+', '', header)[:10]


def clean_header_line(text: str) -> str:
    """헤더에서 점선/페이지 번호 제거, 내부 공백 정규화."""
    text = re.sub(r'[\s·.]{2,}\d*\s*$', '', text)
    text = re.sub(r'\s+\d+\s*$', '', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)   # 내부 다중 공백 → 단일 공백
    return text.strip()


def dedup_inline(text: str) -> str:
    """
    줄 내 반복 구문 제거.
    "나. 기본 방향 나. 기본 방향" → "나. 기본 방향"
    최대 3회 반복.
    """
    for _ in range(3):
        prev = text
        text = re.sub(r'(\S.{4,}?)\s{1,3}\1', r'\1', text)
        if text == prev:
            break
    return text


def dedup_lines(text: str) -> str:
    """연속 중복 줄 제거."""
    lines = text.split('\n')
    result, prev = [], None
    for line in lines:
        s = line.strip()
        if s != prev:
            result.append(line)
        prev = s
    return '\n'.join(result)


def clean_comparison_artifacts(text: str) -> str:
    """개정 비교표 잔여물 제거."""
    for pat in _COMPARISON_PATTERNS:
        text = pat.sub('', text)
    return text



# 비교표 구분점 (U+00B7 MIDDLE DOT, U+2022 BULLET, U+318D, U+2024 ONE DOT LEADER)
# ⚠️  U+002E (일반 마침표)는 제외 — 번호 뒤 점("7.")에 오탐 방지
_SEP_DOTS = '[·•ㆍ․]'
# 비교표 주석 제거용: 마침표도 포함 (챕터/섹션 제목 뒤 annotation 제거 목적)
_DOT_CHARS = '[·•ㆍ․.]'

def clean_chapter_title(title: str) -> str:
    """
    chapter 필드 정제.
    - 개정 비교표 주석 제거: "Ⅰ. 총론 ․ 문구 수정" → "Ⅰ. 총론"
    - U+2024 ONE DOT LEADER 포함
    - 인라인 중복 제거
    """
    title = re.sub(
        _DOT_CHARS + r'\s*(문구\s*수정|개정|삭제|추가)[^\n]{0,50}', '', title
    )
    title = dedup_inline(title)
    title = re.sub(r'[\s·.]{2,}\d*\s*$', '', title)
    return title.strip()


def clean_section_title(title: str) -> str:
    """
    section_title 필드 정제.
    - 인라인 중복 제거
    - 개정 주석 제거 (U+2024 포함)
    - 점 문자 + "단어+조사" 형태의 비교표 잔여물 제거
    - 우측 열 잔여 텍스트 제거
    """
    title = re.sub(_DOT_CHARS + r'\s*(문구\s*수정|현행화|삭제|추가)[^\n]{0,50}', '', title)
    # 비교표 구분점 뒤에 "단어+조사" 형태의 잔여물 제거 (_SEP_DOTS: U+002E 제외)
    # 예: "1. 비전 ․ HIV는 나. 기본 방향" → "1. 비전 나. 기본 방향"
    title = re.sub(
        _SEP_DOTS + r'\s*\S{1,20}(?:는|이|가|을|를|에|와|과|의|으로|로|에서|에게)\s+',
        ' ', title,
    )
    title = dedup_inline(title)
    title = re.sub(r'[\s·.]{2,}\d*\s*$', '', title)
    # 마지막 토큰이 조사/접속사로 끝나는 단편이면 제거
    # 예: "나. 기본 방향 에이즈학회와" → "나. 기본 방향"
    title = re.sub(r'\s+[가-힣]{2,10}(와|과|의|을|를|이|가|에|으로|로|에서|에게)$', '', title)
    return title.strip()


def apply_content_cleaning(text: str) -> str:
    """content 블록에 전체 클리닝 적용."""
    text = clean_comparison_artifacts(text)
    lines = [dedup_inline(line) for line in text.split('\n')]
    text = '\n'.join(lines)
    text = dedup_lines(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    return text.strip()


# ── PDF 추출 ─────────────────────────────────────────────────────────────

def extract_pdf_text(pdf_path: Path) -> str:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        print(f"  총 {len(pdf.pages)}페이지")
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(remove_nul(text.strip()))
    return "\n\n".join(pages)


def clean_sidebar(text: str) -> str:
    for pat in _SIDEBAR_PATTERNS:
        text = pat.sub('', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def is_target_chapter(header: str, body_preview: str = '') -> bool:
    """파싱 대상 단원인지 확인.
    - 제외 패턴: 헤더(단원명)에만 적용  (body에 "문구 수정"이 있어도 총론은 포함)
    - 대상 키워드: 헤더 + body 앞부분 검사 (제목이 다음 줄에 있는 경우 대응)
    """
    # 명시적 제외 패턴은 헤더에만 적용
    for pat in _SKIP_CHAPTER_RE:
        if pat.search(header):
            return False
    # TARGET_KEYWORDS 는 헤더 + body 앞부분 검사
    combined = header + ' ' + body_preview[:300]
    h = combined.upper()
    return any(kw.upper() in h for kw in TARGET_KEYWORDS)


# ── 단원 분리 및 병합 ─────────────────────────────────────────────────────

def split_and_merge_roman(text: str) -> list[dict]:
    """
    로마자 단원 분리 후 같은 단원(running header) 병합.
    PDF 매 페이지 헤더 반복으로 인해 같은 단원이 수십 개로 쪼개지는 문제 해결.
    """
    matches = list(ROMAN_HDR_RE.finditer(text))
    if not matches:
        return [{'header': '전체', 'body': text.strip()}]

    raw_sections = []
    for i, m in enumerate(matches):
        header = clean_header_line(m.group(1))
        start  = m.start()
        end    = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body   = text[start:end].strip()
        if len(body) > 30:
            raw_sections.append({'header': header, 'body': body})

    def enrich_header(raw_header: str, body: str) -> str:
        """
        로마자만 있는 헤더(예: 'Ⅱ')에 body 첫 줄 제목을 붙여 완성.
        예: 'Ⅱ' + body 시작 'Ⅱ\nHIV 감염인 관리·지원\n...' → 'Ⅱ. HIV 감염인 관리·지원'
        PDF 레이아웃상 로마자와 제목이 별도 줄에 출력되는 경우 처리.
        """
        h = clean_chapter_title(raw_header)
        # 헤더가 로마자만 있을 때 body 앞 줄에서 제목 추출
        if re.fullmatch(rf'[{ROMAN_CHARS}]+', h.strip()):
            lines = body.split('\n')
            for line in lines[:5]:
                candidate = line.strip()
                # 로마자로 시작하면 제목 부분만 추출
                if re.match(rf'^[{ROMAN_CHARS}]', candidate):
                    candidate = re.sub(rf'^[{ROMAN_CHARS}]+[. \t·]*', '', candidate).strip()
                # 개정 비교표 주석 제거 ("총론 ․ 문구 수정" → "총론")
                candidate = re.sub(
                    _SEP_DOTS + r'\s*(문구\s*수정|개정|삭제|추가)[^\n]{0,50}', '', candidate
                ).strip()
                # 충분한 길이의 제목 줄이면 붙임
                if 2 <= len(candidate) <= 60 and not re.search(r'\d{2,}', candidate):
                    h = f"{h}. {candidate}"
                    break
        return h

    # 같은 로마자 단원끼리 병합 (순서 유지)
    merged: dict[str, dict] = {}
    order: list[str] = []
    for s in raw_sections:
        key = normalize_roman(s['header'])
        if key not in merged:
            header = enrich_header(s['header'], s['body'])
            merged[key] = {'header': header, 'body': s['body']}
            order.append(key)
        else:
            # 더 긴(더 상세한) 헤더를 선호
            existing = merged[key]['header']
            candidate = enrich_header(s['header'], s['body'])
            if len(candidate) > len(existing):
                merged[key]['header'] = candidate
            merged[key]['body'] += '\n\n' + s['body']

    return [merged[k] for k in order]


def split_by_number(text: str) -> list[dict]:
    matches = list(NUM_HDR_RE.finditer(text))
    if not matches:
        return [{'header': '', 'body': text.strip(), 'num': 0}]
    sections = []
    for i, m in enumerate(matches):
        num    = int(m.group(1))
        title  = clean_header_line(m.group(2))
        # 제목이 숫자로 시작하면 날짜/잔여물로 간주 스킵 (예: "1. 1.부터 지급 가능)")
        if re.match(r'^\d', title):
            continue
        header = f"{num}. {title}"
        start  = m.start()
        end    = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body   = text[start:end].strip()
        if len(body) > 20:
            sections.append({'header': header, 'body': body, 'num': num})
    return sections


def split_by_korean(text: str) -> list[dict]:
    matches = list(KOR_HDR_RE.finditer(text))
    if not matches:
        return [{'header': '', 'body': text.strip()}]
    sections = []
    intro = text[:matches[0].start()].strip()
    if intro and len(intro) > 20:
        sections.append({'header': '', 'body': intro})
    for i, m in enumerate(matches):
        kor    = m.group(1)
        title  = clean_header_line(m.group(2))
        header = f"{kor}. {title}"
        start  = m.start()
        end    = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body   = text[start:end].strip()
        if len(body) > 20:
            sections.append({'header': header, 'body': body})
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

def build_chunks(full_text: str) -> tuple[list[dict], dict]:
    body = full_text[TOC_END_POS:]

    # 1단계: 로마자 단원 분리 + 병합
    roman_sections = split_and_merge_roman(body)
    print(f"\n  [구조] 병합 후 로마자 단원 {len(roman_sections)}개")
    for s in roman_sections:
        flag = '✅' if is_target_chapter(s['header'], s['body']) else '⏭️  스킵'
        print(f"    {flag}  {s['header'][:70]}")

    target_sections = [s for s in roman_sections if is_target_chapter(s['header'], s['body'])]
    print(f"\n  [필터] 파싱 대상: {len(target_sections)}개 단원")

    chunks     = []
    global_idx = 0
    toc_log: dict[str, list[str]] = defaultdict(list)

    for roman_sec in target_sections:
        chapter_title = roman_sec['header']
        num_sections  = split_by_number(roman_sec['body'])
        print(f"\n  ▶ {chapter_title}  ({len(num_sections)}개 절)")

        for num_sec in num_sections:
            num_title    = num_sec['header']
            kor_sections = split_by_korean(num_sec['body'])

            for kor_sec in kor_sections:
                kor_title = kor_sec['header']

                # system_manual 섹션 스킵 (DATA_012에서 별도 파싱)
                if any(pat.search(kor_title) for pat in _SKIP_SECTION_RE):
                    print(f"    ⏭️  system_manual 스킵: {kor_title[:60]}")
                    continue

                raw_content = kor_sec['body']

                # section_title 조합 및 정제
                raw_section   = ' '.join(filter(None, [num_title, kor_title])).strip()
                section_title = clean_section_title(raw_section)

                # content 정제
                content = apply_content_cleaning(raw_content)

                sub_chunks = refine_content(content)

                for sub in sub_chunks:
                    sub = remove_nul(sub)
                    if not sub.strip() or len(sub) < 20:
                        continue

                    chunk_id   = f"hiv_{global_idx:04d}"
                    chunk_text = f"{chapter_title} {section_title}\n{sub}".strip()

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
                        'chapter':         chapter_title,
                        'section_title':   section_title,
                        'content':         sub,
                        'chunk_text':      remove_nul(chunk_text),
                        'embed_text':      build_embed_text(DISEASE_NAME, section_title, sub),
                        'chunk_index':     global_idx,
                        'keywords':        extract_keywords(
                                               f"{chapter_title} {section_title} {sub}"
                                           ),
                        'source':          PDF_FILENAME,
                        'embedding':       None,
                    })

                    if section_title not in toc_log[chapter_title]:
                        toc_log[chapter_title].append(section_title)

                    global_idx += 1

    return chunks, dict(toc_log)


# ── 메인 ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='샘플 출력만, JSON 저장 없음')
    parser.add_argument('--toc',     action='store_true', help='단원 구조만 출력')
    args = parser.parse_args()

    print(f"[HIV/AIDS 파서] 시작")
    print(f"  입력: {PDF_FILENAME}")
    print(f"  출력: {OUTPUT_FILE}\n")

    if not PDF_PATH.exists():
        print(f"[오류] 파일 없음: {PDF_PATH}")
        return

    try:
        raw_text = extract_pdf_text(PDF_PATH)
    except Exception as e:
        print(f"[오류] 텍스트 추출 실패: {e}")
        return

    raw_text = clean_sidebar(raw_text)
    print(f"  추출 완료: {len(raw_text):,}자")

    if args.toc:
        body = raw_text[TOC_END_POS:]
        sections = split_and_merge_roman(body)
        print("\n── 로마자 단원 목록 (병합 후) ────────────────")
        for s in sections:
            flag = '✅' if is_target_chapter(s['header'], s['body']) else '⏭️'
            print(f"  {flag}  {s['header'][:80]}")
            num_secs = split_by_number(s['body'])
            for n in num_secs[:5]:
                print(f"        {n['header'][:60]}")
            if len(num_secs) > 5:
                print(f"        ... 외 {len(num_secs) - 5}개 절")
        return

    all_chunks, toc_log = build_chunks(raw_text)
    total = len(all_chunks)

    # ── 파싱된 단원 목차 출력 ──────────────────────────────────────────────
    print("\n\n══ 파싱된 단원 목차 ══════════════════════════════════════")
    for chapter, sections in toc_log.items():
        print(f"\n  [{chapter}]")
        for sec in sections:
            cnt = sum(1 for c in all_chunks if c['section_title'] == sec)
            label = sec if sec else '(서두 본문)'
            print(f"    • {label}  ({cnt}청크)")
    print(f"\n  총 {total}개 청크\n")

    # ── 샘플 출력 ─────────────────────────────────────────────────────────
    print("── 샘플 청크 (처음 3개) ────────────────────────")
    for c in all_chunks[:3]:
        print(f"  source_id   : {c['source_id']}")
        print(f"  chapter     : {c['chapter']}")
        print(f"  section     : {c['section_title']}")
        print(f"  content 길이: {len(c['content'])}자")
        print(f"  content 앞80: {c['content'][:80]!r}")
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

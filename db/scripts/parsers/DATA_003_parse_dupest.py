"""
parsers/parse_dupest.py
제1급감염병 두창·페스트·탄저·보툴리눔독소증·야토병 대응지침 PDF
→ 질병별/섹션별 청킹 → JSON 저장

PDF 구조 (VHF와 동일):
  PART Ⅰ. 총론   ← 공통 대응절차
  PART Ⅱ. 각론
    제1장. 두창
    제2장. 페스트
    제3장. 탄저
    제4장. 보툴리눔독소증
    제5장. 야토병
      → 각 질병 내부: 1.개요 / 2.발생현황 / 3.역학적특성 / 4.임상적특징
                       5.실험실검사 / 6.치료 / 7.예방
  PART Ⅲ. 부록   ← 제외
  PART Ⅳ. 서식   ← 제외

출력: parsed/chunks_dupest.json

실행:
    python parsers/parse_dupest.py           ← JSON 저장
    python parsers/parse_dupest.py --preview ← 샘플 출력만
"""

import sys
import re
import json
from collections import Counter
import argparse
from pathlib import Path

import pdfplumber

sys.path.append(str(Path(__file__).parent.parent))
from config import GUIDELINE_PDF_DIR

# ── 설정 ─────────────────────────────────────────────────────────────────
PDF_FILENAME   = "제1급감염병 두창 페스트 탄저 보툴리눔독소증 야토병 대응지침.pdf"
PDF_PATH       = GUIDELINE_PDF_DIR / "완료" / PDF_FILENAME
DOC_TITLE      = "제1급감염병 두창 페스트 탄저 보툴리눔독소증 야토병 대응지침"
DISEASE_GROUP  = "두창·페스트·탄저·보툴리눔독소증·야토병"
OUTPUT_DIR       = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE      = OUTPUT_DIR / "DATA_003_chunks_dupest.json"
DATA_ID          = "DATA-003"
SOURCE_CATEGORY  = "disease"
KNOWLEDGE_TYPE   = "disease_guideline"

# ── 패턴 ─────────────────────────────────────────────────────────────────
# 각론 시작 앵커
KAKRON_RE   = re.compile(r'Part\s*[Ⅱ2]\.\s*각론', re.IGNORECASE)

# 각론 종료 앵커 (부록/서식 시작)
APPENDIX_RE = re.compile(
    r'Part\s*[Ⅲ3]\.\s*부\s*록|PART\s*[Ⅲ3]|Part\s*[Ⅳ4]\.\s*서\s*식',
    re.IGNORECASE
)

# 질병 챕터: "제N장 질병명" 또는 "제N장. 질병명"
CHAPTER_RE  = re.compile(r'제(\d+)장[.\s]\s*([가-힣\(\)A-Za-z\s,·]+?)(?=\n|$)', re.MULTILINE)

# 번호 서브섹션: "1. 개요", "2. 발생현황" 등
SECTION_RE  = re.compile(r'\n(\d+)\.\s+([가-힣·\s]{2,20})\n', re.MULTILINE)

# 사이드바/헤더 노이즈 패턴 (두창 PDF는 VHF와 동일한 구조)
SIDEBAR_PATTERNS = [
    # 페이지 헤더 (줄 전체)
    re.compile(r'^제1급감염병 두창[^\n]*대응지침\s*$', re.MULTILINE),
    re.compile(r'^제\d+급 감염병 기본 대응방향\s*$', re.MULTILINE),
    re.compile(r'^Part\s*[ⅠⅡⅢⅣ]\.\s*[총각부]\s*론?\s*$', re.MULTILINE),
    re.compile(r'^Part\s*[ⅠⅡⅢⅣ]\.\s*서\s*식?\s*$', re.MULTILINE),

    # 세로 사이드바 — 줄 단독
    re.compile(r'^\s*[ⅠⅡⅢⅣⅤ]\s*$', re.MULTILINE),
    re.compile(r'^\s*총\s*$', re.MULTILINE),
    re.compile(r'^\s*각\s*$', re.MULTILINE),
    re.compile(r'^\s*론\s*$', re.MULTILINE),
    re.compile(r'^\s*부\s*$', re.MULTILINE),
    re.compile(r'^\s*록\s*$', re.MULTILINE),
    re.compile(r'^\s*서\s*$', re.MULTILINE),
    re.compile(r'^\s*식\s*$', re.MULTILINE),

    # 본문 줄 끝에 붙어있는 로마자 사이드바 마커
    re.compile(r'[ \t]+[ⅠⅡⅢⅣⅤ]\s*\n'),

    # 연결된 사이드바 문자열
    re.compile(r'[ⅠⅡⅢⅣⅤ]\n[총각부서]\n[론록식]\n?'),
    re.compile(r'\n부\n록\n?'),
    re.compile(r'\n서\n식\n?'),
    re.compile(r'\n총\n론\n?'),
    re.compile(r'\n각\n론\n?'),

    # 페이지 번호 단독 줄
    re.compile(r'^\s*\d+\s*$', re.MULTILINE),
    # 세로 급수 사이드바
    re.compile(r'제\n\d+\n급\s*\n감\n염\n병\n?'),
]


# ── NUL 제거 ─────────────────────────────────────────────────────────────
def remove_nul(text: str) -> str:
    return text.replace('\x00', '')


# ── 사이드바 노이즈 제거 ──────────────────────────────────────────────────
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


# ── 총론/각론 분리 ────────────────────────────────────────────────────────
def extract_kakron(full_text: str) -> tuple[str, str]:
    m_start = KAKRON_RE.search(full_text)
    if not m_start:
        print("  [경고] 'Part Ⅱ. 각론' 앵커 미발견 → 전체 텍스트를 각론으로 처리")
        return '', full_text

    kakron_start = m_start.start()
    m_end = APPENDIX_RE.search(full_text, kakron_start + 100)
    kakron_end = m_end.start() if m_end else len(full_text)

    chonron_text = full_text[:kakron_start]
    kakron_text  = full_text[kakron_start:kakron_end]

    print(f"  각론 끝 경계: {'부록 앵커 감지' if m_end else '문서 끝'}")
    return chonron_text, kakron_text


# ── 질병 챕터 분할 ────────────────────────────────────────────────────────
def split_by_chapter(kakron_text: str) -> list[dict]:
    matches = list(CHAPTER_RE.finditer(kakron_text))
    if not matches:
        print("  [경고] 챕터 패턴(제N장) 미발견 → 전체를 단일 블록으로 처리")
        return [{'chapter_no': 0, 'disease_name': DISEASE_GROUP, 'text': kakron_text}]

    chapters = []
    for i, m in enumerate(matches):
        chapter_no   = int(m.group(1))
        disease_name = re.sub(r'\(.*?\)', '', m.group(2)).strip()
        disease_name = re.sub(r'[A-Za-z].*$', '', disease_name).strip()  # 영문 이후 제거
        disease_name = re.sub(r'\s+', ' ', disease_name).strip()

        # 참조·목차성 챕터 제외 (비질병 키워드)
        junk = {'자원관리', '대응체계', '사례정의', '실험실검사', '참조', '참고'}
        if not disease_name or any(kw in disease_name for kw in junk):
            continue

        start = m.start()
        end   = matches[i + 1].start() if i + 1 < len(matches) else len(kakron_text)
        text  = clean_text(kakron_text[start:end])

        # 내부에 실제 섹션 번호(1. 개요 등)가 있는 블록만 유효
        has_sections = bool(SECTION_RE.search('\n' + text))
        if not has_sections:
            continue  # 참조 문구 블록 제외

        if len(text) > 200:
            chapters.append({
                'chapter_no':   chapter_no,
                'disease_name': disease_name,
                'text':         text,
            })

    return chapters


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


# ── STOPWORDS ─────────────────────────────────────────────────────────────
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
}


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


# ── 각론 청크 생성 ────────────────────────────────────────────────────────
def build_chunks(chapters: list[dict], source: str) -> list[dict]:
    chunks = []
    for chap in chapters:
        dname    = chap['disease_name']
        chap_no  = chap['chapter_no']
        sections = split_by_section(chap['text'])

        for sec in sections:
            sec_no    = sec['sec_no']
            sec_title = sec['sec_title']
            content   = remove_nul(sec['content'])
            if not content.strip() or len(content) < 30:
                continue

            safe_name  = re.sub(r'[^\w가-힣]', '', dname)[:20]
            chunk_id   = f"dupest_ch{chap_no:02d}_sec{sec_no:02d}_{safe_name}"
            chunk_text = f"{dname} {sec_title}\n{content}"

            if is_garbage_chunk(content):
                continue

            chunks.append({
                'source_id':       chunk_id,
                'data_id':         DATA_ID,
                'source_category': SOURCE_CATEGORY,
                'knowledge_type':  KNOWLEDGE_TYPE,
                'disease_name':    dname,
                'document_title':  DOC_TITLE,
                'chapter':         f"제{chap_no}장 {dname}",
                'section_title':   sec_title,
                'content':         content,
                'chunk_text':      remove_nul(chunk_text),
                'embed_text':      build_embed_text(dname, sec_title, content),
                'chunk_index':     sec_no,
                'keywords':        extract_keywords(f"{dname} {sec_title} {content}"),
                'source':          source,
                'embedding':       None,
            })

    return chunks


# ── 총론 청킹 ─────────────────────────────────────────────────────────────
CHONRON_CHUNK_SIZE = 1200
CHONRON_MIN_SIZE   = 100
_SENT_END_RE = re.compile(r'(?<=[다요함됨임])\.\s+')


def _split_paragraphs(text: str) -> list[str]:
    raw = re.split(r'\n{2,}', text)
    paragraphs = []
    header_re = re.compile(
        r'^(제\s*\d+\s*[장절]|\d{1,2}\.\s+\S|[가나다라마바사아]\.\s|[①②③④⑤]\s|[○●▶■]\s)'
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
        chunk_text = remove_nul(f"{DISEASE_GROUP} 총론\n{content}")
        if is_garbage_chunk(content):
            continue

        chunks.append({
            'source_id':       f"dupest_chonron_{i:03d}",
            'data_id':         DATA_ID,
            'source_category': SOURCE_CATEGORY,
            'knowledge_type':  KNOWLEDGE_TYPE,
            'disease_name':    DISEASE_GROUP,
            'document_title':  DOC_TITLE,
            'chapter':         '총론',
            'section_title':   '대응절차',
            'content':         content,
            'chunk_text':      chunk_text,
            'embed_text':      build_embed_text(DISEASE_GROUP, '대응절차', content),
            'chunk_index':     i,
            'keywords':        extract_keywords(content),
            'source':          source,
            'embedding':       None,
        })
    return chunks


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='샘플 출력만, JSON 저장 없음')
    args = parser.parse_args()

    print(f"[두창·페스트·탄저·보툴리눔·야토병 파서] 시작")
    print(f"  입력: {PDF_FILENAME}\n")

    print("[1단계] PDF 텍스트 추출 중...")
    full_text = extract_full_text(PDF_PATH)
    print(f"  추출 완료: {len(full_text):,}자\n")

    print("[2단계] 총론/각론 분리 중...")
    chonron_text, kakron_text = extract_kakron(full_text)
    print(f"  총론: {len(chonron_text):,}자 / 각론: {len(kakron_text):,}자\n")

    print("[3단계] 질병 챕터 분할 중...")
    chapters = split_by_chapter(kakron_text)
    print(f"  질병 챕터 {len(chapters)}개 감지:")
    for c in chapters:
        print(f"    제{c['chapter_no']}장. {c['disease_name']} ({len(c['text']):,}자)")
    print()

    print("[4단계] 청크 생성 중...")
    all_chunks  = build_chonron_chunks(chonron_text, PDF_FILENAME)
    all_chunks += build_chunks(chapters, PDF_FILENAME)
    chonron_cnt = len([c for c in all_chunks if c['chapter'] == '총론'])
    kakron_cnt  = len([c for c in all_chunks if c['chapter'] != '총론'])
    print(f"  총론 청크: {chonron_cnt}개")
    print(f"  각론 청크: {kakron_cnt}개")
    print(f"  전체: {len(all_chunks)}개\n")

    # 미리보기
    print("── 샘플 청크 (각론 처음 5개) ─────────────────────")
    kakron_chunks = [c for c in all_chunks if c['chapter'] != '총론']
    for c in kakron_chunks[:5]:
        print(f"  ID           : {c['source_id']}")
        print(f"  disease_name : {c['disease_name']}")
        print(f"  chapter      : {c['chapter']}")
        print(f"  section_title: {c['section_title']}")
        print(f"  content 길이 : {len(c['content'])}자")
        print(f"  keywords     : {c['keywords'][:5]}")
        print()

    if args.preview:
        print("[preview] JSON 저장 건너뜀")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    print(f"[완료] 저장: {OUTPUT_FILE}")
    print(f"  질병 챕터 {len(chapters)}개 / 전체 청크 {len(all_chunks)}개")


if __name__ == '__main__':
    main()

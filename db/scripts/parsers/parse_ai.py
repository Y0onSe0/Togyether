"""
parsers/parse_ai.py
제1급감염병 동물인플루엔자 인체감염증 대응지침 PDF
→ 질병 소분류별 청킹 → JSON 저장

PDF 구조 (212페이지):
  PART Ⅰ. 총 론
    제1장.  동물인플루엔자 인체감염증 개요      → chapter='동물인플루엔자'
    제2장.  조류인플루엔자(AI) 인체감염증 개요   ┐
    제3장.  조류인플루엔자 발생 대비 대응 체계   │
    제4장.  사례 정의                            │→ chapter='조류인플루엔자'
    제5장.  의사환자 발생 시 대응                │
    제6장.  확진환자 발생 시 대응                │
    제7장.  실험실 검사 관리                     │
    제8장.  자원 관리                            │
    제9장.  환축 발생 시 조치사항               ┘
    제10장. 돼지인플루엔자 인체감염증 개요       → chapter='돼지인플루엔자'
  PART Ⅱ. 서식  ← 제외

모든 청크의 disease_name = '동물인플루엔자인체감염증'
chapter 필드 = '동물인플루엔자' / '조류인플루엔자' / '돼지인플루엔자'
section_title = 각 장 또는 하위 섹션 제목

출력: parsed/chunks_ai.json

실행:
    python parsers/parse_ai.py           ← JSON 저장
    python parsers/parse_ai.py --preview ← 샘플 출력만
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
PDF_FILENAME  = "제1급감염병 동물인플루엔자 인체감염증 대응지침.pdf"
PDF_PATH      = GUIDELINE_PDF_DIR / "완료" / PDF_FILENAME
DOC_TITLE     = "제1급감염병 동물인플루엔자 인체감염증 대응지침"
DISEASE_NAME  = "동물인플루엔자인체감염증"
CONTENT_TYPE  = "management"
OUTPUT_DIR    = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE   = OUTPUT_DIR / "chunks_ai.json"

# 목차/구분자 영역 종료 위치 (실제 본문은 14,450 이후)
TOC_END_POS   = 14_450

# ── 장 번호 → 질병 그룹 매핑 ─────────────────────────────────────────────
def chapter_to_group(chap_no: int) -> str:
    """제N장 번호를 질병 소분류 그룹으로 변환."""
    if chap_no == 1:
        return '동물인플루엔자'
    elif 2 <= chap_no <= 9:
        return '조류인플루엔자'
    else:          # 제10장 이상 (돼지인플루엔자)
        return '돼지인플루엔자'

# ── 패턴 ─────────────────────────────────────────────────────────────────
# 장 헤더: "제N장. 제목" 또는 "제N장 제목" (단독 줄)
CHAPTER_RE = re.compile(
    r'^제[ \t]*(\d+)[ \t]*장[.\s][ \t]*(.+?)[ \t]*$',
    re.MULTILINE
)

# PART Ⅱ 서식 시작 (부록/서식 제외 경계)
APPENDIX_RE = re.compile(
    r'^PART\s*[ⅡI]+\.\s*서\s*식|^Part\s*Ⅱ\.\s*서\s*식',
    re.MULTILINE
)

# 서브섹션: "1. 개요", "2. 발생 현황" 등
SECTION_RE = re.compile(
    r'\n(\d+)\.\s+([가-힣A-Za-z\(\)\s·]{2,30})\n',
    re.MULTILINE
)

# 사이드바 / 페이지 노이즈
SIDEBAR_PATTERNS = [
    re.compile(r'^제1급감염병 동물인플루엔자 인체감염증 대응지침[^\n]*$', re.MULTILINE),
    re.compile(r'^www\.kdca\.go\.kr[^\n]*$', re.MULTILINE),
    re.compile(r'^\s*\d+\s*$', re.MULTILINE),          # 페이지 번호
    re.compile(r'^\s*[ⅠⅡⅢ]\s*$', re.MULTILINE),
    re.compile(r'^\s*총\s*$', re.MULTILINE),
    re.compile(r'^\s*론\s*$', re.MULTILINE),
    re.compile(r'^\s*서\s*$', re.MULTILINE),
    re.compile(r'^\s*식\s*$', re.MULTILINE),
    re.compile(r'^\s*부\s*$', re.MULTILINE),
    re.compile(r'^\s*록\s*$', re.MULTILINE),
    re.compile(r'\nⅡ\n서\n식\n?'),
    re.compile(r'\nⅠ\n총\n론\n?'),
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


# ── 장별 분리 ─────────────────────────────────────────────────────────────
def split_by_chapter(full_text: str) -> list[dict]:
    """
    TOC 이후 영역에서 제N장 헤더를 탐색하여 장별 텍스트 분리.
    PART Ⅱ 서식 이전까지만 처리.
    반환: [{'chap_no', 'chap_title', 'disease_group', 'text'}, ...]
    """
    # 서식 시작 위치 (상한선)
    m_app = APPENDIX_RE.search(full_text, TOC_END_POS)
    body_end = m_app.start() if m_app else len(full_text)
    print(f"  서식 시작 경계: pos={body_end} ({'서식 앵커 감지' if m_app else '문서 끝'})")

    # 본문 장 헤더 탐색
    body_text = full_text[TOC_END_POS:body_end]
    matches = list(CHAPTER_RE.finditer(body_text))

    if not matches:
        print("  [경고] 장 헤더(제N장) 미발견")
        return []

    chapters = []
    for i, m in enumerate(matches):
        chap_no    = int(m.group(1))
        chap_title = m.group(2).strip()
        start      = m.start()
        end        = matches[i + 1].start() if i + 1 < len(matches) else len(body_text)
        text       = clean_text(body_text[start:end])

        if len(text) > 50:
            chapters.append({
                'chap_no':      chap_no,
                'chap_title':   chap_title,
                'disease_group': chapter_to_group(chap_no),
                'text':         text,
            })

    return chapters


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
    stopwords = {'감염병', '관리', '지침', '경우', '관련', '통해', '대한', '인체감염증', '인플루엔자'}
    for w in words:
        if w not in seen and w not in stopwords:
            seen.add(w)
            result.append(w)
        if len(result) >= max_kw:
            break
    return result


# ── 청크 생성 ─────────────────────────────────────────────────────────────
CHUNK_SIZE = 1200
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


def build_chunks(chapters: list[dict], source: str) -> list[dict]:
    """
    장 목록 → 청크 리스트.
    각 장을 서브섹션으로 분할 후 청킹.
    서브섹션이 너무 크면 단락+크기 기반 재분할.
    """
    chunks = []
    group_counter: dict[str, int] = {}  # 그룹별 청크 인덱스

    for chap in chapters:
        chap_no   = chap['chap_no']
        title     = chap['chap_title']
        group     = chap['disease_group']
        safe_grp  = re.sub(r'[^\w가-힣]', '', group)[:6]
        sections  = split_by_section(chap['text'])

        for sec in sections:
            content = remove_nul(sec['content'])
            if not content.strip() or len(content) < 30:
                continue

            # 섹션이 너무 크면 단락 기반 재분할
            if len(content) > CHUNK_SIZE * 2:
                sub_chunks = _refine_chunks(_split_paragraphs(content))
            else:
                sub_chunks = [content]

            for j, sub in enumerate(sub_chunks):
                sub = remove_nul(sub)
                idx = group_counter.get(group, 0)
                group_counter[group] = idx + 1

                chunk_id   = f"ai_{safe_grp}_ch{chap_no:02d}_sec{sec['sec_no']:02d}_{j:02d}"
                chunk_text = (
                    f"{DOC_TITLE} {group} "
                    f"제{chap_no}장 {title} {sec['sec_title']}\n{sub}"
                )

                chunks.append({
                    'id':             chunk_id,
                    'disease_name':   DISEASE_NAME,
                    'document_title': DOC_TITLE,
                    'chapter':        group,          # '동물인플루엔자' / '조류인플루엔자' / '돼지인플루엔자'
                    'section_title':  f"제{chap_no}장 {title} {sec['sec_title']}".strip(),
                    'content':        sub,
                    'chunk_text':     remove_nul(chunk_text),
                    'chunk_index':    idx,
                    'keywords':       extract_keywords(f"{group} {title} {sec['sec_title']} {sub}"),
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

    print(f"[동물인플루엔자 인체감염증 파서] 시작")
    print(f"  입력: {PDF_FILENAME}\n")

    print("[1단계] PDF 텍스트 추출 중...")
    full_text = extract_full_text(PDF_PATH)
    print(f"  추출 완료: {len(full_text):,}자\n")

    print("[2단계] 장별 분리 중...")
    chapters = split_by_chapter(full_text)
    print(f"  총 {len(chapters)}개 장 감지:")
    for c in chapters:
        print(f"    제{c['chap_no']:02d}장 [{c['disease_group']}] {c['chap_title'][:30]} ({len(c['text']):,}자)")
    print()

    print("[3단계] 청크 생성 중...")
    all_chunks = build_chunks(chapters, PDF_FILENAME)

    # 그룹별 통계
    from collections import Counter
    grp_cnt = Counter(c['chapter'] for c in all_chunks)
    for grp, cnt in sorted(grp_cnt.items()):
        print(f"  {grp}: {cnt}개")
    print(f"  전체: {len(all_chunks)}개\n")

    print("── 샘플 청크 (각 그룹 처음 2개) ─────────────────────")
    shown = Counter()
    for c in all_chunks:
        grp = c['chapter']
        if shown[grp] < 2:
            print(f"  ID           : {c['id']}")
            print(f"  chapter      : {c['chapter']}")
            print(f"  section_title: {c['section_title'][:50]}")
            print(f"  content 길이 : {len(c['content'])}자")
            print()
            shown[grp] += 1

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

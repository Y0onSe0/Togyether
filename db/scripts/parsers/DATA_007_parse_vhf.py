"""
parsers/parse_vhf.py
제1급감염병 바이러스성출혈열 대응지침 PDF → 질병별/계층 청킹 → JSON 저장

PDF 구조:
  PART Ⅰ. 총론                    ← 공통 대응절차
  PART Ⅱ. 각론
    제1장 바이러스성출혈열 (개요)    ← 장 단위 (질병별)
    제2장 에볼라바이러스병
    제3장 마버그열
    제4장 라싸열
    제5장 크리미안콩고출혈열
    제6장 남아메리카출혈열
    제7장 리프트밸리열
      각 장 내부:
        1. 개요                    ← 번호 단위
          가. 정의                  ← 가나다 단위 (최소 청크)
          나. 역사
        2. 발생 현황
        ...
  PART Ⅲ. 부록 / 서식              ← 제외

청킹 단위: 가나다 항목 (있으면) or 번호 항목 → 800자 초과 시 문장 분할

출력: parsed/chunks_vhf.json

실행:
    python parsers/parse_vhf.py           ← JSON 저장
    python parsers/parse_vhf.py --preview ← 샘플 출력만
    python parsers/parse_vhf.py --toc     ← PART/장 구조 확인 (파싱 전 검증용)
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
PDF_FILENAME = "제1급감염병 바이러스성출혈열 대응지침.pdf"
PDF_PATH     = GUIDELINE_PDF_DIR / "완료" / PDF_FILENAME
DOC_TITLE    = "제1급감염병 바이러스성출혈열 대응지침"
OUTPUT_DIR       = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE      = OUTPUT_DIR / "DATA_007_chunks_vhf.json"
DATA_ID          = "DATA-007"
SOURCE_CATEGORY  = "disease"
KNOWLEDGE_TYPE   = "disease_guideline"

# 목차/표지 스킵
TOC_END_POS = 10_000

DISEASE_VHF = "바이러스성출혈열"

# ── 헤더 정규식 ───────────────────────────────────────────────────────────

# PART Ⅱ 각론 시작 (Unicode + ASCII 로마자 모두 허용)
KAKRON_RE = re.compile(
    r'^PART\s+(?:Ⅱ|II)[\.\s]',
    re.MULTILINE | re.IGNORECASE,
)

# PART Ⅲ 이후 부록/서식 시작
APPENDIX_RE = re.compile(
    r'^PART\s+(?:[ⅢⅣⅤ]|III|IV|V)[\.\s]',
    re.MULTILINE | re.IGNORECASE,
)

# 제N장 헤더: "제1장 에볼라바이러스병" / "제 2 장 ..."
CHAPTER_HDR_RE = re.compile(
    r'^(제\s*\d+\s*장[\.\s　].{0,60})$',
    re.MULTILINE,
)

# 번호 항목: "1. 개요"
NUM_HDR_RE = re.compile(
    r'^(\d{1,2})\.\s+([^\n]{1,80})$',
    re.MULTILINE,
)

# 가나다 항목: "가. 정의"
KOR_HDR_RE = re.compile(
    r'^([가나다라마바사아자차카타파하])\.\s+([^\n]{1,80})$',
    re.MULTILINE,
)

# ── 노이즈 제거 ───────────────────────────────────────────────────────────
# ※ PART Ⅰ/Ⅱ 헤더 단독 줄은 제거하지 않음 → 구간 분리 앵커로 사용
SIDEBAR_PATTERNS = [
    re.compile(r'^제1급감염병\s+바이러스성출혈열[^\n]*$', re.MULTILINE),
    re.compile(r'^Viral\s+Hemorrhagic\s+Fever[^\n]*$',  re.MULTILINE),
    re.compile(r'^VHF[^\n]{0,20}$',                     re.MULTILINE),
    re.compile(r'^www\.kdca\.go\.kr[^\n]*$',             re.MULTILINE),
    re.compile(r'^\s*\d+\s*$',                           re.MULTILINE),  # 페이지 번호
    re.compile(r'^\s*[가-힣]\s*$',                        re.MULTILINE),  # 세로 한 글자
    re.compile(r'^\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]\s*$',             re.MULTILINE),  # 로마자 단독 줄
    # 세로 사이드바 개별 글자
    re.compile(r'^\s*총\s*$', re.MULTILINE),
    re.compile(r'^\s*각\s*$', re.MULTILINE),
    re.compile(r'^\s*론\s*$', re.MULTILINE),
    re.compile(r'^\s*부\s*$', re.MULTILINE),
    re.compile(r'^\s*록\s*$', re.MULTILINE),
    re.compile(r'^\s*서\s*$', re.MULTILINE),
    re.compile(r'^\s*식\s*$', re.MULTILINE),
    re.compile(r'^\s*문구수정\s*$', re.MULTILINE),
    # 본문 중간에 끼어드는 Part 섹션 마커
    re.compile(r'^Part\s+[ⅠⅡⅢⅣⅤIVXilvx]+\.\s+[^\n]*$', re.MULTILINE),
    # 로마 소문자 단독 페이지 번호 (i, ii, iii, iv ...)
    re.compile(r'^\s*(?:i{1,3}|iv|vi{0,3}|ix|xi{0,3})\s*$', re.MULTILINE),
    # 흐름도 화살표 단독 줄
    re.compile(r'^\s*[↓↑→←↔▶▷▼▲∘∙]\s*$', re.MULTILINE),
]

# ── 표/그림 블록 제거용 패턴 ─────────────────────────────────────────────
# <표 N> 또는 <그림 N> 캡션 라인
_TABLE_CAPTION_RE = re.compile(
    r'<(?:표|그림)\s*\d+[^>]*>[^\n]*\n?',
    re.MULTILINE,
)
# 다음 구조 요소 앞(번호항목·가나다항목·○불릿·※·빈줄) — 표 블록 끝 탐색용
_NEXT_STRUCT_RE = re.compile(
    r'(?=\n\s*(?:\d{1,2}\.\s|[가나다라마바사아자차카타파하]\.\s|○\s|※\s|\n))',
    re.MULTILINE,
)
# < ... > 다이어그램/흐름도 인라인 라벨 단독 줄
_DIAGRAM_LABEL_RE = re.compile(r'^<[^>\n]{2,80}>\s*$', re.MULTILINE)
# 표 체크박스 행: ○/X/△ 이 두 개 이상 연속 등장하는 줄
_TABLE_ROW_RE = re.compile(
    r'^[^\n]*(?:○[^\n]{0,10}[Xx×X]|[Xx×X][^\n]{0,10}○|○[^\n]{0,5}○)[^\n]*$',
    re.MULTILINE,
)

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
}


# ── 유틸 ─────────────────────────────────────────────────────────────────

def remove_nul(text: str) -> str:
    return text.replace('\x00', '')


def clean_header(text: str) -> str:
    """목차 점선(......) 및 페이지 번호 제거
    예: "제2장 에볼라바이러스병 ··· 30"  → "제2장 에볼라바이러스병"
        "1. 개요 .......... 35"          → "1. 개요"
    """
    text = re.sub(r'[\s·.]{2,}\d*\s*$', '', text)
    text = re.sub(r'\s+\d+\s*$', '', text)
    return text.strip()


def remove_table_blocks(text: str) -> str:
    """<표 N>/<그림 N> 캡션부터 다음 구조 요소까지 표 내용 전체 제거."""
    result = []
    last_end = 0
    for m in _TABLE_CAPTION_RE.finditer(text):
        result.append(text[last_end:m.start()])
        # 캡션 이후 다음 구조 요소(번호항목·가나다·○불릿·빈줄)가 나올 때까지 스킵
        nxt = _NEXT_STRUCT_RE.search(text, m.end())
        last_end = nxt.start() if nxt else len(text)
    result.append(text[last_end:])
    return ''.join(result)


def clean_text(text: str) -> str:
    # 1. <표 N>/<그림 N> 블록 전체 제거 (캡션 + 다단 표 내용)
    text = remove_table_blocks(text)
    # 2. < ... > 다이어그램/흐름도 라벨 제거
    text = _DIAGRAM_LABEL_RE.sub('', text)
    # 3. 표 체크박스 행 제거 (○ ... X 혼재)
    text = _TABLE_ROW_RE.sub('', text)
    # 4. 사이드바·페이지마커 등 제거
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


# ── 총론 / 각론 구간 분리 ──────────────────────────────────────────────────

def split_parts(body: str) -> tuple[str, str]:
    """PART Ⅱ(각론) 시작 / PART Ⅲ+(부록) 시작 기준으로 구간 분리.

    주의: 목차에 'PART III 부록' 등이 언급되어 APPENDIX_RE가 너무 일찍
    매칭될 수 있으므로, 각론(kakron_start) 이후 구간에서만 부록을 탐색한다.
    """
    m_kakron     = KAKRON_RE.search(body)
    kakron_start = m_kakron.start() if m_kakron else len(body)

    # 각론 시작점 이후에서만 부록 탐색 → 목차 노이즈 방지
    m_app     = APPENDIX_RE.search(body, kakron_start)
    app_start = m_app.start() if m_app else len(body)

    print(f"  총론 구간: 0 ~ {kakron_start:,}자")
    print(f"  각론 구간: {kakron_start:,} ~ {app_start:,}자")
    print(f"  부록 시작: {app_start:,} ({'감지' if m_app else '문서 끝'})\n")

    return body[:kakron_start], body[kakron_start:app_start]


# ── 제N장 분리 (각론 → 질병별) ───────────────────────────────────────────

def split_by_chapter(text: str) -> list[dict]:
    """제N장 헤더로 분리, 각 장의 disease_name 추출"""
    matches = list(CHAPTER_HDR_RE.finditer(text))
    if not matches:
        return [{'header': '', 'disease_name': DISEASE_VHF, 'body': text.strip()}]

    sections = []

    # 장 이전 각론 도입부
    intro = text[:matches[0].start()].strip()
    if intro and len(intro) > 20:
        sections.append({'header': '', 'disease_name': DISEASE_VHF, 'body': intro})

    for i, m in enumerate(matches):
        header = clean_header(m.group(1))

        # 질병명 추출: "제2장 에볼라바이러스병(Ebola)" → "에볼라바이러스병"
        name_m = re.match(r'제\s*\d+\s*장[\.\s　]\s*(.+)', header)
        if name_m:
            disease_name = name_m.group(1).strip()
            disease_name = re.sub(r'\s*[\(\（（].+?[\)\））]\s*', '', disease_name).strip()
        else:
            disease_name = DISEASE_VHF

        start = m.start()
        end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body  = text[start:end].strip()

        if len(body) > 20:
            sections.append({
                'header':       header,
                'disease_name': disease_name,
                'body':         body,
            })

    return sections


# ── 번호 → 가나다 세부 분리 ───────────────────────────────────────────────

def split_by_item(text: str) -> list[dict]:
    """번호(1.) → 가나다(가.) 최소 단위 분리
    가나다가 있으면 가나다가 청크, 없으면 번호 항목이 청크
    """
    num_matches = list(NUM_HDR_RE.finditer(text))

    if not num_matches:
        return [{'section_title': '', 'body': text.strip()}]

    items = []

    # 번호 이전 도입부
    intro = text[:num_matches[0].start()].strip()
    if intro and len(intro) > 20:
        items.append({'section_title': '', 'body': intro})

    for i, m in enumerate(num_matches):
        num        = int(m.group(1))
        title      = clean_header(m.group(2))
        num_header = f"{num}. {title}"
        start      = m.start()
        end        = num_matches[i + 1].start() if i + 1 < len(num_matches) else len(text)
        body       = text[start:end].strip()

        kor_matches = list(KOR_HDR_RE.finditer(body))
        if kor_matches:
            # 가나다 이전 도입부
            kor_intro = body[:kor_matches[0].start()].strip()
            if kor_intro and len(kor_intro) > 20:
                items.append({'section_title': num_header, 'body': kor_intro})

            for j, km in enumerate(kor_matches):
                kor       = km.group(1)
                kor_title = clean_header(km.group(2))
                ks        = km.start()
                ke        = kor_matches[j + 1].start() if j + 1 < len(kor_matches) else len(body)
                kor_body  = body[ks:ke].strip()
                if len(kor_body) > 20:
                    items.append({
                        'section_title': f"{num_header} {kor}. {kor_title}",
                        'body':          kor_body,
                    })
        else:
            if len(body) > 20:
                items.append({'section_title': num_header, 'body': body})

    return items


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
    body = full_text[TOC_END_POS:]

    # ① PART 구간 분리를 먼저 (clean_text 전) — Part Ⅱ/Ⅲ 마커가 살아있어야 함
    chonron_raw, kakron_raw = split_parts(body)

    # ② 각 구간을 별도로 정제 (표 제거 등)
    chonron_text = clean_text(chonron_raw)
    kakron_text  = clean_text(kakron_raw)

    chunks     = []
    global_idx = 0

    # ── 총론 처리 ─────────────────────────────────────────────
    print("[총론 파싱]")
    items = split_by_item(chonron_text)
    print(f"  → 항목 {len(items)}개")

    for item in items:
        for sub in refine_content(item['body']):
            sub = remove_nul(sub)
            if not sub.strip() or len(sub) < 20:
                continue

            chunk_id   = f"vhf_{global_idx:04d}"
            chunk_text = (
                f"PART Ⅰ 총론 {DISEASE_VHF} {item['section_title']}\n{sub}"
            )
            if is_garbage_chunk(sub):
                global_idx += 1
                continue

            chunks.append({
                'source_id':       chunk_id,
                'data_id':         DATA_ID,
                'source_category': SOURCE_CATEGORY,
                'knowledge_type':  KNOWLEDGE_TYPE,
                'disease_name':    DISEASE_VHF,
                'document_title':  DOC_TITLE,
                'chapter':         'PART Ⅰ 총론',
                'section_title':   item['section_title'],
                'content':         sub,
                'chunk_text':      remove_nul(chunk_text),
                'embed_text':      build_embed_text(DISEASE_VHF, item['section_title'], sub),
                'chunk_index':     global_idx,
                'keywords':        extract_keywords(f"총론 {item['section_title']} {sub}"),
                'source':          PDF_FILENAME,
                'embedding':       None,
            })
            global_idx += 1

    chonron_count = global_idx
    print(f"  → 총론 청크: {chonron_count}개\n")

    # ── 각론 처리 ─────────────────────────────────────────────
    print("[각론 파싱]")
    chapters = split_by_chapter(kakron_text)
    print(f"  → 제N장 {len(chapters)}개 감지")
    for c in chapters:
        print(f"    📂  {c['header'][:60]}  [disease: {c['disease_name']}]")
    print()

    for chap in chapters:
        chap_header   = chap['header']
        disease_name  = chap['disease_name']
        chapter_field = f"PART Ⅱ 각론 {chap_header}".strip()
        items         = split_by_item(chap['body'])

        for item in items:
            for sub in refine_content(item['body']):
                sub = remove_nul(sub)
                if not sub.strip() or len(sub) < 20:
                    continue

                chunk_id   = f"vhf_{global_idx:04d}"
                chunk_text = (
                    f"{chapter_field} {disease_name} {item['section_title']}\n{sub}"
                )
                if is_garbage_chunk(sub):
                    global_idx += 1
                    continue

                chunks.append({
                    'source_id':       chunk_id,
                    'data_id':         DATA_ID,
                    'source_category': SOURCE_CATEGORY,
                    'knowledge_type':  KNOWLEDGE_TYPE,
                    'disease_name':    disease_name,
                    'document_title':  DOC_TITLE,
                    'chapter':         chapter_field,
                    'section_title':   item['section_title'],
                    'content':         sub,
                    'chunk_text':      remove_nul(chunk_text),
                    'embed_text':      build_embed_text(disease_name, item['section_title'], sub),
                    'chunk_index':     global_idx,
                    'keywords':        extract_keywords(
                                           f"{disease_name} {chap_header} {item['section_title']} {sub}"
                                       ),
                    'source':          PDF_FILENAME,
                    'embedding':       None,
                })
                global_idx += 1

    kakron_count = global_idx - chonron_count
    print(f"  → 각론 청크: {kakron_count}개")

    return chunks


# ── 메인 ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='샘플 출력만, JSON 저장 없음')
    parser.add_argument('--toc',     action='store_true', help='PART/장 구조 확인 (파싱 전 검증용)')
    args = parser.parse_args()

    print(f"[바이러스성출혈열 파서] 시작")
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

    # --toc: 구조 확인만 하고 종료
    if args.toc:
        body = raw_text[TOC_END_POS:]
        body = clean_text(body)
        chonron_text, kakron_text = split_parts(body)

        print("── PART Ⅰ 총론 구조 ────────────────────────")
        items = split_by_item(chonron_text)
        print(f"  항목 {len(items)}개")
        for it in items[:5]:
            print(f"    • {it['section_title'][:60]}")
        if len(items) > 5:
            print(f"    ... 외 {len(items) - 5}개")

        print("\n── PART Ⅱ 각론 구조 ────────────────────────")
        chapters = split_by_chapter(kakron_text)
        for c in chapters:
            items = split_by_item(c['body'])
            print(f"  📂  {c['header'][:60]}  [{c['disease_name']}]  ({len(items)}개 항목)")
        return

    all_chunks = build_chunks(raw_text)
    total = len(all_chunks)
    print(f"\n[완료] 총 {total}개 청크\n")

    print("── 샘플 청크 (처음 5개) ────────────────────────")
    for c in all_chunks[:5]:
        print(f"  ID           : {c['source_id']}")
        print(f"  disease_name : {c['disease_name']}")
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

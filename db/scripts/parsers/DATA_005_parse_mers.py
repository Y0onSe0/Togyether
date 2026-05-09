"""
parsers/parse_mers.py
제1급감염병 중동호흡기증후군(MERS)·중증급성호흡기증후군(SARS) 대응지침
→ 질병별 분리 + 3단계 계층 청킹 → JSON 저장

PDF 구조 (348페이지):
  PART Ⅰ  ~ Ⅶ.   메르스(MERS)     → disease_name='중동호흡기증후군'
  PART Ⅷ  ~ ⅩⅣ.  사스(SARS)       → disease_name='중증급성호흡기증후군'
  PART ⅩⅤ ~ ⅩⅦ.  부록/서식/참고    ← 제외

각 PART 내부 구조:
  PART Ⅰ. 개요
    1. 발생 현황        ← 번호 단위
      가. 국내 현황      ← 가나다 단위 (최소 청크)
      나. 국외 현황
    2. 원인 병원체
      가. 특성
      ...

청킹 단위: 가나다 항목 (있으면) or 번호 항목 → 800자 초과 시 문장 분할

출력: parsed/chunks_mers.json

실행:
    python parsers/parse_mers.py           ← JSON 저장
    python parsers/parse_mers.py --preview ← 샘플 출력만
    python parsers/parse_mers.py --toc     ← PART 구조 확인
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
PDF_FILENAME  = "제1급감염병 중동호흡기증후군(MERS) 중증급성호흡기증후군(SARS) 대응지침.pdf"
PDF_PATH      = GUIDELINE_PDF_DIR / "완료" / PDF_FILENAME
DOC_TITLE     = "제1급감염병 중동호흡기증후군(MERS)·중증급성호흡기증후군(SARS) 대응지침"
OUTPUT_DIR       = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE      = OUTPUT_DIR / "DATA_005_chunks_mers.json"
DATA_ID          = "DATA-005"
SOURCE_CATEGORY  = "disease"
KNOWLEDGE_TYPE   = "disease_guideline"

# 목차/서문 스킵
TOC_END_POS = 15_000

DISEASE_MERS = "중동호흡기증후군"   # MERS
DISEASE_SARS = "중증급성호흡기증후군" # SARS

# ── PART 경계 정규식 ──────────────────────────────────────────────────────
# PDF 본문 실제 형식: [roman]\nPart\n[제목]  (TOC의 "PART Ⅰ. xxx"와 다름)
PART_HDR_RE = re.compile(
    r'^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ][ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]*)\s*\nPart\s*\n([^\n]+)',
    re.MULTILINE,
)

# SARS 시작: Ⅷ\nPart\n사스 개요
SARS_START_RE = re.compile(r'^Ⅷ\s*\nPart\s*\n', re.MULTILINE)

# 부록 시작: ⅩⅤ\nPart\n부록  또는 ⅩⅤ. 부록 사이드바
APPENDIX_RE = re.compile(
    r'^ⅩⅤ\s*\nPart\s*\n'
    r'|^ⅩⅤ\.\s*부록',
    re.MULTILINE,
)

# 번호 항목: "1. 발생 현황"
NUM_HDR_RE = re.compile(
    r'^(\d{1,2})\.\s+([^\n]{1,80})$',
    re.MULTILINE,
)

# 가나다 항목: "가. 국내 현황"
KOR_HDR_RE = re.compile(
    r'^([가나다라마바사아자차카타파하])\.\s+([^\n]{1,80})$',
    re.MULTILINE,
)

# ── 노이즈 제거 ───────────────────────────────────────────────────────────
SIDEBAR_PATTERNS = [
    re.compile(r'^제1급감염병\s+(?:중동호흡기증후군|중증급성호흡기증후군)[^\n]*$', re.MULTILINE),
    re.compile(r'^(?:MERS|SARS)\s*·?\s*(?:MERS|SARS)[^\n]*$',              re.MULTILINE),
    re.compile(r'^www\.kdca\.go\.kr[^\n]*$',                                re.MULTILINE),
    re.compile(r'^\s*\d+\s*$',                                              re.MULTILINE),
    re.compile(r'^\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]\s*$',                              re.MULTILINE),
    re.compile(r'^\s*[가-힣]\s*$',                                           re.MULTILINE),
    # 세로 사이드바
    re.compile(r'\n메\n르\n스\n?'), re.compile(r'\n사\n스\n?'),
    re.compile(r'^\s*메\s*$', re.MULTILINE), re.compile(r'^\s*르\s*$', re.MULTILINE),
    re.compile(r'^\s*스\s*$', re.MULTILINE), re.compile(r'^\s*사\s*$', re.MULTILINE),
    # 섹션 라벨 중복
    re.compile(r'총론(?=총론)', re.MULTILINE),
    re.compile(r'^\s*문구수정\s*$', re.MULTILINE),
    # 본문 중간에 끼어드는 PART 섹션 마커 (사이드바/페이지 잔여물)
    re.compile(r'^PART\s+[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+\.\s+[^\n]*$', re.MULTILINE),
    # PDF 본문의 로마 숫자 사이드바 (예: "Ⅷ. 사스 개요", "ⅩⅢ. 사스 실험실 검사 관리")
    re.compile(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ][ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]*\.\s+[^\n]+$', re.MULTILINE),
    # 섹션 마커의 "Part" 단독 줄
    re.compile(r'^Part\s*$', re.MULTILINE),
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

def remove_table_blocks(text: str) -> str:
    """<표 N> / <그림 N> 캡션부터 다음 구조 요소 직전까지 제거"""
    result = []
    last_end = 0
    for m in _TABLE_CAPTION_RE.finditer(text):
        result.append(text[last_end:m.start()])
        nxt = _NEXT_STRUCT_RE.search(text, m.end())
        last_end = nxt.start() if nxt else len(text)
    result.append(text[last_end:])
    return ''.join(result)


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
    예: "PART Ⅰ. 개요 ················· 3"  → "PART Ⅰ. 개요"
        "1. 발생 현황 .......... 15"          → "1. 발생 현황"
    """
    text = re.sub(r'[\s·.]{2,}\d*\s*$', '', text)
    text = re.sub(r'\s+\d+\s*$', '', text)
    return text.strip()


def clean_text(text: str) -> str:
    text = remove_table_blocks(text)
    text = _DIAGRAM_LABEL_RE.sub('', text)
    text = _TABLE_ROW_RE.sub('', text)
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


# ── MERS / SARS 구간 분리 ────────────────────────────────────────────────

def split_disease_blocks(full_text: str) -> tuple[str, str]:
    """
    TOC 이후 본문에서 MERS 구간 / SARS 구간으로 분리.
    MERS : TOC_END ~ PART Ⅷ
    SARS : PART Ⅷ  ~ PART ⅩⅤ(부록)
    """
    body = full_text[TOC_END_POS:]

    m_sars = SARS_START_RE.search(body)
    sars_start = m_sars.start() if m_sars else len(body)

    # TOC에도 PART ⅩⅤ 등이 언급될 수 있으므로 SARS 시작 이후에서만 탐색
    m_app = APPENDIX_RE.search(body, sars_start)
    app_start = m_app.start() if m_app else len(body)

    print(f"  MERS 구간: 0 ~ {sars_start:,}자")
    print(f"  SARS 구간: {sars_start:,} ~ {app_start:,}자")
    print(f"  부록 시작: {app_start:,} ({'감지' if m_app else '문서 끝'})\n")

    return body[:sars_start], body[sars_start:app_start]


# ── PART 분리 ─────────────────────────────────────────────────────────────

def split_by_part(text: str) -> list[dict]:
    """Part 헤더 기준으로 분리 (PDF 본문 형식: [roman]\\nPart\\n[제목])"""
    all_matches = list(PART_HDR_RE.finditer(text))
    # 네비게이션 마커 제외: 제목(group 2)에 한글이 없으면 skip
    matches = [m for m in all_matches if re.search(r'[가-힣]', m.group(2))]
    if not matches:
        return [{'header': '전체', 'body': text.strip()}]

    sections = []
    for i, m in enumerate(matches):
        roman  = m.group(1)
        title  = m.group(2).strip()
        header = f"{roman}. {title}"
        start  = m.start()
        end    = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body   = clean_text(text[start:end])
        if len(body) > 50:
            sections.append({'header': header, 'body': body})
    return sections


# ── 번호 → 가나다 세부 분리 ───────────────────────────────────────────────

def split_by_item(text: str) -> list[dict]:
    """
    번호 항목(1.) → 가나다(가.) 순으로 최소 단위 분리
    가나다가 있으면 가나다가 청크, 없으면 번호 항목이 청크
    """
    num_matches = list(NUM_HDR_RE.finditer(text))

    if not num_matches:
        return [{'section_title': '', 'body': text.strip()}]

    items = []

    # 번호 이전 PART 도입부
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

        # 번호 항목 내 가나다 확인
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

def build_chunks_for_disease(
    disease_text: str,
    disease_name: str,
    disease_key: str,
    chapter_label: str,
) -> list[dict]:
    """
    질병 구간 텍스트 → PART → 번호/가나다 항목 → 청크 리스트
    """
    part_sections = split_by_part(disease_text)
    print(f"  [{chapter_label}] PART {len(part_sections)}개 감지")

    chunks     = []
    global_idx = 0

    for part in part_sections:
        part_title = part['header']
        items      = split_by_item(part['body'])

        for item in items:
            section_title = item['section_title']
            content       = item['body']
            sub_chunks    = refine_content(content)

            for sub in sub_chunks:
                sub = remove_nul(sub)
                if not sub.strip() or len(sub) < 20:
                    continue

                chunk_id   = f"{disease_key}_{global_idx:04d}"
                chunk_text = (
                    f"{chapter_label} {part_title} {disease_name} {section_title}\n{sub}"
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
                    'chapter':         f"{chapter_label} {part_title}".strip(),
                    'section_title':   section_title,
                    'content':         sub,
                    'chunk_text':      remove_nul(chunk_text),
                    'embed_text':      build_embed_text(disease_name, section_title, sub),
                    'chunk_index':     global_idx,
                    'keywords':        extract_keywords(
                                           f"{chapter_label} {part_title} {section_title} {sub}"
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
    parser.add_argument('--toc',     action='store_true', help='PART 구조만 출력 (파싱 전 검증용)')
    args = parser.parse_args()

    print(f"[MERS·SARS 파서] 시작")
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

    # ① 구간 분리를 먼저 (raw 텍스트 상태에서 PART 경계 탐색)
    mers_text, sars_text = split_disease_blocks(raw_text)
    # ② 각 구간을 별도로 정제 (clean 후에는 PART 마커가 제거되므로 반드시 분리 후 정제)

    # --toc: 구조 확인만 하고 종료
    if args.toc:
        for label, text in [('MERS', mers_text), ('SARS', sars_text)]:
            parts = split_by_part(text)
            print(f"\n── {label} PART 목록 ({'총 ' + str(len(parts)) + '개'}) ────────────")
            for p in parts:
                items = split_by_item(p['body'])
                print(f"  📂  {p['header'][:70]}  ({len(items)}개 항목)")
        return

    # MERS 청킹
    print("[MERS 파싱]")
    mers_chunks = build_chunks_for_disease(mers_text, DISEASE_MERS, 'mers', 'MERS')
    print(f"  → {len(mers_chunks)}개 청크\n")

    # SARS 청킹
    print("[SARS 파싱]")
    sars_chunks = build_chunks_for_disease(sars_text, DISEASE_SARS, 'sars', 'SARS')
    print(f"  → {len(sars_chunks)}개 청크\n")

    all_chunks = mers_chunks + sars_chunks
    total = len(all_chunks)
    print(f"[완료] 총 {total}개 청크  (MERS {len(mers_chunks)} + SARS {len(sars_chunks)})\n")

    print("── 샘플 청크 (MERS 3개 / SARS 3개) ────────────────────────")
    for label, chunks in [('MERS', mers_chunks[:3]), ('SARS', sars_chunks[:3])]:
        for c in chunks:
            print(f"  [{label}] {c['source_id']}")
            print(f"    disease_name  : {c['disease_name']}")
            print(f"    chapter       : {c['chapter']}")
            print(f"    section_title : {c['section_title']}")
            print(f"    content 길이  : {len(c['content'])}자")
            print()

    if args.preview:
        print("[preview] JSON 저장 건너뜀")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    print(f"[완료] 저장: {OUTPUT_FILE}")
    print(f"  MERS {len(mers_chunks)}개 + SARS {len(sars_chunks)}개 = 총 {total}개")


if __name__ == '__main__':
    main()

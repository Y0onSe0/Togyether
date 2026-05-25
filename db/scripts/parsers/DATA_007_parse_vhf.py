#!/usr/bin/env python3
"""
parsers/DATA_007_parse_vhf.py  [docling-MD rewrite]

바이러스성출혈열 대응지침 vhf_docling.md → RAG 청크 JSON

pdfplumber 버전 대비 변경점:
  - 표를 Markdown table로 정확히 추출 (docling)
  - ## 헤더 계층 → § sentinel 방식으로 분리
  - embed_text: disease > PART > 제N장 > 항목 prefix + 핵심 내용
  - PART Ⅱ 각론 질환별 disease_name 자동 설정

구조:
  PART Ⅰ 총론 (제1~6장): 대응체계, 사례정의, 의심/확진 시 대응, 실험실 검사, 자원관리
  PART Ⅱ 각론 (제1~7장): 각론 VHF, 에볼라, 마버그, 라싸, 크리미안콩고, 남아메리카, 리프트밸리

실행:
    python parsers/DATA_007_parse_vhf.py
    python parsers/DATA_007_parse_vhf.py --preview
    python parsers/DATA_007_parse_vhf.py --toc
"""

import re
import sys
import json
import html as html_lib
import argparse
from pathlib import Path
from collections import Counter

sys.path.append(str(Path(__file__).parent.parent))
from config import CHUNK_SIZE
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 경로 ──────────────────────────────────────────────────────────────────
MD_PATH     = Path(r"C:\Users\jys72\Downloads\vhf_docling.md")
OUTPUT_DIR  = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE = OUTPUT_DIR / "DATA_007_chunks_vhf.json"

DATA_ID         = "DATA-007"
SOURCE_CATEGORY = "disease"
KNOWLEDGE_TYPE  = "disease_guideline"
DOC_TITLE       = "제1급감염병 바이러스성출혈열 대응지침"
SOURCE_FILE     = "vhf_docling.md"
DISEASE_VHF     = "바이러스성출혈열"

# PART Ⅱ 각론: 제N장 번호 → disease_name
_PART2_DISEASE: dict[int, str] = {
    1: DISEASE_VHF,        # 바이러스성출혈열 개요
    2: "에볼라바이러스병",
    3: "마버그열",
    4: "라싸열",
    5: "크리미안콩고출혈열",
    6: "남아메리카출혈열",
    7: "리프트밸리열",
}

# ── 계층 패턴 ─────────────────────────────────────────────────────────────
_CHAP_RE   = re.compile(r'^§제(\d+)장')                               # §제N장
_SEC_RE    = re.compile(r'^§(\d{1,2})\.')                              # §1.
_SUBSEC_RE = re.compile(r'^§([가나다라마바사아자차카타파하])\.')         # §가.
_SUBNUM_RE = re.compile(r'^§(\d{1,2})\)')                              # §1)
_PART2_RE  = re.compile(r'(?m)^§각\s*론\s*Part\s*[ⅡII]', re.IGNORECASE)

# 위 패턴에 걸리지 않는 나머지 § 헤더 (§한글/숫자시작 → level 3 섹션으로 처리)
_CATCH_HDR_RE = re.compile(r'^§[가-힣\d]')


def _hdr_level(line: str) -> int:
    """0=내용, 1=장, 2=번호항목, 3=가나다/번호하위/기타섹션"""
    if _CHAP_RE.match(line):                              return 1
    if _SEC_RE.match(line):                               return 2
    if _SUBSEC_RE.match(line) or _SUBNUM_RE.match(line): return 3
    if _CATCH_HDR_RE.match(line):                         return 3  # catch-all
    return 0


# ── 전처리 ────────────────────────────────────────────────────────────────

def _normalize_chap_hdr(m: re.Match) -> str:
    """## 제 N 장 . title → ## 제N장. title"""
    num   = m.group(1)
    title = (m.group(2) or '').strip()
    dot   = '.' if title else ''
    return f"## 제{num}장{dot} {title}".rstrip()


def load_docling_md(md_path: Path) -> str:
    text = md_path.read_text(encoding='utf-8')

    # 1. HTML 주석 제거
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    # 2. OCR 노이즈 제거
    text = re.sub(r'[߀-߿]+',  '', text)   # NKo 블록
    text = re.sub(r'[中号大肉]+', '', text)   # CJK OCR 잔재
    text = re.sub(r'[\x80-\x9f]', '', text)  # C1 제어문자 (\x9f 등)
    # 3. HTML 엔티티 디코딩
    text = html_lib.unescape(text)
    # 4. MD 이스케이프 제거
    text = re.sub(r'\\(.)', r'\1', text)
    # 5. TOC 점선(·) 행 제거
    text = re.sub(r'(?m)^\|[^\n]*(?:·\s*){3,}[^\n]*\|[^\n]*$', '', text)

    # 6. 본문 추출: "## Part Ⅰ" (L407) 부터
    _m = re.search(r'(?m)^##\s+Part\s+[ⅠI]\b', text)
    if _m:
        text = text[_m.start():]
    else:
        print("  [경고] '## Part Ⅰ' 본문 시작점을 찾지 못함")

    # 7. 부록(## 부  록 Part Ⅲ) 이후 제외
    _m_end = re.search(r'(?m)^##\s+부\s*록\s*Part\s+[ⅢIii]', text, re.IGNORECASE)
    if _m_end:
        text = text[:_m_end.start()].rstrip()
    else:
        print("  [경고] PART Ⅲ 부록 경계를 찾지 못함 — 전체 사용")

    # 8. 페이지 헤더 제거
    text = re.sub(r'(?m)^##\s*제1급감염병\s+바이러스성출혈열[^\n]*$', '', text)
    text = re.sub(r'(?m)^##\s*바이러스성출혈열\s+대응(?:지침)?\s*$',  '', text)

    # 9. 장 헤더 정규화: ## 제 N 장 [.] [title] → ## 제N장. title
    text = re.sub(
        r'(?m)^##\s+제\s*(\d+)\s*장\s*\.?\s*(.*?)\s*$',
        _normalize_chap_hdr,
        text,
    )

    # 10. 가나다 헤더 정규화: ## 가 . → ## 가.
    text = re.sub(r'(?m)^(##\s+)([가나다라마바사아자차카타파하])\s*\.\s*', r'\1\2. ', text)

    # 11. 분리된 번호 헤더 병합: "## 2.\n## 법적근거" → "## 2. 법적근거"
    text = re.sub(
        r'(?m)^(##\s+\d{1,2}\.)\s*\n(?:[ \t]*\n)?##\s+([가-힣A-Za-z][^\n]{0,80})\s*$',
        r'\1 \2',
        text,
    )

    # 12. 이중공백 정규화 (표 행은 보존)
    _norm: list[str] = []
    for _ln in text.split('\n'):
        if _ln.lstrip().startswith('|'):
            _norm.append(_ln)
        else:
            _norm.append(re.sub(r'[ \t]{2,}', ' ', _ln))
    text = '\n'.join(_norm)

    # 13. ## → § sentinel 변환
    text = re.sub(r'(?m)^#{1,6}\s*', '§', text)

    # 14. 노이즈 헤더 정리 (단계적으로 처리)

    # 14a. 이중 sentinel 제거: §§... → §...
    text = re.sub(r'(?m)^§§', '§', text)

    # 14b. §<...> 꺾쇠 라벨 → § 제거 (표 캡션, 현황 라벨 등)
    text = re.sub(r'(?m)^§(<)', r'\1', text)

    # 14c. §* 각주/참고 → * (§ 제거)
    text = re.sub(r'(?m)^§(\*\s*)', r'\1', text)

    # 14d. §(…) 괄호형 헤더 → § 제거해서 내용으로
    text = re.sub(r'(?m)^§(\()', r'\1', text)

    # 14e. 알려진 구조 노이즈
    text = re.sub(r'(?m)^§Part\s+[ⅠI]\s*$',                '', text)  # bare §Part Ⅰ
    text = re.sub(r'(?m)^§총\s*론\s*$',                      '', text)  # §총  론
    text = re.sub(r'(?m)^§[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫivxlIVXL]+\s*$',   '', text)  # 단독 로마자
    text = re.sub(r'(?m)^§\s*\d+\s*$',                       '', text)  # 단독 숫자
    text = re.sub(r'(?m)^§[A-Za-z]{1,3}\s*$',                '', text)  # 단독 영문

    # 14f. bullet/참고 prefix 제거
    text = re.sub(r'(?m)^§([○※◦▪·•⚫])',                   r'\1', text)
    text = re.sub(r'(?m)^§\s*(참고\.\s+)',                   r'\1', text)

    # 14g. 짧은 한글 단어 노이즈: §기관, §역할, §구분 등 (3글자 이하 단독)
    text = re.sub(r'(?m)^§([가-힣]{1,3})\s*$',               '', text)

    # 15. 빈줄 정리
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── embed_text 생성 ────────────────────────────────────────────────────────

def _clean_embed(text: str) -> str:
    """embed_text용: 특수문자 제거 + newline 평탄화"""
    text = re.sub(r'[⚫⦁∙◦○▪•∘]\s*', '', text)
    text = re.sub(r"∙'",              '', text)
    text = re.sub(r'[⇄→←↔▸▶⇓⇑⇒⇐]\s*', '', text)
    text = re.sub(r'[①②③④⑤⑥⑦⑧⑨⑩❶❷❸❹❺]\s*', '', text)
    text = re.sub(r'[ \t]{2,}',  ' ',  text)
    text = re.sub(r'\n+',        ' ',  text)   # newline 평탄화 (dense embedding 핵심)
    text = re.sub(r'\s*\|\s*',   ' ',  text)   # 표 파이프 제거
    text = re.sub(r' {2,}',      ' ',  text)
    return text.strip()


def _extract_key_content(content: str, max_chars: int = 400) -> str:
    """표/산문 혼재 시 핵심 내용 추출"""
    table_lines = [l for l in content.split('\n') if l.lstrip().startswith('|')]
    prose_lines  = [l for l in content.split('\n')
                    if not l.lstrip().startswith('|') and l.strip()]

    if len(table_lines) > len(prose_lines):
        # 표 중심 → 셀 내용 추출
        cells: list[str] = []
        for row in table_lines[:8]:
            parts = [p.strip() for p in row.split('|')
                     if p.strip() and not re.fullmatch(r'[-:]+', p.strip())]
            cells.extend(parts)
        return ' '.join(cells)[:max_chars]

    return content[:max_chars]


def build_embed_text(
    disease: str, part_label: str, chapter: str, section: str, content: str
) -> str:
    """context prefix + 핵심 내용 → embed_text (1200자 이내)"""
    ctx_parts = [p for p in [disease, part_label, chapter, section] if p]
    # 순서 유지 중복 제거
    _seen: set[str] = set()
    ctx_parts = [p for p in ctx_parts if not (p in _seen or _seen.add(p))]
    prefix = ' > '.join(ctx_parts)
    key    = _clean_embed(_extract_key_content(content))
    result = f"{prefix}: {key}" if prefix else key
    return result[:1200]


# ── 콘텐츠 분할 ───────────────────────────────────────────────────────────

_SENT_END_RE = re.compile(r'(?<=[다요함됨임])\.\s+')


def _split_content(text: str, max_size: int = CHUNK_SIZE) -> list[str]:
    """max_size 초과 시 문장 단위 분할"""
    if len(text) <= max_size:
        return [text] if text.strip() else []
    sentences = _SENT_END_RE.split(text)
    result: list[str] = []
    buf = ''
    for sent in sentences:
        if len(buf) + len(sent) + 1 <= max_size:
            buf = (buf + ' ' + sent).strip()
        else:
            if buf:
                result.append(buf)
            if len(sent) > max_size:
                for i in range(0, len(sent), max_size):
                    result.append(sent[i:i + max_size].strip())
                buf = ''
            else:
                buf = sent
    if buf:
        result.append(buf)
    return [r for r in result if r.strip()]


# ── 청크 빌더 ─────────────────────────────────────────────────────────────

def _is_garbage(content: str) -> bool:
    kor   = len(re.findall(r'[가-힣]', content))
    total = len(content.replace(' ', '').replace('\n', ''))
    if kor < 15:
        return True
    if total > 0 and kor / total < 0.25:
        return True
    return False


_STOPWORDS: set[str] = {
    '관련', '통해', '경우', '대한', '따른', '위한', '통한', '기반',
    '따라서', '그러나', '하지만', '또한', '그리고', '이후', '이전',
    '이내', '이상', '이하', '있는', '있음', '있으며', '되어', '이를',
    '위해', '모든', '각각',
    '관리', '지침', '개요', '현황', '특성', '절차', '정의', '목적',
    '대상', '범위', '내용', '방향', '원칙', '기본', '방법', '기준',
    '환자', '발생', '실시', '진행', '시행', '사용', '여부', '수행',
    '제공', '확인', '통보', '신고', '조치', '판단', '검토', '결과',
    '수준', '기간', '필요', '해당', '포함',
    '질병관리청', '감염병', '대응지침', '바이러스성출혈열',
}


def _extract_kw(text: str, max_kw: int = 10) -> list[str]:
    kor = re.findall(r'[가-힣]{2,}', text)
    eng = re.findall(r'\b[A-Z]{2,}\b', text)
    freq = Counter(w for w in kor + eng if w not in _STOPWORDS)
    return [w for w, _ in freq.most_common(max_kw)]


def _make_chunk(
    idx: int,
    content: str,
    chapter: str,
    section: str,
    disease: str,
    part_label: str,
) -> dict:
    chunk_text = ' > '.join(filter(None, [chapter, section])) + '\n' + content
    embed_text = build_embed_text(disease, part_label, chapter, section, content)
    return {
        'source_id':       f"vhf_{idx:04d}",
        'data_id':         DATA_ID,
        'source_category': SOURCE_CATEGORY,
        'knowledge_type':  KNOWLEDGE_TYPE,
        'disease_name':    disease,
        'document_title':  DOC_TITLE,
        'part':            part_label,   # sibling 병합 시 embed_text 재생성용
        'chapter':         chapter,
        'section_title':   section,
        'content':         content,
        'chunk_text':      chunk_text,
        'embed_text':      embed_text,
        'chunk_index':     idx,
        'keywords':        _extract_kw(f"{disease} {chapter} {section} {content}"),
        'source':          SOURCE_FILE,
        'embedding':       None,
    }


# ── Sibling 병합 ──────────────────────────────────────────────────────────

MIN_CHUNK_SIZE = 150   # 이 크기 미만 청크를 이전 청크에 흡수


def merge_small_siblings(chunks: list[dict], min_size: int = MIN_CHUNK_SIZE) -> list[dict]:
    """
    같은 chapter 내에서 작은 청크(< min_size)를 이전 청크에 병합.
    - 병합 조건: 이전 청크와 같은 chapter + 합산 ≤ CHUNK_SIZE
    - 이전 청크가 작거나 현재 청크가 작으면 병합 시도
    - embed_text / chunk_text / keywords 재생성
    """
    if not chunks:
        return chunks

    result: list[dict] = []

    for cur in chunks:
        if not result:
            result.append(cur)
            continue

        prev      = result[-1]
        prev_len  = len(prev['content'])
        cur_len   = len(cur['content'])
        merged_ok = (prev_len + cur_len + 2) <= CHUNK_SIZE

        can_merge = (
            prev['chapter'] == cur['chapter']   # 같은 장
            and merged_ok                        # 크기 초과 안 함
            and (prev_len < min_size or cur_len < min_size)  # 둘 중 하나가 작음
        )

        if can_merge:
            # 이전 청크에 흡수
            prev['content'] += '\n\n' + cur['content']
            # section_title: 이전 것 유지 (첫 번째 섹션 컨텍스트 보존)
            if not prev['section_title'] and cur['section_title']:
                prev['section_title'] = cur['section_title']
            # chunk_text / embed_text / keywords 재생성
            prev['chunk_text'] = (
                ' > '.join(filter(None, [prev['chapter'], prev['section_title']]))
                + '\n' + prev['content']
            )
            prev['embed_text'] = build_embed_text(
                prev['disease_name'], prev['part'],
                prev['chapter'], prev['section_title'], prev['content'],
            )
            prev['keywords'] = _extract_kw(
                f"{prev['disease_name']} {prev['chapter']} "
                f"{prev['section_title']} {prev['content']}"
            )
        else:
            result.append(cur)

    return result


# ── PART 처리 ─────────────────────────────────────────────────────────────

def process_part(text: str, part_label: str, is_part2: bool) -> list[dict]:
    """§ sentinel 텍스트 한 PART → 청크 목록 (임시 idx 0-based)"""
    chunks:   list[dict] = []
    idx       = 0
    chapter   = ''
    section   = ''
    disease   = DISEASE_VHF
    buf: list[str] = []

    def flush() -> None:
        nonlocal idx
        content = '\n'.join(buf).strip()
        buf.clear()
        if not content or _is_garbage(content):
            return
        for seg in _split_content(content):
            if seg.strip():
                chunks.append(_make_chunk(idx, seg, chapter, section, disease, part_label))
                idx += 1

    for line in text.split('\n'):
        lv = _hdr_level(line)
        if lv == 1:           # 제N장
            flush()
            chapter = line[1:].strip()   # § 제거
            m = _CHAP_RE.match(line)
            if m and is_part2:
                disease = _PART2_DISEASE.get(int(m.group(1)), DISEASE_VHF)
            section = ''
        elif lv in (2, 3):    # 번호항목 / 가나다 / 번호하위
            flush()
            section = line[1:].strip()   # § 제거
        else:
            buf.append(line)

    flush()
    return chunks


def build_chunks(text: str) -> list[dict]:
    # PART Ⅱ 경계 탐지
    m_p2 = _PART2_RE.search(text)
    if m_p2:
        part1_text = text[:m_p2.start()].strip()
        part2_text = text[m_p2.end():].strip()
    else:
        print("  [경고] 'PART Ⅱ 각론' 경계를 찾지 못했습니다 — 전체를 PART Ⅰ으로 처리")
        part1_text = text
        part2_text = ''

    print(f"  PART Ⅰ 총론: {len(part1_text):,}자")
    print(f"  PART Ⅱ 각론: {len(part2_text):,}자\n")

    chunks1 = process_part(part1_text, 'PART Ⅰ 총론', is_part2=False)
    chunks2 = process_part(part2_text, 'PART Ⅱ 각론', is_part2=True)

    print(f"  → PART Ⅰ (병합 전): {len(chunks1)}개")
    print(f"  → PART Ⅱ (병합 전): {len(chunks2)}개")

    # Sibling 병합 (< MIN_CHUNK_SIZE 청크 흡수)
    chunks1 = merge_small_siblings(chunks1)
    chunks2 = merge_small_siblings(chunks2)
    print(f"  → PART Ⅰ (병합 후): {len(chunks1)}개")
    print(f"  → PART Ⅱ (병합 후): {len(chunks2)}개")

    # 전체 인덱스 재정렬
    all_chunks = chunks1 + chunks2
    for i, c in enumerate(all_chunks):
        c['chunk_index'] = i
        c['source_id']   = f"vhf_{i:04d}"

    return all_chunks


# ── TOC 출력 (--toc) ──────────────────────────────────────────────────────

def print_toc(text: str) -> None:
    m_p2    = _PART2_RE.search(text)
    p2_start = m_p2.start() if m_p2 else len(text)

    print("── PART Ⅰ 총론 ─────────────────────────────────────────────")
    p1_lines = text[:p2_start].split('\n')
    for line in p1_lines:
        lv = _hdr_level(line)
        if lv == 1:
            print(f"  📂  {line[1:].strip()[:70]}")
        elif lv == 2:
            print(f"      {line[1:].strip()[:60]}")

    if m_p2:
        print("\n── PART Ⅱ 각론 ─────────────────────────────────────────────")
        p2_lines = text[m_p2.end():].split('\n')
        cur_chap = ''
        for line in p2_lines:
            lv = _hdr_level(line)
            if lv == 1:
                cur_chap = line[1:].strip()[:70]
                print(f"  📂  {cur_chap}")
            elif lv == 2:
                print(f"      {line[1:].strip()[:60]}")


# ── 메인 ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='샘플 출력, JSON 저장 없음')
    parser.add_argument('--toc',     action='store_true', help='PART/장 구조 확인')
    args = parser.parse_args()

    print("[바이러스성출혈열 파서 v2 (docling-MD)] 시작")
    print(f"  입력: {MD_PATH.name}\n")

    if not MD_PATH.exists():
        print(f"[오류] 파일 없음: {MD_PATH}")
        return

    print("[1] 전처리 중...")
    text = load_docling_md(MD_PATH)
    print(f"  전처리 완료: {len(text):,}자 / {text.count(chr(10)):,}줄\n")

    if args.toc:
        print_toc(text)
        return

    print("[2] 청킹 중...")
    all_chunks = build_chunks(text)
    total = len(all_chunks)
    print(f"\n[완료] 총 {total}개 청크\n")

    # disease_name별 통계
    from collections import Counter as _Counter
    cnt = _Counter(c['disease_name'] for c in all_chunks)
    print("── disease_name 분포 ────────────────────────────────────────")
    for dn in sorted(cnt):
        print(f"  {dn}: {cnt[dn]}개")

    # 샘플 출력
    print("\n── 샘플 청크 (처음 3개) ─────────────────────────────────────")
    for c in all_chunks[:3]:
        print(f"  source_id   : {c['source_id']}")
        print(f"  disease_name: {c['disease_name']}")
        print(f"  chapter     : {c['chapter']}")
        print(f"  section     : {c['section_title']}")
        print(f"  embed_text  : {c['embed_text'][:120]}...")
        print(f"  content 길이: {len(c['content'])}자")
        print()

    if args.preview:
        print("[preview] JSON 저장 건너뜀")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    print(f"[저장] {OUTPUT_FILE}  ({total}개)")


if __name__ == '__main__':
    main()

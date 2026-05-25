#!/usr/bin/env python3
"""
DATA_006_parse_tb.py  (v2 — docling 전용)
2026 국가결핵관리지침
Docling MD → 계층 구조 기반 청킹 → JSON 저장

문서 구조:
  PART Ⅰ   국가결핵관리사업
  PART Ⅱ   결핵 감시체계
  PART Ⅲ   결핵 역학조사
  PART Ⅳ   결핵의 검사
  PART Ⅴ   결핵환자 맞춤형 통합관리
  PART Ⅵ   대상별 결핵환자 관리
  PART Ⅶ   잠복결핵감염 검진 및 치료
  PART Ⅷ   인수공통결핵관리
  PART Ⅸ   결핵 검진 사업
  PART Ⅹ   결핵예방 홍보
  PART ⅩⅠ  결핵 치료제 등 수급관리
  PART ⅩⅡ  국가결핵관리사업 감시 및 평가
  PART ⅩⅢ  결핵 (각론 — 병원체·임상·진단·치료)
  PART ⅩⅣ  부 록  ← 제외

청킹 원칙:
  1. 구조 우선    : PART → 제N절 → 번호항(1. 2. 3.) → 가나다항 → 세부항(1)2)3))
  2. 응집성 유지  : \\n\\n 단락 / 표 / 목록은 원자 단위 — 절대 중간 절단 금지
  3. 목표 크기    : 600자
  4. 최대 크기    : 1200자 → 초과 시 하위 구조로 재귀 분할 (표는 예외)
  5. 병합 기준    : 200자 미만 인접 sibling → 부모 안에서 병합
  6. 마지막 수단  : 문장 경계 분할 → hard cut (표·목록 제외)

실행:
  python parsers/DATA_006_parse_tb.py            # 기본 실행
  python parsers/DATA_006_parse_tb.py --stats    # 크기 통계
  python parsers/DATA_006_parse_tb.py --toc      # 문서 구조
  python parsers/DATA_006_parse_tb.py --preview  # 샘플 출력만
  python parsers/DATA_006_parse_tb.py --md "C:/path/to/tb_docling.md"
"""

import sys
import re
import json
import html as html_lib
from collections import Counter
from pathlib import Path
import argparse

sys.path.append(str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 청킹 임계값 ─────────────────────────────────────────────────────────────
MIN_CHARS    = 200
TARGET_CHARS = 600
MAX_CHARS    = 1200

# ── 파일 설정 ────────────────────────────────────────────────────────────────
PDF_FILENAME    = "2026 국가결핵관리지침.pdf"
DOC_TITLE       = "2026 국가결핵관리지침"
DISEASE_NAME    = "결핵"
OUTPUT_DIR      = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE     = OUTPUT_DIR / "DATA_006_chunks_tb.json"
DATA_ID         = "DATA-006"
SOURCE_CATEGORY = "disease"
KNOWLEDGE_TYPE  = "disease_guideline"

# Docling MD 경로
DOCLING_MD_PATH: Path | None = Path(r"C:\Users\jys72\Downloads\tb_docling.md")

# ── 로마 숫자 문자셋 ─────────────────────────────────────────────────────────
# U+2160(Ⅰ) ~ U+216B(Ⅻ) : 단일 코드포인트 로마 숫자
ROMAN = 'ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ'

# ── 계층 구조 (§ 센티널 방식) ────────────────────────────────────────────────
#
#   load_docling_md() 가 ## → § 로 변환 + 헤더 정규화 후 아래 패턴으로 분리.
#
#   part       §PART Ⅰ  /  §PART Ⅱ 결핵 감시체계
#   jeoL       §제1절 가족접촉자 조사
#   section    §1 목적 및 기본방향  /  §2 주요 사업내용
#   item       §가. 목적  /  §나. 기본방향
#   subitem    §1) 결핵감시  /  §(가) ...

HIERARCHY: list[tuple[str, re.Pattern]] = [
    ('part', re.compile(
        rf'(?m)^§(PART\s+[{ROMAN}]+(?:\s+[{ROMAN}]+)?[^\n]{{0,35}})\s*$'
    )),
    ('jeoL', re.compile(
        r'(?m)^§(제\s*\d{1,2}\s*절[^\n]{0,35})\s*$'
    )),
    ('section', re.compile(
        r'(?m)^§(\d{1,2}\s+[가-힣A-Za-z][^\n]{0,45})\s*$'
    )),
    ('item', re.compile(
        r'(?m)^§([가-하]\.\s+[^\n]{1,70})\s*$'
    )),
    ('subitem', re.compile(
        r'(?m)^§(\d{1,2}\)\s+[^\n]{1,55}|\([가-하]\)\s+[^\n]{1,55})\s*$'
    )),
]
LEVEL_NAMES = [h[0] for h in HIERARCHY]

# ── Stopwords ────────────────────────────────────────────────────────────────
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
    '질병관리청', '감염병', '대응지침', '관리지침', '결핵',
}


# ═════════════════════════════════════════════════════════════════════════════
# 1. Docling MD 전처리
# ═════════════════════════════════════════════════════════════════════════════

def _normalize_part_header(m: re.Match) -> str:
    """
    ## PART Ⅱ .  결핵  감시체계          → ## PART Ⅱ 결핵 감시체계
    ## PART Ⅴ .  결핵환자  통합  | 제1절  → ## PART Ⅴ 결핵환자 통합
    """
    part_num = m.group(1).strip()   # e.g. "## PART Ⅱ"
    title    = m.group(2) or ''
    # | 제N절 ... 접미사 제거
    title = re.sub(r'\s*\|.*$', '', title)
    # 연속 공백 → 단일
    title = re.sub(r'\s{2,}', ' ', title).strip()
    if title:
        return f'{part_num} {title}'
    return part_num


def load_docling_md(md_path: Path) -> str:
    """
    Docling MD → § 센티널 방식 텍스트.

    처리 순서:
      1.  HTML 주석 제거 (<!-- image --> 등)
      2.  NKo 문자 / OCR 잡음 제거
      3.  HTML 엔티티 디코딩
      4.  마크다운 이스케이프 제거
      5.  목차 점선 표 행 제거 (· · · · 패턴)
      5c. 로마 숫자 정규화: Ⅺ→ⅩⅠ, Ⅻ→ⅩⅡ; 공백 제거 (Ⅹ Ⅰ→ⅩⅠ)
      5b. 본문 시작 추출: 첫 '## PART Ⅰ' 이전 목차 잔재 제거
      6a. PART 헤더 정규화 (도트형 → 공백)
      6b. 이중 공백 정규화 ([ \t] 사용 — \\s는 \\n 포함하므로 금지)
      7.  PART ⅩⅣ (부록) 직전에서 종료
      8.  실행 페이지 헤더 제거: "## 2026 국가결핵관리지침"
      9.  번호 분리 헤더 병합 ([ \t] 사용)
      10. ## → § 센티널 치환
      11. §PART 중복 제거
          a) bare §PART X: 같은 로마 숫자의 titled 버전이 있으면 제거
          b) 동일 §PART 라인: 첫 번째만 유지 (running page header 제거)
      12. 노이즈 헤더 제거
      13. 빈 줄 정리
    """
    text = md_path.read_text(encoding='utf-8')

    # 1. HTML 주석 제거
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)

    # 2. NKo 문자(U+07C0~U+07FF) / OCR 잡음 제거
    text = re.sub(r'[߀-߿]+', '', text)
    text = re.sub(r'[中号大肉]+', '', text)

    # 3. HTML 엔티티 디코딩 (&lt; → < 등)
    text = html_lib.unescape(text)

    # 4. 마크다운 이스케이프 제거
    text = re.sub(r'\\(.)', r'\1', text)

    # 5. 목차 점선 표 행 제거: | 항목 · · · · · 123 |
    text = re.sub(r'(?m)^\|[^\n]*(?:·\s*){3,}[^\n]*\|[^\n]*$', '', text)

    # 5c. 로마 숫자 정규화
    #     복합 코드포인트 분해: Ⅺ(U+216A)→ⅩⅠ, Ⅻ(U+216B)→ⅩⅡ (ROMAN 기본집합 내로 통일)
    text = text.replace('Ⅺ', 'ⅩⅠ').replace('Ⅻ', 'ⅩⅡ')
    #     ## PART 헤더에서 로마 숫자 간 공백 제거: "## PART Ⅹ Ⅰ" → "## PART ⅩⅠ"
    #     반복 적용 (2자 이상 연속 조합 처리)
    _prev = None
    while _prev != text:
        _prev = text
        text = re.sub(
            rf'(?m)^(##[ \t]+PART[ \t]+[{ROMAN}]+)[ \t]+([{ROMAN}])',
            r'\1\2',
            text,
        )

    # 5b. 본문 시작: 첫 '## PART Ⅰ' 이전 목차 잔재 제거
    #     (목차에서 ## 헤더로 렌더링된 가짜 PART 항목 제거)
    _m_start = re.search(r'(?m)^##\s+PART\s+Ⅰ', text)
    if _m_start:
        text = text[_m_start.start():]

    # 6a. PART 헤더 정규화 (도트형 → 공백형)
    #    "## PART Ⅱ .  결핵  감시체계" → "## PART Ⅱ 결핵 감시체계"
    #    주의: [ \t]* 사용 — \s 사용 시 \n 흡수 위험
    text = re.sub(
        rf'(?m)^(##\s+PART\s+[{ROMAN}]+(?:[ \t]+[{ROMAN}]+)?)[ \t]*\.[ \t]+(.*)$',
        _normalize_part_header,
        text,
    )

    # 6b. 이중 공백 정규화 ([ \t]+ 사용 — \s+는 \n 포함이므로 금지)
    #    "## PART Ⅱ 결핵  감시체계" → "## PART Ⅱ 결핵 감시체계"
    text = re.sub(
        rf'(?m)^(##\s+PART\s+[{ROMAN}]+(?:[ \t]+[{ROMAN}]+)?[ \t]+)(.+)$',
        lambda m: m.group(1).rstrip() + ' ' + re.sub(r'[ \t]{2,}', ' ', m.group(2)).strip(),
        text,
    )

    # 7. PART ⅩⅣ (부록) 직전에서 종료
    _m_end = re.search(r'(?m)^##\s+PART\s+ⅩⅣ', text)
    if _m_end:
        text = text[: _m_end.start()].rstrip()

    # 8. 실행 페이지 헤더 제거
    text = re.sub(r'(?m)^##\s*2026\s+국가결핵관리지침\s*$', '', text)

    # 9. 번호 분리 헤더 병합 ([ \t] 사용 — \s는 \n 포함)
    #    "## 1\n## 목적 및 기본방향" → "## 1 목적 및 기본방향"
    #    빈 줄 하나는 허용 ((?:[ \t]*\n)?)
    text = re.sub(
        r'(?m)^(##[ \t]*\d{1,2})[ \t]*\n(?:[ \t]*\n)?##[ \t]*([가-힣A-Za-z][^\n]{0,50})\s*$',
        r'\1 \2',
        text,
    )

    # 9.5. 전체 본문 이중공백 정규화 (표 행 제외)
    #       Docling 이 PDF 자간을 그대로 살려 이중공백을 삽입하는 현상 대응
    _lines_norm: list[str] = []
    for _ln in text.split('\n'):
        if _ln.lstrip().startswith('|'):
            _lines_norm.append(_ln)          # 표 행 — 파이프 위치 보존
        else:
            _lines_norm.append(re.sub(r'[ \t]{2,}', ' ', _ln))
    text = '\n'.join(_lines_norm)

    # 9.6. OCR 불릿 아티팩트 정규화
    #       "- w 근거:" → "- 근거:"
    text = re.sub(r'(?m)^(\s*)-\s+w\s+', r'\1- ', text)
    #       "2. ⚫ 내용" → "- 내용"  (번호+검은원 혼합 목록)
    text = re.sub(r'(?m)^\s*\d+\.\s+[⚫⦁∙▪]\s*', '- ', text)
    #       ❙ (U+2759, Heavy Vertical Bar) → | (표 구분자로 통일, is_table_block 판별 가능)
    text = text.replace('❙', '|')

    # 10. ## → § 센티널 치환
    text = re.sub(r'(?m)^#{1,6}\s*', '§', text)

    # 11. §PART 중복 제거
    #     a) bare §PART X (로마 숫자만, 제목 없음): 같은 로마 숫자의 titled 버전이
    #        문서 어딘가 존재하면 해당 bare 라인 제거
    #     b) 동일 §PART 라인: 첫 번째만 유지 → running page header 제거
    _bare_pat   = re.compile(rf'^§PART\s+([{ROMAN}]+)\s*$')
    _titled_pat = re.compile(rf'^§PART\s+([{ROMAN}]+)\s+\S')

    # titled 버전을 가진 로마 숫자 집합 수집 (공백 정규화 키)
    _titled_romans: set[str] = set()
    for _ln in text.split('\n'):
        _tm = _titled_pat.match(_ln)
        if _tm:
            _titled_romans.add(re.sub(r'\s+', '', _tm.group(1)))

    # 필터링 (순서 보존, 첫 번째 우선)
    _seen_part: set[str] = set()
    _result: list[str] = []
    for _ln in text.split('\n'):
        if re.match(rf'^§PART\s+[{ROMAN}]', _ln):
            _bm = _bare_pat.match(_ln)
            if _bm and re.sub(r'\s+', '', _bm.group(1)) in _titled_romans:
                continue  # titled 버전 있으므로 bare 제거
            if _ln in _seen_part:
                continue  # 동일 라인 중복 → running page header
            _seen_part.add(_ln)
        _result.append(_ln)
    text = '\n'.join(_result)

    # 12. 노이즈 헤더 제거
    # 단독 로마 숫자 사이드바 (§Ⅰ, §Ⅱ, §ⅩⅠ 등)
    text = re.sub(rf'(?m)^§[{ROMAN}]+\s*$', '', text)
    # 챕터 배너 (§국가결핵관리사업 등 짧은 반복 제목)
    text = re.sub(r'(?m)^§국가결핵관리사업\s*$', '', text)
    text = re.sub(r'(?m)^§일러두기\s*$', '', text)
    # 불릿 기호 강등 (§⚫... → ⚫...)
    text = re.sub(r'(?m)^§([○※◦▪·•⚫])', r'\1', text)
    # 영문자 3자 이하 단독 헤더 (OCR 잔재)
    text = re.sub(r'(?m)^§[A-Za-z]{1,3}\s*$', '', text)
    # § 다음 단독 숫자 (페이지 번호 잔재)
    text = re.sub(r'(?m)^§\s*\d+\s*$', '', text)
    # 참고. ... 헤더 강등 (본문으로 편입)
    text = re.sub(r'(?m)^§(참고\.\s+)', r'\1', text)

    # 13. 빈 줄 정리
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ═════════════════════════════════════════════════════════════════════════════
# 2. 원자 블록 판별 (표·목록은 절대 중간 절단 금지)
# ═════════════════════════════════════════════════════════════════════════════

def is_table_block(text: str) -> bool:
    lines = [l for l in text.strip().split('\n') if l.strip()]
    if len(lines) < 2:
        return False
    pipe_count = sum(1 for l in lines if '|' in l)
    return pipe_count >= 2 and pipe_count / len(lines) >= 0.5


def is_list_block(text: str) -> bool:
    lines = [l for l in text.strip().split('\n') if l.strip()]
    if len(lines) < 2:
        return False
    _pat = re.compile(r'^\s*[○◦▪·\-•∙⚫]|\s*\d+[.)]\s|\s*[가-하][.)]\s')
    cnt  = sum(1 for l in lines if _pat.match(l))
    return cnt >= 2 and cnt / len(lines) >= 0.5


def split_to_atomic_blocks(text: str) -> list[str]:
    return [b.strip() for b in re.split(r'\n{2,}', text) if b.strip()]


# ═════════════════════════════════════════════════════════════════════════════
# 3. 구조적 분할
# ═════════════════════════════════════════════════════════════════════════════

def clean_header(text: str) -> str:
    """목차 점선·페이지 번호 제거"""
    text = re.sub(r'[\s·.]{2,}\d*\s*$', '', text)
    text = re.sub(r'\s+\d+\s*$', '', text)
    return text.strip()


def split_at_level(text: str, level_idx: int) -> list[dict]:
    """
    text를 HIERARCHY[level_idx] 패턴으로 분할.
    TOC 중복 제거: 같은 헤더가 여러 번 등장하면 마지막(본문) 위치만 사용.
    """
    if level_idx >= len(HIERARCHY):
        return [{'header': '', 'body': text}]

    matches = list(HIERARCHY[level_idx][1].finditer(text))
    if not matches:
        return [{'header': '', 'body': text}]

    # TOC dedup — 공백 정규화 기준 마지막 위치만 유지
    seen: dict[str, re.Match] = {}
    for m in matches:
        key = re.sub(r'\s+', '', m.group(1))
        seen[key] = m
    matches = sorted(seen.values(), key=lambda m: m.start())

    sections: list[dict] = []
    preamble = text[: matches[0].start()].strip()
    if len(preamble) > 30:
        sections.append({'header': '', 'body': preamble})

    for i, m in enumerate(matches):
        hdr  = clean_header(m.group(1))
        body = text[
            m.end() : (matches[i + 1].start() if i + 1 < len(matches) else len(text))
        ].strip()
        if hdr or len(body) > 30:
            sections.append({'header': hdr, 'body': body})

    return sections if sections else [{'header': '', 'body': text}]


# ═════════════════════════════════════════════════════════════════════════════
# 4. Fallback 분할 (표·목록 절단 절대 금지)
# ═════════════════════════════════════════════════════════════════════════════

_SENT_END     = re.compile(r'(?<=[다요함됨임])\.\s+')
_BULLET_SPLIT = re.compile(r'\n(?=\s*[○◦▪·\-•∙⚫]|\s*\d+[.)]\s|\s*[가-하][.)]\s)')


def _group_parts(parts: list[str], sep: str) -> list[str]:
    groups: list[str] = []
    cur: list[str]    = []
    cur_len = 0
    for part in parts:
        plen = len(part)
        if cur_len + plen > MAX_CHARS and cur:
            groups.append(sep.join(cur))
            cur, cur_len = [part], plen
        else:
            cur.append(part)
            cur_len += plen
    if cur:
        groups.append(sep.join(cur))
    return [g for g in groups if g.strip()]


def _split_by_text_boundaries(text: str) -> list[str]:
    bullet_parts = _BULLET_SPLIT.split(text)
    if len(bullet_parts) > 1:
        result = _group_parts(bullet_parts, '\n')
        if any(len(g) <= MAX_CHARS for g in result):
            return result

    sent_parts = _SENT_END.split(text)
    if len(sent_parts) > 1:
        result = _group_parts(sent_parts, ' ')
        if any(len(g) <= MAX_CHARS for g in result):
            return result

    return [
        text[i : i + MAX_CHARS].strip()
        for i in range(0, len(text), MAX_CHARS)
        if text[i : i + MAX_CHARS].strip()
    ]


def _make_raw(header: str, content: str, breadcrumbs: list[str]) -> dict:
    # 본문에 남은 § 센티널 제거 (split_at_level이 캡처 못 한 헤더)
    content = re.sub(r'(?m)^§', '', content)
    return {
        '_header':      header,
        '_breadcrumbs': list(breadcrumbs),
        'content':      content.strip(),
    }


def split_by_atomic_blocks(
    blocks: list[str],
    header: str,
    breadcrumbs: list[str],
) -> list[dict]:
    groups: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0

    for block in blocks:
        blen    = len(block)
        is_atom = is_table_block(block) or is_list_block(block)

        if blen > MAX_CHARS:
            if cur:
                groups.append(cur[:])
                cur, cur_len = [], 0
            if is_atom:
                groups.append([block])
            else:
                for seg in _split_by_text_boundaries(block):
                    groups.append([seg])
        else:
            if cur_len + blen > MAX_CHARS and cur:
                groups.append(cur[:])
                cur, cur_len = [], 0
            cur.append(block)
            cur_len += blen

    if cur:
        groups.append(cur)

    total = len(groups)
    return [
        _make_raw(
            f'{header} (계속 {i + 1}/{total})' if total > 1 else header,
            '\n\n'.join(g),
            breadcrumbs,
        )
        for i, g in enumerate(groups)
    ]


# ═════════════════════════════════════════════════════════════════════════════
# 5. 재귀 청킹 + Sibling 병합
# ═════════════════════════════════════════════════════════════════════════════

def merge_short_siblings(
    chunks: list[dict],
    parent_header: str,
    parent_crumbs: list[str],
) -> list[dict]:
    if not chunks:
        return []

    result: list[dict] = []
    pending: list[dict] = []
    pending_len = 0

    def _do_flush(extra: list[dict] | None = None) -> None:
        nonlocal pending_len
        group = pending + (extra or [])
        if not group:
            return
        if len(group) == 1:
            result.append(group[0])
        else:
            titles   = [c['_header'] for c in group if c['_header']]
            mheader  = ' · '.join(titles) if titles else parent_header
            mcontent = '\n\n'.join(c['content'] for c in group)
            mcrumbs  = [*parent_crumbs, parent_header] if parent_header else list(parent_crumbs)
            result.append(_make_raw(mheader, mcontent, mcrumbs))
        pending.clear()
        pending_len = 0

    for chunk in chunks:
        clen = len(chunk['content'])
        if clen >= MIN_CHARS:
            if pending:
                if pending_len + clen <= MAX_CHARS:
                    _do_flush(extra=[chunk])
                else:
                    _do_flush()
                    result.append(chunk)
            else:
                result.append(chunk)
        else:
            if pending_len + clen > MAX_CHARS:
                _do_flush()
            pending.append(chunk)
            pending_len += clen

    _do_flush()
    return result


def chunk_section(
    body: str,
    header: str,
    breadcrumbs: list[str],
    split_level: int,
) -> list[dict]:
    body = body.strip()
    if not body:
        return []

    if len(body) <= MAX_CHARS:
        return [_make_raw(header, body, breadcrumbs)]

    for lvl in range(split_level, len(HIERARCHY)):
        secs = split_at_level(body, lvl)
        has_struct = len(secs) > 1 or (secs and secs[0]['header'])
        if not has_struct:
            continue

        child_crumbs = [*breadcrumbs, header] if header else list(breadcrumbs)
        children: list[dict] = []
        for sec in secs:
            children.extend(
                chunk_section(
                    body        = sec['body'],
                    header      = sec['header'],
                    breadcrumbs = child_crumbs,
                    split_level = lvl + 1,
                )
            )
        return merge_short_siblings(children, header, breadcrumbs)

    return split_by_atomic_blocks(
        split_to_atomic_blocks(body), header, breadcrumbs
    )


# ═════════════════════════════════════════════════════════════════════════════
# 6. 계층 레벨 분류 (chapter vs section_title 분리)
# ═════════════════════════════════════════════════════════════════════════════

_LEVEL_DETECT: list[tuple[int, re.Pattern]] = [
    (0, re.compile(rf'^PART\s+[{ROMAN}]')),           # PART Ⅰ ...
    (1, re.compile(r'^제\s*\d+\s*절')),               # 제1절 ...
    (2, re.compile(r'^\d{1,2}\s+[가-힣A-Za-z]')),    # 1 목적 ...
    (3, re.compile(r'^[가-하]\.')),                    # 가. 목적
    (4, re.compile(r'^\d+\)|\([가-하]\)')),            # 1) / (가)
]
# PART 레벨만 chapter 필드 — 나머지는 section_title
_CHAPTER_MAX_LEVEL = 0


def _crumb_level(text: str) -> int:
    t = text.strip().split('·')[0].strip()
    for lvl, pat in _LEVEL_DETECT:
        if pat.match(t):
            return lvl
    return len(HIERARCHY)


def _split_meta(crumbs: list[str], hdr: str) -> tuple[str, str]:
    chapter_parts: list[str] = []
    section_parts: list[str] = []

    for c in crumbs:
        if _crumb_level(c) <= _CHAPTER_MAX_LEVEL:
            chapter_parts.append(c)
        else:
            section_parts.append(c)

    if hdr:
        if _crumb_level(hdr) <= _CHAPTER_MAX_LEVEL:
            chapter_parts.append(hdr)
        else:
            section_parts.append(hdr)

    # chapter_parts 중복 제거 (순서 유지)
    # — merge_short_siblings 가 parent_header를 mcrumbs+mheader 양쪽에 넣을 때 발생
    _seen_ch: set[str] = set()
    chapter_parts = [p for p in chapter_parts if not (p in _seen_ch or _seen_ch.add(p))]
    chapter   = ' '.join(chapter_parts)
    # section_parts가 비어있을 때: hdr가 섹션 레벨이면 사용, 아니면 '' 반환
    # (chapter crumbs[-1]을 폴백으로 쓰면 chapter==section_title 중복 발생)
    sec_title = ' > '.join(section_parts) or (
        hdr if hdr and _crumb_level(hdr) > _CHAPTER_MAX_LEVEL else ''
    )
    return chapter, sec_title


def _clean_chapter(ch: str) -> str:
    """chapter 필드 정리: 불필요한 공백 정규화"""
    ch = re.sub(r'\s{2,}', ' ', ch)
    return ch.strip()


def _clean_section_title(sec: str) -> str:
    """section_title 필드 정리: 계속 마커·잔재 § 제거·이중공백 정규화"""
    sec = re.sub(r'\s*>\s*\(계속\s*\d+/\d+\)', '', sec)
    sec = re.sub(r'\s*>\s*$', '', sec)
    sec = re.sub(r'\s*\(계속\s*\d+/\d+\)', '', sec)
    sec = sec.replace('§', '')
    sec = re.sub(r'[ \t]{2,}', ' ', sec)   # Docling 이중공백 정규화
    return sec.strip()


# ═════════════════════════════════════════════════════════════════════════════
# 7. 키워드 / 임베딩 / 가비지 필터
# ═════════════════════════════════════════════════════════════════════════════

# ── TB 도메인 엔티티 패턴 ──────────────────────────────────────────────────────
_TB_DRUG_RE = re.compile(
    r'이소니아지드|리팜핀|에탐부톨|피라진아미드|스트렙토마이신|카나마이신'
    r'|아미카신|카프레오마이신|레보플록사신|목시플록사신|오플록사신|가티플록사신'
    r'|베다퀼린|리네졸리드|델라마니드|클로파지민|사이클로세린|테리지돈'
    r'|프로티오나미드|에티오나미드|리파부틴|리파펜틴'
    r'|isoniazid|rifampicin|ethambutol|pyrazinamide|bedaquiline|linezolid|delamanid'
    r'|항결핵제|항결핵약제|약제내성'
)
_TB_TEST_RE = re.compile(
    r'객담검사|도말검사|배양검사|핵산증폭검사|TB-PCR|Xpert\s*MTB'
    r'|항산균|IGRA|TST|투베르쿨린|인터페론감마'
    r'|흉부X선|흉부CT|흉부전산화|약제감수성검사'
    r'|통상감수성검사|신속감수성검사'
)
_TB_TYPE_RE = re.compile(
    r'잠복결핵감염|다제내성결핵|광범위약제내성|리팜핀단독내성|이소니아지드단독내성'
    r'|MDR-TB|XDR-TB|RR-TB|Hr-TB|pre-XDR|NTM|비결핵항산균'
    r'|폐결핵|폐외결핵|속립성결핵|군내결핵|소아결핵'
)
_TB_MEDICAL_RE = re.compile(
    r'[가-힣]{2,4}(?:결핵|감염|환자|접촉자|역학조사|검진|치료|관리|신고|격리|접종'
    r'|배양|검사|진단|분리|동정|복약|순응|사례)'
)
_ORG_RE = re.compile(
    r'질병관리청|보건소|권역질병대응센터|결핵정책과|결핵조사과'
    r'|보건환경연구원|국립마산병원|국립목포병원'
    r'|PPM|민간공공협력|결핵관리전담'
)


def extract_keywords(text: str, max_kw: int = 10) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()

    def _add(word: str) -> None:
        w = word.strip()
        if w and len(w) >= 2 and w not in seen and w not in STOPWORDS:
            keywords.append(w)
            seen.add(w)

    for pat in [_TB_DRUG_RE, _TB_TEST_RE, _TB_TYPE_RE, _TB_MEDICAL_RE, _ORG_RE]:
        for m in pat.finditer(text):
            _add(m.group())

    for m in re.finditer(r'\b[A-Z]{2,}\b', text):
        _add(m.group())

    if len(keywords) < max_kw:
        kor_words = re.findall(r'[가-힣]{2,}', text)
        freq = Counter(w for w in kor_words if w not in STOPWORDS and w not in seen)
        for word, _ in freq.most_common(max_kw * 2):
            if len(keywords) >= max_kw:
                break
            _add(word)

    return keywords[:max_kw]


# ── 표 평문화 (embed_text 전용) ──────────────────────────────────────────────
_SEP_ROW = re.compile(r'^\|[\s\|\-:]+\|$')

def _table_to_plain(content: str, max_rows: int = 5) -> str:
    """
    마크다운 표 → 임베딩용 평문 변환
      | 구분 | 값 |  →  구분: 값 / ...
    구분자 행(|---|---|)과 빈 셀은 스킵.
    """
    parsed: list[list[str]] = []
    for line in content.split('\n'):
        line = line.strip()
        if not line.startswith('|'):
            continue
        if _SEP_ROW.match(line):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        cells = [c for c in cells if c]
        if cells:
            parsed.append(cells)

    if not parsed:
        return ''

    headers   = parsed[0]
    data_rows = parsed[1:] if len(parsed) > 1 else []

    parts: list[str] = []
    if not data_rows:
        parts.append(' / '.join(headers))
    else:
        for row in data_rows[:max_rows]:
            row_parts: list[str] = []
            for h, v in zip(headers, row):
                if v:
                    row_parts.append(f'{h}: {v}' if (h and h != v) else v)
            if row_parts:
                parts.append(' / '.join(row_parts))

    # 표 아래 산문도 포함
    non_table = []
    for line in content.split('\n'):
        line = line.strip()
        if line and not line.startswith('|') and not _SEP_ROW.match(line):
            non_table.append(line)
    if non_table:
        parts.append(' '.join(non_table[:3]))

    return '\n'.join(parts)


def _clean_embed(text: str) -> str:
    """
    embed_text 전용 노이즈 제거 (강화).
    dense embedding은 연속 의미 흐름이 중요 → 줄바꿈을 공백으로 평탄화.
    """
    # 1. OCR 불릿 아티팩트: "- w 내용" → "- 내용"
    text = re.sub(r'-\s+w\s+', '- ', text)
    # 2. 번호+특수불릿: "2. ⚫ 내용" → "- 내용"
    text = re.sub(r'(?m)^\s*\d+\.\s+[⚫⦁∙▪]\s*', '- ', text)
    # 3. 특수불릿 문자 제거 (⚫⦁∙◦○▪• 등)
    text = re.sub(r'[⚫⦁∙◦○▪•⚫]\s*', '', text)
    # 4. 화살표·순서도 기호 제거
    text = re.sub(r'[⇄→←↔▸▶⇓⇑⇒⇐]\s*', '', text)
    # 5. 원문자 (①②③…) 제거
    text = re.sub(r'[①②③④⑤⑥⑦⑧⑨⑩❶❷❸❹❺]\s*', '', text)
    # 6. ∙' 조합 잔재
    text = re.sub(r"∙'", '', text)
    # 7. ❙ (Heavy Vertical Bar) 제거
    text = text.replace('❙', ' ')
    # 8. 공백 정규화
    text = re.sub(r'[ \t]{2,}', ' ', text)
    # 9. 줄바꿈 → 공백 (dense embedding 의미 연속성 유지)
    text = re.sub(r'\n+', ' ', text)
    # 10. 표 파이프 제거 (is_table_block 판별 실패 시 content[:MAX] 폴백에서 잔류하는 경우)
    #     평탄화 후에도 남은 '| 구분 | 값 |' 형태 → 단어만 남김
    text = re.sub(r'\s*\|\s*', ' ', text)
    # 11. 최종 이중공백 정리 (치환 후 생긴 경우)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def _extract_key_content(content: str) -> str:
    """
    embed_text용 핵심 내용 추출 (≤ 800자).

    유형별 전략:
      표       → _table_to_plain() 으로 평문화
      목록     → 도입 문장(있으면) + 첫 5개 항목
      일반 텍스트 → 전체 ≤ MAX 이면 전체 반환; 첫 단락 ≥ 50자면 앞 2문장; 아니면 전체 앞부분
    """
    MAX = 800
    lines = [l for l in content.strip().split('\n') if l.strip()]
    paragraphs = [b.strip() for b in re.split(r'\n{2,}', content.strip()) if b.strip()]
    first_para = paragraphs[0] if paragraphs else content

    # 표 → 평문 변환
    if is_table_block(content) or is_table_block(first_para):
        target = content if is_table_block(content) else first_para
        plain  = _table_to_plain(target)
        return plain[:MAX] if plain else content[:MAX]

    # 목록 → 도입 + 항목
    if is_list_block(content):
        _lpat = re.compile(r'^\s*[○◦▪·\-•∙⚫]|\s*\d+[.)]\s|\s*[가-하][.)]\s')
        intro_lines = [l for l in lines if not _lpat.match(l)]
        list_lines  = [l for l in lines if _lpat.match(l)]
        intro = ' '.join(intro_lines[:2]) if intro_lines else ''
        items = '\n'.join(list_lines[:5])
        return ((intro + '\n' + items).strip() if intro else items)[:MAX]

    # 전체가 MAX 이내면 그대로 반환 (첫 단락이 짧은 레이블이어도 전체 보존)
    if len(content.strip()) <= MAX:
        return content.strip()

    if paragraphs:
        first = paragraphs[0]
        if len(first) >= 50:
            # 의미 있는 단락 → 앞 2문장
            sents = _SENT_END.split(first)
            return (' '.join(sents[:2])).rstrip()[:MAX]
        # 첫 단락이 짧은 레이블 → 전체 앞부분 사용
        return content[:MAX]

    return content[:MAX]


def build_embed_text(disease: str, chapter: str, section: str, content: str) -> str:
    """
    Dense 검색용 임베딩 텍스트.
    - text-embedding-3-small: 8191 토큰 지원 → 1200자까지 활용
    - 접두사(disease > chapter > section)는 context anchor 역할
    - 표는 _table_to_plain()으로 평문화, 나머지 노이즈는 _clean_embed()로 제거
    """
    # section_title의 이중공백 정규화 (Docling 아티팩트가 prefix까지 오염되는 것 방지)
    section_clean = re.sub(r'[ \t]{2,}', ' ', section).strip() if section else section
    ctx_parts = list(dict.fromkeys(p for p in [disease, chapter, section_clean] if p))
    prefix    = ' > '.join(ctx_parts)
    key       = _clean_embed(_extract_key_content(content))
    result    = f"{prefix}: {key}" if prefix else key
    return result[:1200]


def is_garbage_chunk(content: str) -> bool:
    kor   = len(re.findall(r'[가-힣]', content))
    if kor < 30:
        return True
    total = len(content.replace(' ', '').replace('\n', ''))
    return total > 0 and kor / total < 0.4


# ═════════════════════════════════════════════════════════════════════════════
# 8. 메인 빌더
# ═════════════════════════════════════════════════════════════════════════════

def remove_nul(text: str) -> str:
    return text.replace('\x00', '')


def build_chunks(full_text: str) -> list[dict]:
    # ── level 0: PART 분리 ──────────────────────────────────────────────────
    part_secs = split_at_level(full_text, 0)
    print(f"  [파트] {len(part_secs)}개 감지")
    for s in part_secs:
        hdr = s['header'] or '(헤더 없음)'
        print(f"    ▸ [{hdr[:40]}]  {len(s['body']):,}자")
    print()

    raw_all: list[dict] = []
    for part in part_secs:
        pheader = part['header'] or '전체'
        body    = part['body']
        print(f"  처리 중: [{pheader[:40]}]  {len(body):,}자  ", end='')
        before = len(raw_all)
        raw_all.extend(
            chunk_section(body=body, header=pheader, breadcrumbs=[], split_level=1)
        )
        print(f"→ {len(raw_all) - before}개 raw 청크")

    # ── 최종 포맷 변환 ──────────────────────────────────────────────────────
    final: list[dict] = []
    for idx, raw in enumerate(raw_all):
        content = remove_nul(raw['content'])
        if not content.strip() or len(content) < 20:
            continue
        if is_garbage_chunk(content):
            continue

        hdr    = raw['_header']
        crumbs = raw['_breadcrumbs']

        chapter_raw, sec_title_raw = _split_meta(crumbs, hdr)
        chapter   = _clean_chapter(chapter_raw)
        sec_title = _clean_section_title(sec_title_raw)

        chunk_txt = ' > '.join(filter(None, [chapter, sec_title])) + '\n' + content

        final.append({
            'source_id':       f'tb_{idx:04d}',
            'data_id':         DATA_ID,
            'source_category': SOURCE_CATEGORY,
            'knowledge_type':  KNOWLEDGE_TYPE,
            'disease_name':    DISEASE_NAME,
            'document_title':  DOC_TITLE,
            'chapter':         chapter,
            'section_title':   sec_title,
            'content':         content,
            'chunk_text':      remove_nul(chunk_txt),
            'embed_text':      build_embed_text(DISEASE_NAME, chapter, sec_title, content),
            'chunk_index':     idx,
            'char_count':      len(content),
            'keywords':        extract_keywords(f'{chapter} {sec_title} {content}'),
            'source':          PDF_FILENAME,
            'embedding':       None,
        })

    return final


# ═════════════════════════════════════════════════════════════════════════════
# 9. CLI
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(description='결핵 관리지침 파서 v2 (docling)')
    ap.add_argument('--out',     type=Path, default=OUTPUT_FILE, help='출력 JSON 경로')
    ap.add_argument('--preview', action='store_true', help='샘플 출력만, JSON 저장 안 함')
    ap.add_argument('--stats',   action='store_true', help='크기 통계 출력')
    ap.add_argument('--toc',     action='store_true', help='문서 구조만 출력')
    ap.add_argument('--md',      type=Path, default=None,
                    help='Docling MD 파일 경로 (없으면 DOCLING_MD_PATH 사용)')
    args = ap.parse_args()

    print('[결핵 관리지침 파서 v2 (docling)]')
    print(f'  임계값: MIN={MIN_CHARS}자  TARGET={TARGET_CHARS}자  MAX={MAX_CHARS}자\n')

    md_path = args.md or DOCLING_MD_PATH
    if not md_path or not Path(md_path).exists():
        print('[오류] Docling MD 파일을 찾을 수 없습니다.')
        print(f'  지정 경로: {md_path}')
        print('  --md 옵션으로 경로를 지정하거나 스크립트 내 DOCLING_MD_PATH를 설정하세요.')
        return

    print(f'[1단계] Docling MD 전처리 중... ({Path(md_path).name})')
    text = load_docling_md(Path(md_path))
    print(f'  전처리 후: {len(text):,}자\n')

    # ── --toc 모드 ────────────────────────────────────────────────────────
    if args.toc:
        print('── 문서 구조 ─────────────────────────────────────────────')
        parts = split_at_level(text, 0)
        for p in parts:
            print(f'\n  ▸ [{p["header"] or "(없음)"}]  {len(p["body"]):,}자')
            for lvl in range(1, len(HIERARCHY)):
                secs = [s for s in split_at_level(p['body'], lvl) if s['header']]
                if secs:
                    print(f'    level {lvl} ({LEVEL_NAMES[lvl]}): {len(secs)}개')
                    for s in secs[:6]:
                        print(f'      · {s["header"][:55]}  ({len(s["body"]):,}자)')
                    if len(secs) > 6:
                        print(f'      ... 외 {len(secs) - 6}개')
                    break
        return

    # ── 청킹 실행 ─────────────────────────────────────────────────────────
    print('[2단계] 계층 청킹 중...')
    chunks = build_chunks(text)
    n      = len(chunks)
    print(f'\n[완료] {n}개 청크\n')

    if n > 0:
        sizes  = [c['char_count'] for c in chunks]
        srt    = sorted(sizes)
        short  = sum(1 for s in sizes if s < MIN_CHARS)
        over   = sum(1 for s in sizes if s > MAX_CHARS)
        in_rng = n - short - over
        print('── 크기 통계 ─────────────────────────────────────────────')
        print(f'  평균 {sum(sizes) // n}자  중앙값 {srt[n // 2]}자  최소 {srt[0]}자  최대 {srt[-1]}자')
        print(f'  {MIN_CHARS}자 미만: {short}개')
        print(f'  {MAX_CHARS}자 초과 (표·목록 허용): {over}개')
        print(f'  {MIN_CHARS}~{MAX_CHARS}자 (정상 범위): {in_rng}개  ({in_rng / n * 100:.0f}%)\n')

    print('── 샘플 청크 (처음 5개) ──────────────────────────────────')
    for c in chunks[:5]:
        path = ' > '.join(filter(None, [c['chapter'], c['section_title']]))
        print(f"  [{c['source_id']}] {path}")
        print(f"  {c['char_count']}자")
        print(f"  {c['content'][:120]}{'...' if len(c['content']) > 120 else ''}\n")

    if args.preview:
        print('[preview] JSON 저장 건너뜀')
        return

    args.out.parent.mkdir(exist_ok=True)
    args.out.write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'[저장] {args.out}  ({n} 청크)')


if __name__ == '__main__':
    main()

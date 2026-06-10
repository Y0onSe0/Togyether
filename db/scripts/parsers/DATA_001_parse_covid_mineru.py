#!/usr/bin/env python3
"""
DATA_001_parse_covid_mineru.py  (v2 — 계층적 구조 우선 청킹)
MinerU 마크다운 → JSON 청크 저장

청킹 원칙
  1. 구조 우선    : 총론/각론 → 장 → 절(1.2.3.) → 항(가.나.다.) → 세부항(1)2)3))
  2. 응집성 유지  : \\n\\n 단락 / 표 / 목록은 원자 단위 — 절대 중간 절단 금지
  3. 목표 크기    : 600자
  4. 최대 크기    : 1200자  →  초과 시 하위 구조로 재귀 분할
  5. 병합 기준    : 200자 미만 인접 sibling → 부모 안에서 병합
  6. 마지막 수단  : 문장 경계 분할  →  hard cut (표·목록은 hard cut 제외)

실행
  python parsers/DATA_001_parse_covid_mineru.py --md 파일.md
  python parsers/DATA_001_parse_covid_mineru.py --md 파일.md --preview
  python parsers/DATA_001_parse_covid_mineru.py --md 파일.md --stats
  python parsers/DATA_001_parse_covid_mineru.py --md 파일.md --toc
"""

import sys
import re
import json
from collections import Counter
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 청킹 임계값 ──────────────────────────────────────────────────────────────
MIN_CHARS    = 200    # 미만 → sibling 병합
TARGET_CHARS = 600    # 목표 (참고용)
MAX_CHARS    = 1200   # 초과 → 하위 구조 분할

# ── 파일 설정 ─────────────────────────────────────────────────────────────────
DEFAULT_MD_PATH = (
    Path(__file__).parent.parent / "raw" / "DATA_001_covid.md"
)

DOC_TITLE       = "2025년도 코로나19 관리지침"
DISEASE_NAME    = "코로나19"
OUTPUT_DIR      = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE     = OUTPUT_DIR / "DATA_001_chunks_covid.json"
DATA_ID         = "DATA-001"
SOURCE_CATEGORY = "disease"
KNOWLEDGE_TYPE  = "disease_guideline"
PDF_FILENAME    = "++2025년도 코로나19 관리지침_최종-전자용.pdf"
TARGET_PARTS    = {'총론', '각론'}

# ── 계층 구조 정의 ────────────────────────────────────────────────────────────
#
#   level 0  총론 / 각론 / 부록           — 단독 줄
#   level 1  제X장 제목                   — 없는 문서도 있음 → skip 후 level 2 시도
#   level 2  1. 개요 / 2. 수행체계        — 짧은 제목만 (끝 앵커 $로 본문 목록과 구별)
#   level 3  가. 급성호흡기... / 나. ...  — 항
#   level 4  1) ... / (가) ...            — 세부항
#
# 핵심 설계 포인트
#   - 각 레벨의 end anchor($) + 길이 제한 → 본문 번호·불릿 목록과 구별
#   - 같은 헤더가 TOC+본문에 반복 → 마지막 위치만 사용해 중복 제거

HIERARCHY: list[tuple[str, re.Pattern]] = [
    ('part', re.compile(
        # § 접두사 필수 — MinerU # 헤더였던 줄만 매치 (본문 번호목록 오인식 방지)
        r'(?m)^§(총\s*론|각\s*론|부\s*록)\s*$'
    )),
    ('chapter', re.compile(
        r'(?m)^§(제\s*\d{1,2}\s*장[^\n]{0,30})$'
    )),
    ('section', re.compile(
        # § 접두사로 # 헤더 줄만 인식 → 초록박스 내 "1. 연령 60세 이상" 같은
        # 본문 번호목록이 section 헤딩으로 오인식되는 문제 해결
        # ⚠️  [ \t] 사용 (not \s) — \s는 \n 포함이라 멀티라인 오매치 발생
        r'(?m)^§(\d{1,2}\.\s+[가-힣A-Za-z][가-힣A-Za-z0-9 \t\xb7\-]{0,33})$'
    )),
    ('item', re.compile(
        # 영문 괄호(ARI, Acute Respiratory Infection 등) 포함 시 42자 초과 → 90자로 완화
        r'(?m)^§([가-하]\.\s+[^\n]{1,90})$'
    )),
    ('subitem', re.compile(
        r'(?m)^§(\d{1,2}\)\s+[^\n]{1,50}|\([가-하]\)\s+[^\n]{1,50})$'
    )),
]

LEVEL_NAMES = [h[0] for h in HIERARCHY]

# ── 노이즈 패턴 ───────────────────────────────────────────────────────────────
SIDEBAR_PATTERNS = [
    # § 접두사 포함 버전 — load_mineru_md 에서 # 헤더를 §로 변환 후 적용
    re.compile(r'(?m)^§?코로나19[^\n]{0,15}$'),
    re.compile(r'(?m)^§?COVID[-\s]?19[^\n]{0,15}$'),
    re.compile(r'(?m)^§?www\.kdca\.go\.kr[^\n]*$'),
    re.compile(r'(?m)^\s*\d+\s*$'),
    re.compile(r'(?m)^\s*[가-힣]\s*$'),
    re.compile(r'(?m)^§?\s*문구수정\s*$'),
    re.compile(r'(?m)^§?[IⅠⅡⅢ]+\.\s*(총론|각론|부록)\s*$'),
    re.compile(r'(?m)^§?[IⅠⅡⅢ]+\s*$'),
]

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
    '질병관리청', '감염병', '대응지침', '관리지침', '코로나',
}


# ═════════════════════════════════════════════════════════════════════════════
# 1. MinerU 전처리
# ═════════════════════════════════════════════════════════════════════════════

def html_table_to_text(html_table: str) -> str:
    """HTML 테이블 → 마크다운 파이프 표 변환 (_table_to_plain 호환)"""
    html = re.sub(r'<(td|th)[^>]*>', r'<\1>', html_table)
    rows = re.split(r'</?tr>', html)
    lines = []
    for row in rows:
        cells = re.findall(r'<t[dh]>(.*?)</t[dh]>', row, re.DOTALL)
        if not cells:
            continue
        clean = [
            re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', c)).strip()
            for c in cells
        ]
        if any(clean):
            # 마크다운 파이프 형식으로 출력 → _table_to_plain() 과 호환
            lines.append('| ' + ' | '.join(clean) + ' |')
    return '\n'.join(lines)


def load_mineru_md(md_path: Path) -> str:
    """MinerU .md 로드 및 전처리"""
    print(f"  로드: {md_path.name}")
    text = md_path.read_text(encoding='utf-8', errors='replace')
    print(f"  원본: {len(text):,}자")

    # 1. HTML 테이블 → 파이프 평문
    text = re.sub(
        r'<table>.*?</table>',
        lambda m: html_table_to_text(m.group()),
        text, flags=re.DOTALL,
    )
    # 2. 이미지 링크 제거
    text = re.sub(r'!\[.*?\]\([^)]*\)', '', text)
    # 3. 마크다운 이스케이프 제거  ← # 처리 전에 수행해야 역슬래시가 남지 않음
    text = re.sub(r'\\(.)', r'\1', text)
    # 4. OCR 오류 보정  ← # 처리 전에 수행 (§ 이후엔 줄 시작 패턴 달라짐)
    text = text.replace('충론', '총론')
    # 4b. OCR 보정: "가.제목" → "가. 제목" / "1)목적" → "1) 목적" (# 헤더 줄 포함)
    #    (?m)^#+\s* 이후에 나오는 가.X / 1)X 패턴도 보정
    text = re.sub(r'(?m)^(#+\s*[가-하]\.)([^\s\n])', r'\1 \2', text)
    text = re.sub(r'(?m)^(#+\s*\d{1,2}\))([^\s\n])', r'\1 \2', text)
    text = re.sub(r'(?m)^([가-하]\.)([^\s\n])', r'\1 \2', text)
    text = re.sub(r'(?m)^(\d{1,2}\))([^\s\n])', r'\1 \2', text)
    # 5. 마크다운 # 헤더 → §  sentinel 변환
    #    이 줄만 구조 헤딩(HIERARCHY)으로 인식 → 초록박스 내 번호목록 오인식 방지
    text = re.sub(r'^#+\s*', '§', text, flags=re.MULTILINE)
    # 6. MinerU 중복 헤더 제거: "§제목\n제목" → "§제목"
    #    예: "§6. 감염취약시설 관리\n6. 감염취약시설 관리" → "§6. 감염취약시설 관리"
    text = re.sub(r'(?m)^§(.+)\n\1$', r'§\1', text)
    # 7. 연속 빈 줄 정리
    text = re.sub(r'\n{3,}', '\n\n', text)

    print(f"  전처리: {len(text):,}자")
    return text.strip()


def clean_sidebar(text: str) -> str:
    for pat in SIDEBAR_PATTERNS:
        text = pat.sub('', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def remove_nul(text: str) -> str:
    return text.replace('\x00', '')


def clean_header(text: str) -> str:
    """목차 점선·페이지 번호 제거"""
    text = re.sub(r'[\s·.]{2,}\d*\s*$', '', text)
    text = re.sub(r'\s+\d+\s*$', '', text)
    return text.strip()


# ═════════════════════════════════════════════════════════════════════════════
# 2. 원자 블록 판별
#    표·목록·단락은 절대 중간에서 자르지 않음
# ═════════════════════════════════════════════════════════════════════════════

def is_table_block(text: str) -> bool:
    """파이프 구분 테이블 블록 감지"""
    lines = [l for l in text.strip().split('\n') if l.strip()]
    if len(lines) < 2:
        return False
    pipe_count = sum(1 for l in lines if '|' in l)
    return pipe_count >= 2 and pipe_count / len(lines) >= 0.5


def is_list_block(text: str) -> bool:
    """불릿/절차 목록 블록 감지"""
    lines = [l for l in text.strip().split('\n') if l.strip()]
    if len(lines) < 2:
        return False
    _pat = re.compile(r'^\s*[○◦▪·\-•]|\s*\d+[.)]\s|\s*[가-하][.)]\s')
    cnt  = sum(1 for l in lines if _pat.match(l))
    return cnt >= 2 and cnt / len(lines) >= 0.5


def split_to_atomic_blocks(text: str) -> list[str]:
    """\\n\\n 경계로 원자 블록 분리 (각 블록은 내부 절단 금지)"""
    return [b.strip() for b in re.split(r'\n{2,}', text) if b.strip()]


# ═════════════════════════════════════════════════════════════════════════════
# 3. 구조적 분할
# ═════════════════════════════════════════════════════════════════════════════

def split_at_level(text: str, level_idx: int) -> list[dict]:
    """
    text를 HIERARCHY[level_idx] 패턴으로 분할.

    TOC 중복 제거: 같은 헤더(공백 정규화 기준)가 여러 번 나오면
    마지막 위치만 사용 → 목차 항목보다 실제 본문 위치를 선택.

    반환: [{'header': str, 'body': str}, ...]
    구조 없으면: [{'header': '', 'body': text}]
    """
    if level_idx >= len(HIERARCHY):
        return [{'header': '', 'body': text}]

    matches = list(HIERARCHY[level_idx][1].finditer(text))
    if not matches:
        return [{'header': '', 'body': text}]

    # 중복 제거 — 같은 헤더는 마지막 등장 위치만 유지
    seen: dict[str, re.Match] = {}
    for m in matches:
        key = re.sub(r'\s+', '', m.group(1))
        seen[key] = m
    matches = sorted(seen.values(), key=lambda m: m.start())

    sections: list[dict] = []

    # 첫 매치 이전 서문
    preamble = text[: matches[0].start()].strip()
    if len(preamble) > 30:
        sections.append({'header': '', 'body': preamble})

    for i, m in enumerate(matches):
        hdr  = clean_header(m.group(1))
        body = text[
            m.end() : (matches[i + 1].start() if i + 1 < len(matches) else len(text))
        ].strip()
        # 헤더가 있으면 body가 짧아도 유지 (바로 아래 1) 2) 가 나오는 경우)
        # 헤더 없는 서문(preamble)만 30자 미만이면 skip
        if hdr or len(body) > 30:
            sections.append({'header': hdr, 'body': body})

    return sections if sections else [{'header': '', 'body': text}]


# ═════════════════════════════════════════════════════════════════════════════
# 4. Fallback 분할 (표·목록 절단 절대 금지)
# ═════════════════════════════════════════════════════════════════════════════

_SENT_END    = re.compile(r'(?<=[다요함됨임])\.\s+')
_BULLET_SPLIT = re.compile(r'\n(?=\s*[○◦▪·\-•]|\s*\d+[.)]\s|\s*[가-하][.)]\s)')


def _group_parts(parts: list[str], sep: str) -> list[str]:
    """파트 리스트를 MAX_CHARS 기준으로 그룹핑."""
    groups: list[str] = []
    cur: list[str] = []
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
    """
    일반 텍스트 분할 우선순위 (표·목록은 이 함수로 오지 않음):
      1. 불릿/번호 목록 경계  — 목록 항목 사이만 자름 (항목 내부 절단 금지)
      2. 문장 경계            — 한국어 종결 어미 기준
      3. Hard cut             — 최최종 수단
    """
    # 1. 불릿/번호 경계
    bullet_parts = _BULLET_SPLIT.split(text)
    if len(bullet_parts) > 1:
        result = _group_parts(bullet_parts, '\n')
        if any(len(g) <= MAX_CHARS for g in result):   # 분할 효과 있으면 사용
            return result

    # 2. 문장 경계
    sent_parts = _SENT_END.split(text)
    if len(sent_parts) > 1:
        result = _group_parts(sent_parts, ' ')
        if any(len(g) <= MAX_CHARS for g in result):
            return result

    # 3. Hard cut
    return [
        text[i : i + MAX_CHARS].strip()
        for i in range(0, len(text), MAX_CHARS)
        if text[i : i + MAX_CHARS].strip()
    ]


def _make_raw(header: str, content: str, breadcrumbs: list[str]) -> dict:
    """내부 임시 청크 dict (최종 포맷 변환 전)"""
    # § 센티널 제거: 박스 제목(§■ ...), 하위 소제목(§- ...)은 content로 편입 후 정리
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
    """
    원자 블록 리스트를 MAX_CHARS 기준으로 그룹핑.

    규칙:
      - 표·목록 블록  → MAX_CHARS 초과해도 단독 청크로 허용 (절단 금지)
      - 일반 텍스트   → 문장 경계 분할
      - 여러 블록이 MAX_CHARS 이하라면 하나의 청크로 합치기
    """
    groups: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0

    for block in blocks:
        blen    = len(block)
        is_atom = is_table_block(block) or is_list_block(block)

        if blen > MAX_CHARS:
            # 현재 버퍼 flush
            if cur:
                groups.append(cur[:])
                cur, cur_len = [], 0

            if is_atom:
                # 표·목록: 크기 초과 허용, 절단 금지
                groups.append([block])
            else:
                # 일반 텍스트: 불릿 → 문장 → hard cut 순
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
    """
    MIN_CHARS 미만 인접 청크를 MAX_CHARS 범위 안에서 병합.
    병합 헤더: 'A · B · C' 형태.

    전략:
      1. 짧은 청크들은 pending 버퍼에 누적
      2. 긴 청크(≥ MIN_CHARS)가 나오면:
         - pending + 긴청크 합이 MAX_CHARS 이하 → 모두 함께 병합 (앞 짧은것들 흡수)
         - 합이 MAX_CHARS 초과 → pending 먼저 flush, 긴청크 단독 출력
      3. 루프 종료 후 남은 pending → flush
      이 방식으로 단독 짧은 청크가 다음 sibling에 자연스럽게 흡수됨
    """
    if not chunks:
        return []

    result: list[dict] = []
    pending: list[dict] = []
    pending_len = 0

    def _do_flush(extra: list[dict] | None = None) -> None:
        """pending [+ extra] 를 하나로 합쳐 result에 추가"""
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
                # 긴 청크 등장 — pending과 함께 흡수 가능한지 확인
                if pending_len + clen <= MAX_CHARS:
                    _do_flush(extra=[chunk])   # pending + 긴청크 합병
                else:
                    _do_flush()               # pending 먼저 flush
                    result.append(chunk)      # 긴청크 단독
            else:
                result.append(chunk)
        else:
            # 짧은 청크 → pending 누적
            if pending_len + clen > MAX_CHARS:
                _do_flush()
            pending.append(chunk)
            pending_len += clen

    _do_flush()  # 남은 pending 처리
    return result


def chunk_section(
    body: str,
    header: str,
    breadcrumbs: list[str],
    split_level: int,
) -> list[dict]:
    """
    재귀 청킹 핵심 함수.

    전략:
      1. body <= MAX_CHARS          → 단일 청크 (구조 유지)
      2. body > MAX_CHARS           → split_level 부터 순서대로 구조 분할 시도
         2-a. 구조 발견             → 재귀 + sibling 병합
         2-b. 모든 레벨 구조 없음  → 원자 블록(\\n\\n) 경계에서 분할
                                      (표·목록은 절단 금지, 일반 텍스트는 문장 경계)
    """
    body = body.strip()
    if not body:
        return []

    # ── 적정 크기 → 그대로 단일 청크 ────────────────────────────────────────
    if len(body) <= MAX_CHARS:
        return [_make_raw(header, body, breadcrumbs)]

    # ── MAX_CHARS 초과 → 하위 구조로 분할 시도 ───────────────────────────────
    # split_level부터 순서대로 시도 (레벨 건너뛰기 자동 처리)
    for lvl in range(split_level, len(HIERARCHY)):
        secs = split_at_level(body, lvl)
        has_struct = len(secs) > 1 or (secs and secs[0]['header'])
        if not has_struct:
            continue  # 이 레벨엔 구조 없음 → 다음 레벨 시도

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

    # ── 구조 분할 실패 → 원자 블록 경계에서만 분할 ───────────────────────────
    return split_by_atomic_blocks(
        split_to_atomic_blocks(body), header, breadcrumbs
    )


# ═════════════════════════════════════════════════════════════════════════════
# 6. 계층 레벨 분류 (chapter vs section_title 분리용)
# ═════════════════════════════════════════════════════════════════════════════

# 텍스트 패턴으로 HIERARCHY 레벨 추정
_LEVEL_DETECT: list[tuple[int, re.Pattern]] = [
    (0, re.compile(r'^(총론|각론|부록)$')),
    (1, re.compile(r'^제\s*\d')),
    (2, re.compile(r'^\d{1,2}\.')),
    (3, re.compile(r'^[가-하]\.')),
    (4, re.compile(r'^\d+\)|\([가-하]\)')),
]

# level 0~2 → chapter 필드 / level 3~ → section_title 필드
_CHAPTER_MAX_LEVEL = 2


def _crumb_level(text: str) -> int:
    """
    breadcrumb 텍스트에서 HIERARCHY 레벨 추정.
    병합 헤더('가. A · 나. B') 는 첫 항목으로 판단.
    """
    t = text.strip().split('·')[0].strip()
    for lvl, pat in _LEVEL_DETECT:
        if pat.match(t):
            return lvl
    return len(HIERARCHY)  # 미분류 → section_title 쪽으로


def _split_meta(crumbs: list[str], hdr: str) -> tuple[str, str]:
    """
    breadcrumbs + header를 chapter / section_title 로 분리.

    반환: (chapter, section_title)
      chapter      : level 0~2 (총론/각론, 제X장, 1.2.3.)
      section_title: level 3~  (가.나.다., 1)2)3)) — ' > ' 로 연결
    """
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

    chapter   = ' '.join(chapter_parts)
    sec_title = ' > '.join(section_parts) or hdr or (crumbs[-1] if crumbs else '')
    return chapter, sec_title


# ═════════════════════════════════════════════════════════════════════════════
# 7. 키워드 / 임베딩 / 가비지 필터
# ═════════════════════════════════════════════════════════════════════════════

# ── 도메인 엔티티 패턴 (우선순위 순) ──────────────────────────────────────────
# 약품·치료제명
_DRUG_RE = re.compile(
    r'렘데시비르|팍스로비드|몰누피라비르|라게브리오|베클루리주?|니르마트렐비르|리토나비르'
    r'|덱사메타손|바리시티닙|토실리주맙|코르티코스테로이드'
)
# 검사·진단법
_TEST_RE = re.compile(
    r'RT-?PCR|신속항원검사|항원검사|항체검사|유전자(?:검사|증폭)|중합효소연쇄반응'
)
# 변이 바이러스 (영문 코드 + 한국어명)
_VARIANT_RE = re.compile(
    r'\b(?:XBB|JN|KP|BA|BQ|EG|HV|HK|NB|LP)\.\d+(?:\.\d+)*\b'
    r'|오미크론|델타|알파|베타|감마|람다'
)
# 의료 명사구 (2~4자 어근 + 의미 있는 suffix)
_MEDICAL_SUFFIX_RE = re.compile(
    r'[가-힣]{2,4}(?:감염증?|바이러스|증후군|환자|격리|접종|검사|조사|신고'
    r'|예방|치료|진단|관리|발생|현황|체계|방법|기준|지침|대응|분류)'
)
# 기관·조직명
_ORG_RE = re.compile(
    r'질병관리청|보건소|보건환경연구원|감염병관리과|역학조사팀'
    r'|(?:시도|시군구|중앙|지방)(?:보건|청|정부|방역)?'
)


def extract_keywords(text: str, max_kw: int = 10) -> list[str]:
    """
    도메인 엔티티 우선 + 고빈도 명사 보완.

    우선순위:
      1. 약품·치료제명  2. 검사법명  3. 변이명
      4. 의료 명사구    5. 기관명    6. 영문 약어
      7. 고빈도 한글 명사 (stopword 제외, 보완용)
    """
    keywords: list[str] = []
    seen: set[str] = set()

    def _add(word: str) -> None:
        w = word.strip()
        if w and len(w) >= 2 and w not in seen and w not in STOPWORDS:
            keywords.append(w)
            seen.add(w)

    for pat in [_DRUG_RE, _TEST_RE, _VARIANT_RE, _MEDICAL_SUFFIX_RE, _ORG_RE]:
        for m in pat.finditer(text):
            _add(m.group())

    for m in re.finditer(r'\b[A-Z]{2,}\b', text):
        _add(m.group())

    # 도메인 엔티티가 부족하면 고빈도 명사로 보완
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

_EMBED_NOISE = re.compile(
    r'∙\'|◦\s*|[⇄→←↔▸▶•]\s*|^\s*[①②③④⑤]\s*|\s{2,}'
)


def _table_to_plain(content: str, max_rows: int = 5) -> str:
    """마크다운 표 → embed_text용 평문 (헤더: 값 / 형태)"""
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
            row_parts = [
                f'{h}: {v}' if (h and h != v) else v
                for h, v in zip(headers, row) if v
            ]
            if row_parts:
                parts.append(' / '.join(row_parts))

    # 표 아래 산문도 포함
    non_table = [
        l.strip() for l in content.split('\n')
        if l.strip() and not l.strip().startswith('|') and not _SEP_ROW.match(l.strip())
    ]
    if non_table:
        parts.append(' '.join(non_table[:3]))

    return '\n'.join(parts)


def _clean_embed(text: str) -> str:
    """embed_text 노이즈 제거 (불릿기호·화살표·연속공백)"""
    text = _EMBED_NOISE.sub(
        lambda m: ' ' if m.group()[-1:] == ' ' or m.group() == m.group() and m.group().strip() == '' else '',
        text,
    )
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()


def _extract_key_content(content: str) -> str:
    """
    embed_text용 핵심 내용 추출 (≤ 800자).

    유형별 전략:
      표       → _table_to_plain() 으로 평문화 (파이프 제거)
      목록     → 도입 문장(있으면) + 첫 5개 항목
      일반 텍스트 → 첫 완성 단락; 길면 앞 2문장
    """
    MAX = 800
    lines = [l for l in content.strip().split('\n') if l.strip()]
    paragraphs = [b.strip() for b in re.split(r'\n{2,}', content.strip()) if b.strip()]
    first_para = paragraphs[0] if paragraphs else content

    # 전체 or 첫 단락이 표 → 평문 변환
    if is_table_block(content) or is_table_block(first_para):
        target = content if is_table_block(content) else first_para
        plain  = _table_to_plain(target)
        return plain[:MAX] if plain else content[:MAX]

    if is_list_block(content):
        _lpat = re.compile(r'^\s*[○◦▪·\-•]|\s*\d+[.)]\s|\s*[가-하][.)]\s')
        intro_lines = [l for l in lines if not _lpat.match(l)]
        list_lines  = [l for l in lines if _lpat.match(l)]
        intro = ' '.join(intro_lines[:2]) if intro_lines else ''
        items = '\n'.join(list_lines[:5])
        return ((intro + '\n' + items).strip() if intro else items)[:MAX]

    # 전체 내용이 MAX 이내면 그대로 반환 (첫 단락이 짧은 레이블이어도 전체 보존)
    if len(content.strip()) <= MAX:
        return content.strip()

    if paragraphs:
        first = paragraphs[0]
        if len(first) >= 50:
            # 의미있는 단락 → 앞 2문장
            sents = _SENT_END.split(first)
            return (' '.join(sents[:2])).rstrip()[:MAX]
        # 첫 단락이 너무 짧은 레이블(예: "가. 목적") → 전체 앞부분 사용
        return content[:MAX]

    return content[:MAX]


def build_embed_text(disease: str, chapter: str, section: str, content: str) -> str:
    """
    Dense 검색용 embed_text.
      - text-embedding-3-small: 8191 토큰 지원 → 1200자까지 활용
      - 표는 _table_to_plain()으로 평문화 (파이프 제거)
      - 노이즈 기호 _clean_embed()로 제거
    """
    ctx_parts = list(dict.fromkeys(p for p in [disease, chapter, section] if p))
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
# 7. 메인 빌더
# ═════════════════════════════════════════════════════════════════════════════

def build_chunks(full_text: str) -> list[dict]:
    """전체 텍스트 → 최종 청크 리스트"""

    # ── level 0: 총론 / 각론 / 부록 분리 ─────────────────────────────────────
    part_secs = split_at_level(full_text, 0)
    print(f"  [파트] {len(part_secs)}개 감지")
    for s in part_secs:
        key  = re.sub(r'\s+', '', s['header'])
        flag = '✅' if key in TARGET_PARTS else ('전체' if not key else '⏭️  스킵')
        print(f"    {flag}  [{s['header'] or '(헤더 없음)'}]  {len(s['body']):,}자")
    print()

    raw_all: list[dict] = []

    # 총론/각론만 처리. 없으면(파트 구조가 없는 문서) 전체 처리
    named = [s for s in part_secs if re.sub(r'\s+', '', s['header']) in TARGET_PARTS]
    process_secs = named if named else part_secs

    for part in process_secs:
        key = re.sub(r'\s+', '', part['header'])
        if key not in TARGET_PARTS and part['header']:
            print(f"  ⏭️  스킵: [{part['header']}]")
            continue

        pheader = key or '전체'
        print(f"  처리 중: [{pheader}]  {len(part['body']):,}자  ", end='')

        chunks_before = len(raw_all)
        raw_all.extend(
            chunk_section(
                body        = part['body'],
                header      = pheader,
                breadcrumbs = [],
                split_level = 1,   # 파트 내부는 level 1(장)부터 시도
            )
        )
        print(f"→ {len(raw_all) - chunks_before}개 raw 청크")

    # ── 최종 포맷 변환 ────────────────────────────────────────────────────────
    final: list[dict] = []
    for idx, raw in enumerate(raw_all):
        content = remove_nul(raw['content'])
        if not content.strip() or len(content) < 20:
            continue
        if is_garbage_chunk(content):
            continue

        hdr    = raw['_header']
        crumbs = raw['_breadcrumbs']

        # level 0~2 (총론, 절) → chapter / level 3~ (항, 세부항) → section_title
        chapter, sec_title = _split_meta(crumbs, hdr)

        # chunk_text: 검색용 전문
        chunk_txt = ' > '.join(filter(None, [chapter, sec_title])) + '\n' + content

        final.append({
            'source_id':       f'covid_{idx:04d}',
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
# 8. CLI
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(description='MinerU MD → 계층적 청킹 v2')
    ap.add_argument('--md',      type=Path, default=DEFAULT_MD_PATH, help='.md 파일 경로')
    ap.add_argument('--out',     type=Path, default=OUTPUT_FILE,     help='출력 JSON 경로')
    ap.add_argument('--preview', action='store_true', help='샘플 출력만, JSON 저장 안 함')
    ap.add_argument('--stats',   action='store_true', help='크기 통계 출력')
    ap.add_argument('--toc',     action='store_true', help='문서 구조만 출력')
    args = ap.parse_args()

    print(f'[코로나19 파서 v2]')
    print(f'  입력: {args.md}')
    print(f'  임계값: MIN={MIN_CHARS}자  TARGET={TARGET_CHARS}자  MAX={MAX_CHARS}자\n')

    if not args.md.exists():
        print(f'[오류] 파일 없음: {args.md}')
        print('  --md 옵션으로 .md 파일 경로를 지정하세요')
        return

    text = load_mineru_md(args.md)
    text = clean_sidebar(text)
    print(f'  노이즈 정제 후: {len(text):,}자\n')

    # ── --toc: 구조 확인 모드 ─────────────────────────────────────────────────
    if args.toc:
        print('── 문서 구조 ─────────────────────────────────────────────')
        parts = split_at_level(text, 0)
        for p in parts:
            key  = re.sub(r'\s+', '', p['header'])
            flag = '✅' if key in TARGET_PARTS else '⏭️'
            print(f'\n  {flag} [{p["header"] or "(없음)"}]  {len(p["body"]):,}자')
            for lvl in range(1, len(HIERARCHY)):
                secs = [s for s in split_at_level(p['body'], lvl) if s['header']]
                if secs:
                    print(f'    level {lvl} ({LEVEL_NAMES[lvl]}): {len(secs)}개')
                    for s in secs[:6]:
                        print(f'      ▸ {s["header"][:55]}  ({len(s["body"]):,}자)')
                    if len(secs) > 6:
                        print(f'      ... 외 {len(secs) - 6}개')
                    break
        return

    # ── 청킹 실행 ─────────────────────────────────────────────────────────────
    chunks = build_chunks(text)
    n      = len(chunks)
    print(f'\n[완료] {n}개 청크\n')

    # 크기 통계 (--stats 또는 기본 출력)
    if n > 0:
        sizes  = [c['char_count'] for c in chunks]
        srt    = sorted(sizes)
        short  = sum(1 for s in sizes if s < MIN_CHARS)
        over   = sum(1 for s in sizes if s > MAX_CHARS)
        in_rng = n - short - over
        print('── 크기 통계 ─────────────────────────────────────────────')
        print(f'  평균 {sum(sizes) // n}자  중앙값 {srt[n // 2]}자  최소 {srt[0]}자  최대 {srt[-1]}자')
        print(f'  {MIN_CHARS}자 미만 (병합 대상): {short}개')
        print(f'  {MAX_CHARS}자 초과 (표·목록 허용): {over}개')
        print(f'  {MIN_CHARS}~{MAX_CHARS}자 (정상 범위): {in_rng}개  ({in_rng / n * 100:.0f}%)\n')

    # 샘플 출력
    print('── 샘플 청크 (처음 5개) ──────────────────────────────────')
    for c in chunks[:5]:
        path = ' > '.join(filter(None, [c['chapter'], c['section_title']]))
        print(f"  [{c['source_id']}] {path}")
        print(f"  {c['char_count']}자  |  {c['content'][:120]}{'...' if len(c['content']) > 120 else ''}\n")

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

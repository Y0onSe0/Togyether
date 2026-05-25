#!/usr/bin/env python3
"""
DATA_003_parse_dupest.py  (v3 — docling 전용)
제1급감염병 두창·페스트·탄저·보툴리눔독소증·야토병 대응지침
Docling MD → 계층 구조 기반 청킹 → JSON 저장

PDF 구조:
  총론 Part Ⅰ
    제1장. 대응체계
    제2장. 사례정의
    제3장. 감염병 의심 시 대응
    제4장. 감염병 확진 시 대응
    제5장. 실험실 검사
    제6장. 자원관리
  각론 Part Ⅱ
    제1장. 두창  → 1.개요 / 2.발생현황 / 3.역학적특성 / 4.임상적특징 / 5.실험실검사 / 6.치료 / 7.예방
    제2장. 페스트 (동일 구조)
    제3장. 탄저
    제4장. 보툴리눔독소증
    제5장. 야토병
  (부록·서식 — 제외)

청킹 원칙:
  1. 구조 우선    : 부(총론/각론) → 장 → 절(1.2.3.) → 항(가.나.다.) → 세부항
  2. 응집성 유지  : \\n\\n 단락 / 표 / 목록은 원자 단위 — 절대 중간 절단 금지
  3. 목표 크기    : 600자
  4. 최대 크기    : 1200자 → 초과 시 하위 구조로 재귀 분할 (표는 예외)
  5. 병합 기준    : 200자 미만 인접 sibling → 부모 안에서 병합
  6. 마지막 수단  : 문장 경계 분할 → hard cut (표·목록 제외)

실행:
  python parsers/DATA_003_parse_dupest.py            # 기본 실행
  python parsers/DATA_003_parse_dupest.py --stats    # 크기 통계
  python parsers/DATA_003_parse_dupest.py --toc      # 문서 구조
  python parsers/DATA_003_parse_dupest.py --md "C:/path/to/dupest_docling.md"
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
PDF_FILENAME = "제1급감염병 두창 페스트 탄저 보툴리눔독소증 야토병 대응지침.pdf"

DOC_TITLE     = "제1급감염병 두창·페스트·탄저·보툴리눔독소증·야토병 대응지침"
DISEASE_GROUP = "두창·페스트·탄저·보툴리눔독소증·야토병"
OUTPUT_DIR    = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE   = OUTPUT_DIR / "DATA_003_chunks_dupest.json"
DATA_ID         = "DATA-003"
SOURCE_CATEGORY = "disease"
KNOWLEDGE_TYPE  = "disease_guideline"

# Docling MD 경로 — 코랩에서 생성한 파일 경로 설정
DOCLING_MD_PATH: Path | None = Path(r"C:\Users\jys72\Downloads\dupest_docling.md")

# 처리 대상 파트 키워드
TARGET_PART_KEYWORDS = {'총론', '각론'}

# 각론 챕터에서 disease 이름 추출
_DISEASE_IN_CHAPTER = re.compile(
    r'제\s*\d+\s*장\s*[.·]\s*(두창|페스트|탄저|보툴리눔독소증|야토병)'
)

# ── 계층 구조 (§ 센티널 방식) ────────────────────────────────────────────────
#
#   load_docling_md() 가 ## → § 로 변환 + 헤더 정규화 후 아래 패턴으로 분리.
#
#   part    §총론 Part Ⅰ  /  §각론 Part Ⅱ
#   chapter §제1장. 대응 체계  /  §제1장. 두창 Smallpox
#   section §1. 목적  /  §2. 발생현황
#   item    §가. 질병관리청 감염병별 대책반 구성 및 운영
#   subitem §1) ...  /  §(가) ...

HIERARCHY: list[tuple[str, re.Pattern]] = [
    ('part', re.compile(
        r'(?m)^§((?:총론|각론)\s*(?:Part\s*[ⅠⅡⅢⅣ])?[^\n]{0,20})\s*$'
    )),
    ('chapter', re.compile(
        r'(?m)^§(제\s*\d+\s*장[.·]\s*[가-힣A-Za-z][^\n]{0,55}?)\s*$'
    )),
    ('section', re.compile(
        r'(?m)^§(\d{1,2}\.\s+[가-힣A-Za-z][가-힣A-Za-z0-9 \t·\-]{0,40})\s*$'
    )),
    ('item', re.compile(
        r'(?m)^§([가-하]\.\s+[^\n]{1,60})\s*$'
    )),
    ('subitem', re.compile(
        r'(?m)^§(\d{1,2}\)\s+[^\n]{1,50}|\([가-하]\)\s+[^\n]{1,50})\s*$'
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
    '질병관리청', '감염병', '대응지침', '관리지침',
}


# ═════════════════════════════════════════════════════════════════════════════
# 1. Docling MD 전처리
# ═════════════════════════════════════════════════════════════════════════════

def load_docling_md(md_path: Path) -> str:
    """
    Docling MD → § 센티널 방식 텍스트.

    처리 순서:
      1. 이미지 주석 / NKo 문자 / 중국어 OCR 잡음 제거
      2. HTML 엔티티 디코딩
      3. 실제 본문 범위 추출  : "## 총  론 Part Ⅰ" ~ Part Ⅲ 부록 직전
      4. 목차 점선 표 행 제거 (·····)
      5. 챕터 헤더 정규화    : "## 제 1 장 . 두창" → "## 제1장. 두창"
      6. 번호 분리 헤더 병합  : "## 2.\\n## 발생현황" → "## 2. 발생현황"
      7. ## → § 센티널 치환
      8. 노이즈 헤더 제거    : < 표명 > / [ ] / Ⅰ~Ⅴ 사이드바 / ○ ※ 불릿 등
      9. 빈 줄 정리
    """
    text = md_path.read_text(encoding='utf-8')

    # 1-a. HTML 주석 제거 (<!-- image --> 등)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    # 1-b. NKo 문자 제거 (U+07C0–U+07FF : ߶ ߳ 등)
    text = re.sub(r'[߀-߿]+', '', text)
    # 1-c. 중국어 OCR 잡음
    text = re.sub(r'[中号大肉]+', '', text)

    # 2. HTML 엔티티 디코딩
    text = html_lib.unescape(text)

    # 3. 본문 범위 추출
    #    시작: "## 총  론 Part Ⅰ"
    m_start = re.search(r'(?m)^##\s*총\s+론\s+Part\s+Ⅰ', text)
    if m_start:
        text = text[m_start.start():]
    #    끝: Part Ⅲ 부록 직전
    m_end = re.search(r'Part\s*\n+Ⅲ\s*\n+부\s+록', text)
    if m_end:
        text = text[:m_end.start()].rstrip()

    # 4. 목차 점선 표 행 제거: | 1. 개요 ·····  | ··· 170 |
    text = re.sub(r'(?m)^\|[^\n]*(?:·\s*){5,}[^\n]*\|[^\n]*$', '', text)

    # 5. 챕터 헤더 정규화
    #    "## 제 1 장 . 두창 Smallpox" → "## 제1장. 두창 Smallpox"
    text = re.sub(r'(?m)^(##\s+)제\s+(\d+)\s+장\s*[.·]\s*', r'\1제\2장. ', text)
    text = re.sub(r'(?m)^(##\s+)제\s+(\d+)\s+부\s*[.·]\s*', r'\1제\2부. ', text)
    #    "총  론" / "각  론" 이중 공백 정규화
    text = re.sub(r'(?m)^(##[^\n]*)총\s+론', r'\1총론', text)
    text = re.sub(r'(?m)^(##[^\n]*)각\s+론', r'\1각론', text)

    # 6. 번호 분리 헤더 병합: "## 2.\n## 발생현황" → "## 2. 발생현황"
    text = re.sub(
        r'(?m)^(##\s*\d+)\.\s*\n##\s*([가-힣A-Za-z][^\n]{0,50})\s*$',
        r'\1. \2', text
    )

    # 7. ## → § 센티널 치환
    text = re.sub(r'(?m)^#{1,6}\s*', '§', text)

    # 8. 노이즈 헤더 제거
    text = re.sub(r'(?m)^§<[^>]{0,100}>\s*$', '', text)          # < 표 제목 >
    text = re.sub(r'(?m)^§\[[^\]]{0,100}\]\s*$', '', text)        # [ 표 제목 ]
    text = re.sub(r'(?m)^§([○※◦▪·•])', r'\1', text)              # ○ ※ 불릿 → 강등
    text = re.sub(r'(?m)^§[ⅠⅡⅢⅣⅤ][^\n]{0,15}\s*$', '', text)   # 로마자 사이드바
    text = re.sub(r'(?m)^§제1급감염병\s+두창[^\n]*\s*$', '', text) # 반복 페이지 헤더
    text = re.sub(r'(?m)^§[A-Za-z가-힣]{1,3}\s*$', '', text)      # 3자 이하 단독 헤더

    # 9. 빈 줄 정리
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
    _pat = re.compile(r'^\s*[○◦▪·\-•∙]|\s*\d+[.)]\s|\s*[가-하][.)]\s')
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

    # TOC dedup — 마지막 위치만 유지
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
_BULLET_SPLIT = re.compile(r'\n(?=\s*[○◦▪·\-•∙]|\s*\d+[.)]\s|\s*[가-하][.)]\s)')


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
    (0, re.compile(r'^(?:총론|각론)')),             # 총론 Part Ⅰ / 각론 Part Ⅱ
    (1, re.compile(r'^제\s*\d+\s*장')),             # 제1장. 두창
    (2, re.compile(r'^\d{1,2}\.')),                 # 1. 개요
    (3, re.compile(r'^[가-하]\.')),                 # 가. 역할
    (4, re.compile(r'^\d+\)|\([가-하]\)')),         # 1) / (가)
]
# 0~1만 chapter 필드에 — 번호 섹션(2)부터는 section_title
_CHAPTER_MAX_LEVEL = 1


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

    chapter   = ' '.join(chapter_parts)
    sec_title = ' > '.join(section_parts) or hdr or (crumbs[-1] if crumbs else '')
    return chapter, sec_title


def _clean_chapter(ch: str) -> str:
    """chapter 필드 정리: Part Ⅰ/Ⅱ 제거, 영문 병명 제거"""
    # "총론 Part Ⅰ" → "총론",  "각론 Part Ⅱ" → "각론"
    ch = re.sub(r'(총론|각론)\s+Part\s+[ⅠⅡⅢⅣⅤ]', r'\1', ch)
    # "제1장. 두창 Smallpox" → "제1장. 두창"  (영문 disease 표기 제거)
    ch = re.sub(r'(제\d+장\.\s*[가-힣]+)\s+[A-Z][a-z]+(?:\s+[A-Za-z]+)*', r'\1', ch)
    return ch.strip()


def _clean_section_title(sec: str) -> str:
    """section_title 필드 정리: 빈 경로·계속 마커 제거"""
    # " >  (계속 N/M)" 형태 — 빈 경로 뒤 계속 마커
    sec = re.sub(r'\s*>\s*\(계속\s*\d+/\d+\)', '', sec)
    # 끝에 남은 " > " 제거
    sec = re.sub(r'\s*>\s*$', '', sec)
    # "(계속 N/M)" 제거 — section_title은 내용명만
    sec = re.sub(r'\s*\(계속\s*\d+/\d+\)', '', sec)
    # "§" 잔재 제거 (병합 헤더에 간혹 섞임)
    sec = sec.replace('§', '')
    return sec.strip()


# ═════════════════════════════════════════════════════════════════════════════
# 7. 키워드 / 임베딩 / 가비지 필터
# ═════════════════════════════════════════════════════════════════════════════

_BIO_AGENT_RE = re.compile(
    r'두창바이러스|천연두|우두|원숭이두창'
    r'|예르시니아페스티스|페스트균|폐페스트|가래톳|선페스트'
    r'|탄저균|바실루스안트라시스|피부탄저|폐탄저|장탄저'
    r'|클로스트리디움|보툴리눔독소|보툴리즘|식이성보툴리눔|영아보툴리눔'
    r'|프란시셀라투라렌시스|야토균|튤라레미아'
)
_DRUG_RE = re.compile(
    r'독소신|시프로플록사신|독시사이클린|아목시실린|페니실린'
    r'|항독소|항혈청|백신|예방접종|예방적항생제'
    r'|렘데시비르|팍스로비드|항바이러스제|항생제'
)
_TEST_RE = re.compile(
    r'RT-?PCR|실시간PCR|배양검사|분리동정|마우스독소중화|항체검사'
    r'|혈청검사|검체채취|음압격리|국가지정입원치료병상'
)
_CLINICAL_RE = re.compile(
    r'[가-힣]{2,4}(?:잠복기|증상|마비|발열|발진|수포|가피|림프절|호흡곤란'
    r'|격리|접촉자|노출자|역학조사|사례분류|의사환자|확진환자)'
)
_ORG_RE = re.compile(
    r'질병관리청|보건소|권역별질병대응센터|시도대책본부'
    r'|국립검역소|보건환경연구원'
)


def extract_keywords(text: str, max_kw: int = 10) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()

    def _add(word: str) -> None:
        w = word.strip()
        if w and len(w) >= 2 and w not in seen and w not in STOPWORDS:
            keywords.append(w)
            seen.add(w)

    for pat in [_BIO_AGENT_RE, _DRUG_RE, _TEST_RE, _CLINICAL_RE, _ORG_RE]:
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
        if _SEP_ROW.match(line):   # |---|---| 구분선
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

    # 표 다음 일반 텍스트도 포함 (표 아래 산문)
    non_table = []
    for line in content.split('\n'):
        line = line.strip()
        if line and not line.startswith('|') and not _SEP_ROW.match(line):
            non_table.append(line)
    if non_table:
        parts.append(' '.join(non_table[:3]))

    return '\n'.join(parts)


def _extract_key_content(content: str) -> str:
    MAX = 800   # embed_text용: 1200자 한도 내에서 핵심 내용 최대 확보
    lines = [l for l in content.strip().split('\n') if l.strip()]

    # 단락 단위로 분리 — 첫 단락이 표일 수 있음 (표+산문 혼합 청크 대응)
    paragraphs = [b.strip() for b in re.split(r'\n{2,}', content.strip()) if b.strip()]
    first_para = paragraphs[0] if paragraphs else content

    # 전체 or 첫 단락이 표 → 평문 변환
    if is_table_block(content) or is_table_block(first_para):
        target = content if is_table_block(content) else first_para
        plain  = _table_to_plain(target)
        return plain[:MAX] if plain else content[:MAX]

    if is_list_block(content):
        _lpat = re.compile(r'^\s*[○◦▪·\-•∙]|\s*\d+[.)]\s|\s*[가-하][.)]\s')
        intro_lines = [l for l in lines if not _lpat.match(l)]
        list_lines  = [l for l in lines if _lpat.match(l)]
        intro = ' '.join(intro_lines[:2]) if intro_lines else ''
        items = '\n'.join(list_lines[:5])
        return ((intro + '\n' + items).strip() if intro else items)[:MAX]

    if paragraphs:
        first = paragraphs[0]
        if len(first) <= MAX:
            return first
        sents = _SENT_END.split(first)
        return ' '.join(sents[:2]).rstrip()[:MAX]

    return content[:MAX]


_EMBED_NOISE = re.compile(
    r'∙\'|'           # ∙' 불릿 잔재
    r'◦\s*|'          # ◦ 불릿
    r'[⇄→←↔▸▶•]\s*|' # 화살표·순서도 기호
    r'^\s*[①②③④⑤]\s*|'  # 원문자
    r'\s{2,}'         # 연속 공백 → 단일
)


def _clean_embed(text: str) -> str:
    """embed_text 전용 노이즈 제거 (dense 검색 품질 향상)"""
    text = _EMBED_NOISE.sub(lambda m: ' ' if m.group() == '\s{2,}' else
                            (' ' if m.group()[-1:] == ' ' else ''), text)
    # 연속 공백 정리
    text = re.sub(r'[ \t]{2,}', ' ', text)
    # 빈 줄 정리
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()


def build_embed_text(disease: str, chapter: str, section: str, content: str) -> str:
    """
    Dense 검색용 임베딩 텍스트.
    - text-embedding-3-small: 8191 토큰 지원 → 1200자까지 활용
    - 접두사(disease > chapter > section)는 context anchor 역할
    - 표는 _table_to_plain()으로 평문화, 나머지 노이즈는 _clean_embed()로 제거
    """
    ctx_parts = list(dict.fromkeys(p for p in [disease, chapter, section] if p))
    prefix    = ' > '.join(ctx_parts)
    key       = _clean_embed(_extract_key_content(content))
    result    = f"{prefix}: {key}" if prefix else key
    return result[:1200]


def infer_disease_name(chapter: str, section_title: str) -> str:
    for text in (chapter, section_title):
        m = _DISEASE_IN_CHAPTER.search(text)
        if m:
            return m.group(1)
    return DISEASE_GROUP


# 각론 유효 임상 섹션 패턴 (1.개요 ~ 7.예방)
_VALID_SECTION_RE = re.compile(
    r'(?:^|(?<=\s))(?:\d\s*\.\s*(?:개요|발생현황|역학적|임상적|실험실\s*검사|치료|예방))'
)
# disease명 + 영문명 이후 section 부분 추출
_SECTION_AFTER_DISEASE = re.compile(
    r'(?:두창|페스트|탄저|보툴리눔독소증|야토병)(?:\s+[A-Za-z]+)*\s+([\d가-하].+)'
)


def is_valid_disease_chunk(chapter: str, section_title: str, disease: str) -> bool:
    """
    각론 질병 챕터 청크가 실제 임상 정보(개요~예방)인지 판별.
    - 개정사항 챕터 → False
    - 부록·서식 귀속 내용 → False
    - 총론 섹션 → True
    - 유효 질병 섹션 → True
    """
    if disease == DISEASE_GROUP:
        return '개정' not in chapter
    m = _SECTION_AFTER_DISEASE.search(chapter)
    if m:
        section_part = re.sub(r'\s*\(계속\s*\d+/\d+\)', '', m.group(1)).strip()
        return bool(_VALID_SECTION_RE.match(section_part))
    first = re.sub(r'\s*\(계속\s*\d+/\d+\)', '', section_title.split(' · ')[0]).strip()
    return bool(_VALID_SECTION_RE.match(first))


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
    # ── level 0: 총론/각론 분리 ────────────────────────────────────────────
    part_secs = split_at_level(full_text, 0)
    print(f"  [파트] {len(part_secs)}개 감지")
    for s in part_secs:
        normalized = re.sub(r'\s+', '', s['header'])
        has_target = any(kw in normalized for kw in TARGET_PART_KEYWORDS)
        flag = '✅' if has_target else ('전체' if not s['header'] else '⏭️  스킵')
        print(f"    {flag}  [{s['header'] or '(헤더 없음)'}]  {len(s['body']):,}자")
    print()

    named = [
        s for s in part_secs
        if any(kw in re.sub(r'\s+', '', s['header']) for kw in TARGET_PART_KEYWORDS)
    ]
    process_secs = named if named else part_secs

    raw_all: list[dict] = []
    for part in process_secs:
        pheader = part['header'] or '전체'
        body    = part['body']
        print(f"  처리 중: [{pheader}]  {len(body):,}자  ", end='')
        before = len(raw_all)
        raw_all.extend(
            chunk_section(body=body, header=pheader, breadcrumbs=[], split_level=1)
        )
        print(f"→ {len(raw_all) - before}개 raw 청크")

    # ── 최종 포맷 변환 ────────────────────────────────────────────────────
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

        # 메타 정리
        chapter   = _clean_chapter(chapter_raw)
        sec_title = _clean_section_title(sec_title_raw)

        disease = infer_disease_name(chapter, sec_title)

        # 개정사항·부록·서식 제외
        if not is_valid_disease_chunk(chapter, sec_title, disease):
            continue

        # section_title이 비어있으면 chapter 마지막 토큰으로 보완
        if not sec_title:
            parts = chapter.split()
            sec_title = parts[-1] if parts else ''

        chunk_txt = ' > '.join(filter(None, [chapter, sec_title])) + '\n' + content

        final.append({
            'source_id':       f'dupest_{idx:04d}',
            'data_id':         DATA_ID,
            'source_category': SOURCE_CATEGORY,
            'knowledge_type':  KNOWLEDGE_TYPE,
            'disease_name':    disease,
            'document_title':  DOC_TITLE,
            'chapter':         chapter,
            'section_title':   sec_title,
            'content':         content,
            'chunk_text':      remove_nul(chunk_txt),
            'embed_text':      build_embed_text(disease, chapter, sec_title, content),
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
    ap = argparse.ArgumentParser(description='두창·페스트·탄저·보툴리눔·야토병 파서 v3 (docling)')
    ap.add_argument('--out',     type=Path, default=OUTPUT_FILE, help='출력 JSON 경로')
    ap.add_argument('--preview', action='store_true', help='샘플 출력만, JSON 저장 안 함')
    ap.add_argument('--stats',   action='store_true', help='크기 통계 출력')
    ap.add_argument('--toc',     action='store_true', help='문서 구조만 출력')
    ap.add_argument('--md',      type=Path, default=None,
                    help='Docling MD 파일 경로 (없으면 DOCLING_MD_PATH 사용)')
    args = ap.parse_args()

    print('[두창·페스트·탄저·보툴리눔·야토병 파서 v3]')
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
            normalized = re.sub(r'\s+', '', p['header'])
            has_target = any(kw in normalized for kw in TARGET_PART_KEYWORDS)
            flag = '✅' if has_target else '⏭️'
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

        from collections import Counter
        disease_cnt = Counter(c['disease_name'] for c in chunks)
        print('── disease_name 분포 ─────────────────────────────────────')
        for k, v in sorted(disease_cnt.items(), key=lambda x: -x[1]):
            print(f'  {k}: {v}개')
        print()

    print('── 샘플 청크 (처음 5개) ──────────────────────────────────')
    for c in chunks[:5]:
        path = ' > '.join(filter(None, [c['chapter'], c['section_title']]))
        print(f"  [{c['source_id']}] {path}")
        print(f"  {c['char_count']}자  disease={c['disease_name']}")
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

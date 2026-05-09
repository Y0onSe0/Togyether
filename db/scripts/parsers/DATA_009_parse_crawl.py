"""
parsers/DATA_009_parse_crawl.py
질병관리청 법정감염병 크롤링 데이터 (133종) → 섹션별 청킹 → JSON 저장

데이터 구조:
  name:         질병명 → disease_name
  icd_cd:       ICD 코드
  department:   담당부서 (6개 과)
  english_name: 영문명 (null 가능)
  group_name:   법정 등급 (1급/2급/3급/4급/조회전용) → chapter
  sections.content: ▢/□/▣ 섹션 + ◾ 불릿 혼합 텍스트 (Format A)
                 또는 섹션명\n○\n불릿 형식 (Format B)

청킹 전략:
  ▢ 섹션 하나 = 청크 하나
  section_title = 섹션명 (정의 / 원인 병원체 / 전파경로 / 임상증상 /
                          잠복기 및 전염기간 / 치료 / 예방 /
                          진단·신고 기준 / 담당부서 등)

출력: parsed/DATA_009_chunks_crawl.json
"""

import sys
import re
import json
from collections import Counter
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from config import CHUNK_SIZE

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 설정 ─────────────────────────────────────────────────────────────────
INPUT_FILE  = Path(__file__).parent.parent.parent.parent / "data" / "DATA_009_감염병_크롤링.json"
OUTPUT_DIR  = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE = OUTPUT_DIR / "DATA_009_chunks_crawl.json"

DATA_ID        = "DATA-009"
DOC_TITLE      = "질병관리청 법정감염병 정보"
KNOWLEDGE_TYPE = "disease_info"

# 출처: 질병관리청 감염병포털 > 감염병 정보 > 법정감염병(색인별)
# URL : https://npt.kdca.go.kr/npt/biz/npp/portal/nppPblctDtaView.do
SOURCE = "질병관리청 감염병포털 > 감염병 정보 > 법정감염병(색인별)"

# ── STOPWORDS ─────────────────────────────────────────────────────────────
STOPWORDS = {
    '관련', '통해', '경우', '대한', '따른', '위한', '통한', '기반',
    '따라서', '그러나', '하지만', '또한', '그리고', '이후', '이전',
    '이내', '이상', '이하', '있는', '있음', '있으며', '되어',
    '이를', '위해', '모든', '각각', '경우에', '관리', '지침',
    '개요', '현황', '절차', '목적', '대상', '범위', '내용',
    '방향', '원칙', '기본', '방법', '기준', '환자', '발생',
    '실시', '진행', '시행', '사용', '여부', '수행', '제공',
    '확인', '통보', '신고', '조치', '판단', '검토', '결과',
    '수준', '기간', '필요', '해당', '포함', '바랍니다',
    '질병관리청', '감염병', '안내',
}


# ── 텍스트 정리 ───────────────────────────────────────────────────────────

def clean_bullet_text(text: str) -> str:
    """
    PDF 크롤링 아티팩트 제거.
    (\nX\n) 괄호 / 줄바꿈으로 쪼개진 구두점·숫자·한글 연결.
    """
    # 1. 괄호 안 줄바꿈: (\nX\n) → (X)
    text = re.sub(
        r'\(\s*\n\s*([^)\n]*?)\s*\n\s*\)',
        lambda m: f'({m.group(1).strip()})',
        text,
    )
    # 2. 단독 구두점 줄: X\n,\nY → X, Y  /  X\n.\nY → X. Y
    text = re.sub(r'\n\s*,\s*\n', ', ', text)
    text = re.sub(r'\n\s*\.\s*\n', '. ', text)
    text = re.sub(r'\n\s*-\s*\n', ' - ', text)
    text = re.sub(r'\n\s*·\s*\n', '·', text)
    # 3. 여는/닫는 괄호 주변 줄바꿈
    text = re.sub(r'\(\n', '(', text)
    text = re.sub(r'\n\)', ')', text)
    # 4. 콜론 앞 줄바꿈: "질병코드\n: ..." → "질병코드: ..."
    text = re.sub(r'\n\s*:', ':', text)
    # 5. 숫자 + 한글 연결: "24\n시간" → "24시간", "1~3\n일" → "1~3일"
    text = re.sub(r'(\d)\n([가-힣])', r'\1\2', text)
    # 6. 한글/영문/숫자/닫는괄호 → 한글/영문/숫자/여는괄호 줄 연결
    text = re.sub(r'([가-힣A-Za-z0-9)])\n([가-힣A-Za-z0-9(])', r'\1 \2', text)
    # 7. 쉼표 뒤 줄바꿈 (끊긴 목록)
    text = re.sub(r',\n', ', ', text)
    # 8. 줄 끝 슬래시 제거 (담당부서 구분자 아티팩트)
    text = re.sub(r'\s*/\s*$', '', text, flags=re.MULTILINE)
    # 9. 남은 줄바꿈 → 공백
    text = re.sub(r'\n+', ' ', text)
    # 10. 다중 공백 → 단일
    text = re.sub(r'  +', ' ', text)
    return text.strip()


# ── 이름·텍스트 정규화 ────────────────────────────────────────────────────

# embed_text에서 제거할 특수문자
_SPECIAL_CHARS_RE = re.compile(r'[•⊙※Ⅹ․\n]+')


def strip_disease_prefix(name: str) -> str:
    """
    질병명 앞의 카테고리 괄호 제거.
    '(급성호흡기감염증)사람 코로나바이러스 감염증' → '사람 코로나바이러스 감염증'
    '(장관감염증)노로바이러스 감염증'             → '노로바이러스 감염증'
    괄호가 없으면 원본 반환.
    """
    return re.sub(r'^\([^)]+\)\s*', '', name).strip()


def clean_embed_text(text: str) -> str:
    """
    embed_text 전용 정리: 특수기호·줄바꿈 제거 후 단일 공백 정규화.
    제거 대상: • ⊙ ※ Ⅹ ․ (U+2024 ONE DOT LEADER)
    """
    text = _SPECIAL_CHARS_RE.sub(' ', text)
    text = re.sub(r'  +', ' ', text)
    return text.strip()


# ── Format A 파서 (▢ + ◾) ─────────────────────────────────────────────────

def normalize_section_name(raw: str) -> str:
    """섹션명 정규화: 아티팩트 공백·구두점 제거."""
    name = raw.strip()
    name = re.sub(r'\s+', ' ', name)
    name = re.sub(r'\s*·\s*', '·', name)
    name = re.sub(r'\s*\.\s*', '.', name)
    return name


def parse_sections_a(content: str) -> list[tuple[str, str]]:
    """
    Format A: ▢/□/▣ 섹션 분리 → [(section_name, cleaned_body), ...]
    섹션명: 첫 번째 ◾ 이전 텍스트
    본문:   ◾ 불릿들 정리 후 '• ...' 형식으로 재조합
    """
    raw_sections = re.split(r'[▢□▣]\s*\n', content)
    result: list[tuple[str, str]] = []

    for raw in raw_sections:
        if not raw.strip():
            continue

        # 섹션명: 첫 번째 ◾ 이전
        if '◾' in raw:
            header_part, _, rest = raw.partition('◾')
            bullets_raw_str = '◾' + rest
        else:
            header_part = raw
            bullets_raw_str = ''

        sec_name = normalize_section_name(header_part)
        if not sec_name:
            continue

        # ◾ 불릿 분리 → 정리
        bullets_raw = re.split(r'◾\s*\n?', bullets_raw_str)
        bullets: list[str] = []
        for b in bullets_raw:
            cleaned = clean_bullet_text(b)
            if cleaned:
                bullets.append(cleaned)

        if not bullets:
            continue

        body_text = '\n'.join(f'• {b}' for b in bullets)
        result.append((sec_name, body_text))

    return result


# ── Format B 파서 (○ bullets, no ▢ marker) ───────────────────────────────

# Format B 섹션명이 아닌 본문 단어들 (이 단어를 포함하면 내용 줄로 판단)
_NOT_SEC_WORDS = {
    '이상', '이하', '이내', '이후', '이전', '위한', '위해',
    '씻기', '하기', '받기', '닦기', '하여', '등의',
    '경우', '따라', '에서', '로써', '하도록', '가능',
}


def _normalize_sec_name_b(name: str) -> str:
    """
    Format B 섹션명 정규화.
    "정 의" → "정의" (단음절 낱말이 공백으로 쪼개진 경우 합치기).
    "일반적 예방" 같이 다음절 단어 사이 공백은 유지.
    """
    words = name.split()
    if len(words) > 1 and all(len(w) <= 2 for w in words):
        return ''.join(words)
    return name


def is_section_name_b(line: str) -> bool:
    """
    Format B에서 줄이 섹션명인지 판별.
    조건: 짧고(≤20자), 한글+특수기호만, 숫자 없음,
          본문 서술어(_NOT_SEC_WORDS) 미포함.
    """
    line = line.strip()
    if not line or len(line) > 20:
        return False
    # 한글, 공백, ·, /, (, ) 만 — 숫자·영문자 없음
    if not re.match(r'^[가-힣·/\s\(\)]+$', line):
        return False
    if len(line) < 2:
        return False
    # 본문 서술어 포함 시 섹션명 아님 ("초 이상 손 씻기", "진단을 위한 검사기준" 등)
    words_in_line = re.findall(r'[가-힣]{2,}', line)
    if any(w in _NOT_SEC_WORDS for w in words_in_line):
        return False
    return True


def parse_sections_b(content: str) -> list[tuple[str, str]]:
    """
    Format B: 섹션명\n○\n불릿1\n[섹션명\n○\n불릿2\n...] 형식 파싱.

    ○\n 으로 분리 후:
      parts[0] = 첫 섹션명 (마지막 줄)
      parts[i] = [불릿 내용]\n[다음 섹션명]  ← 마지막 줄이 섹션명인 경우
               = [불릿 내용]               ← 같은 섹션의 다음 불릿
    """
    parts = re.split(r'[○⊙]\s*\n', content)

    sections: list[tuple[str, str]] = []
    current_sec: str | None = None
    current_bullets: list[str] = []

    for i, part in enumerate(parts):
        lines = part.split('\n')
        # 끝의 빈 줄 제거
        while lines and not lines[-1].strip():
            lines.pop()

        if i == 0:
            # 첫 ○ 이전: 마지막 줄 = 첫 번째 섹션명
            if lines:
                current_sec = _normalize_sec_name_b(lines[-1].strip())
            continue

        # 마지막 줄이 다음 섹션명인지 판별
        if lines and is_section_name_b(lines[-1]) and i < len(parts) - 1:
            next_sec  = _normalize_sec_name_b(lines[-1].strip())
            bullet_lines = lines[:-1]
        else:
            next_sec     = None
            bullet_lines = lines

        # 현재 불릿 정리
        bullet_text = clean_bullet_text('\n'.join(bullet_lines))
        if bullet_text and current_sec is not None:
            current_bullets.append(bullet_text)

        # 섹션 전환
        if next_sec is not None:
            if current_sec and current_bullets:
                body = '\n'.join(f'• {b}' for b in current_bullets)
                sections.append((current_sec, body))
            current_sec    = next_sec
            current_bullets = []

    # 마지막 섹션 저장
    if current_sec and current_bullets:
        body = '\n'.join(f'• {b}' for b in current_bullets)
        sections.append((current_sec, body))

    return sections


# ── 포맷 자동 감지 ──────────────────────────────────────────────────────────

def parse_sections(content: str) -> list[tuple[str, str]]:
    """
    content 포맷 자동 감지 후 섹션 파싱.
    Format A: ◾ (BLACK CIRCLE U+25CF) 불릿 사용 → ▢ 섹션 헤더 + ◾ 불릿
    Format B: ○ (WHITE CIRCLE U+25CB) 불릿 사용 → 섹션명\n○\n불릿 형식
    (▣/□ 문자는 본문 내 장식으로 등장할 수 있어 포맷 판별 기준 제외)
    """
    if '◾' in content:
        return parse_sections_a(content)
    if '○' in content or '⊙' in content:
        return parse_sections_b(content)
    return []


# ── 키워드 추출 ───────────────────────────────────────────────────────────

def extract_keywords(text: str, max_kw: int = 10) -> list[str]:
    kor = re.findall(r'[가-힣]{2,}', text)
    eng = re.findall(r'\b[A-Za-z]{2,}\b', text)
    freq = Counter(w for w in kor + eng if w not in STOPWORDS)
    return [w for w, _ in freq.most_common(max_kw)]


# ── 메인 ─────────────────────────────────────────────────────────────────

def main():
    import argparse
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--preview', action='store_true', help='샘플 출력만, JSON 저장 없음')
    args = arg_parser.parse_args()

    print(f"[크롤링 파서] DATA-009 시작")
    print(f"  입력: {INPUT_FILE}")
    print(f"  출력: {OUTPUT_FILE}\n")

    if not INPUT_FILE.exists():
        print(f"[오류] 파일 없음: {INPUT_FILE}")
        return

    with open(INPUT_FILE, encoding='utf-8') as f:
        items = json.load(f)

    print(f"  총 {len(items)}개 질병\n")

    chunks: list[dict] = []
    global_idx = 0
    dept_counter:  dict[str, int] = {}
    group_counter: dict[str, int] = {}
    sec_counter:   dict[str, int] = {}
    fmt_counter:   dict[str, int] = {'A': 0, 'B': 0, 'unknown': 0}

    for dis_idx, item in enumerate(items):
        name_raw     = item.get('name', '').strip()
        name         = strip_disease_prefix(name_raw)   # "(급성호흡기감염증)..." → "..."
        english_name = (item.get('english_name') or '').strip()
        department   = item.get('department', '').strip()
        group_name   = item.get('group_name', '').strip()
        icd_cd       = item.get('icd_cd', '')
        content_raw  = item.get('sections', {}).get('content', '')

        dept_counter[department]  = dept_counter.get(department, 0) + 1
        group_counter[group_name] = group_counter.get(group_name, 0) + 1

        if not name or not content_raw:
            continue

        # 포맷 기록
        if '◾' in content_raw:
            fmt_counter['A'] += 1
        elif '○' in content_raw or '⊙' in content_raw:
            fmt_counter['B'] += 1
        else:
            fmt_counter['unknown'] += 1

        sections = parse_sections(content_raw)

        for sec_idx, (sec_name, body_text) in enumerate(sections):
            sec_counter[sec_name] = sec_counter.get(sec_name, 0) + 1

            en_part   = f' {english_name}' if english_name else ''
            dept_part = f' [{department}]' if department else ''

            # embed_text: 질병명 + 영문명 + 섹션명 + 내용 앞부분 (특수기호 제거)
            embed_text = clean_embed_text(
                f"{name}{en_part} - {sec_name}: {body_text[:400]}"
            )

            # chunk_text: BM25용 — 질병명·부서·등급·ICD 포함
            chunk_text = (
                f"{name}{en_part} {group_name}{dept_part}"
                + (f" {icd_cd}" if icd_cd else "")
                + f"\n[{sec_name}]\n{body_text}"
            )
            if len(chunk_text) > CHUNK_SIZE * 3:
                chunk_text = chunk_text[:CHUNK_SIZE * 3]

            # content: LLM 컨텍스트용
            content_out = (
                f"질병명: {name}{en_part}\n"
                f"등급: {group_name}  담당부서: {department}\n"
                f"섹션: {sec_name}\n\n"
                f"{body_text}"
            )

            # keywords: 부서명 최우선, 이후 빈도 기반
            kw_raw = extract_keywords(name + en_part + ' ' + body_text)
            keywords: list[str] = []
            if department:
                keywords.append(department)
            for w in kw_raw:
                if w not in keywords:
                    keywords.append(w)
            keywords = keywords[:10]

            chunk = {
                'source_id':       f'disease_{dis_idx:04d}_s{sec_idx:02d}',
                'data_id':         DATA_ID,
                'source_category': 'disease',
                'knowledge_type':  KNOWLEDGE_TYPE,
                'disease_name':    name,
                'document_title':  DOC_TITLE,
                'chapter':         group_name,
                'section_title':   sec_name,
                'content':         content_out,
                'chunk_text':      chunk_text,
                'embed_text':      embed_text,
                'chunk_index':     global_idx,
                'keywords':        keywords,
                'source':          SOURCE,
                'embedding':       None,
            }
            chunks.append(chunk)
            global_idx += 1

    total = len(chunks)

    # ── 통계 출력 ─────────────────────────────────────────────────────────
    print("══ 파싱 결과 ══════════════════════════════════════")
    print(f"\n  [포맷 분포] Format A(▢◾): {fmt_counter['A']}개  "
          f"Format B(○): {fmt_counter['B']}개  "
          f"미분류: {fmt_counter['unknown']}개")

    print("\n  [법정 등급별]")
    for g, cnt in sorted(group_counter.items()):
        print(f"    {g:10s}: {cnt}개 질병")

    print("\n  [담당부서별]")
    for d, cnt in sorted(dept_counter.items(), key=lambda x: -x[1]):
        print(f"    {d:20s}: {cnt}개 질병")

    print("\n  [주요 섹션별 청크 수 (상위 20)]")
    for s, cnt in sorted(sec_counter.items(), key=lambda x: -x[1])[:20]:
        print(f"    {s:30s}: {cnt}청크")

    print(f"\n  총 {len(items)}개 질병 → {total}개 청크")

    # ── 샘플 출력 ─────────────────────────────────────────────────────────
    print("\n── Format A 샘플 (처음 2개) ────────────────────────")
    for c in chunks[:2]:
        print(f"  source_id    : {c['source_id']}")
        print(f"  disease_name : {c['disease_name']}")
        print(f"  section_title: {c['section_title']}")
        print(f"  embed_text 앞80: {c['embed_text'][:80]!r}")
        print()

    print("── Format B 샘플 ────────────────────────")
    b_chunks = [c for c in chunks if '_s0' in c['source_id']
                and not any(c['disease_name'].startswith(p)
                            for p in ['(급성호흡기감염증)'])]
    for c in b_chunks[:2]:
        print(f"  source_id    : {c['source_id']}")
        print(f"  disease_name : {c['disease_name']}")
        print(f"  section_title: {c['section_title']}")
        print(f"  content 앞120: {c['content'][:120]!r}")
        print()

    print("── 담당부서 섹션 샘플 ────────────────────────")
    dept_chunks = [c for c in chunks if c['section_title'] == '담당부서']
    for c in dept_chunks[:3]:
        print(f"  disease_name : {c['disease_name']}")
        print(f"  content      : {c['content']!r}")
        print()

    if args.preview:
        print("[preview] JSON 저장 건너뜀")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    print(f"[완료] 저장: {OUTPUT_FILE}  ({total}청크)")


if __name__ == '__main__':
    main()

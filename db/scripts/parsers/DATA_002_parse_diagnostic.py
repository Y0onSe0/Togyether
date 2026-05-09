"""
DATA_002_parse_diagnostic.py
법정감염병 진단검사 통합지침 — 원본 JSON 후처리 파서

기존 PDF 파싱(pdfplumber)은 사이드바 노이즈를 제대로 제거하지 못해
질병명·섹션 분리는 올바른 원본 JSON을 그대로 활용하고,
아래 처리만 추가 적용한다.

  1. content / section_title 사이드바 노이즈 제거
     - 급·감·염·병·개·요·제 단독 줄, 줄 끝 단독 한글자
     - 단독 숫자 줄(페이지 번호), [제개N급요-N] 목차 잔여물
  2. chunk_text 재생성 (정제된 content 기반)
  3. DB 필드 추가 — source_id, data_id, source_category,
                    knowledge_type, embed_text, embedding
  4. 키워드 재생성 — Counter 빈도 기반 (STOPWORDS 제거)
  5. 가비지 청크 필터 — 한글 30자 미만 or 한글 비율 40% 미만 제외
  6. disease_name 정규화 — 법정감염병 약 130종 공식 명칭만 사용

입력 파일 (우선순위):
  1. --input 인수로 직접 지정
  2. 환경 변수 DATA_002_SRC
  3. db/scripts/parsed/DATA_002_chunks_diagnostic_원본.json (프로젝트 내)
  4. C:/Users/<현재 유저>/Downloads/DATA_002_chunks_diagnostic_원본.json

출력: parsed/DATA_002_chunks_diagnostic.json

실행:
    python parsers/DATA_002_parse_diagnostic.py
    python parsers/DATA_002_parse_diagnostic.py --preview
    python parsers/DATA_002_parse_diagnostic.py \\
        --input "C:/Users/jys72/Downloads/DATA_002_chunks_diagnostic_원본.json"
"""

import os
import re
import sys
import json
import argparse
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 상수 ─────────────────────────────────────────────────────────────────
DOC_TITLE        = "본책_법정감염병 진단검사 통합지침(제4-2판)"
OUTPUT_DIR       = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE      = OUTPUT_DIR / "DATA_002_chunks_diagnostic.json"
DATA_ID          = "DATA-002"
SOURCE_CATEGORY  = "disease"
KNOWLEDGE_TYPE   = "disease_guideline"

# 원본 JSON 기본 탐색 경로 (우선순위 순)
_DEFAULT_SRC_CANDIDATES = [
    Path(__file__).parent.parent / "parsed" / "DATA_002_chunks_diagnostic_원본.json",
    Path.home() / "Downloads" / "DATA_002_chunks_diagnostic_원본.json",
]


# ── 법정감염병 공식 명칭 목록 (약 130종) ─────────────────────────────────
CANONICAL_DISEASES = [
    # 제1급
    "에볼라바이러스병",
    "마버그열",
    "라싸열",
    "크리미안콩고출혈열",
    "아르헨티나출혈열",
    "볼리비아출혈열",
    "베네수엘라출혈열",
    "브라질출혈열",
    "리프트밸리열",
    "두창",
    "페스트",
    "탄저",
    "보툴리눔독소증",
    "야토병",
    "신종감염병증후군",
    "중증급성호흡기증후군(SARS)",
    "중동호흡기증후군(MERS)",
    "동물인플루엔자 인체감염증",
    "신종인플루엔자",
    "디프테리아",
    "니파바이러스감염증",
    # 제2급
    "결핵",
    "수두",
    "홍역",
    "콜레라",
    "장티푸스",
    "파라티푸스",
    "세균성이질",
    "장출혈성대장균 감염증",
    "A형간염",
    "백일해",
    "유행성이하선염",
    "풍진",
    "폴리오",
    "수막구균 감염증",
    "b형헤모필루스인플루엔자",
    "폐렴구균 감염증",
    "한센병",
    "성홍열",
    "반코마이신내성황색포도알균(VRSA) 감염증",
    "카바페넴내성장내세균목(CRE) 감염증",
    "E형간염",
    # 제3급
    "파상풍",
    "B형간염",
    "일본뇌염",
    "C형간염",
    "말라리아",
    "레지오넬라증",
    "비브리오패혈증",
    "발진티푸스",
    "발진열",
    "쯔쯔가무시증",
    "렙토스피라증",
    "브루셀라증",
    "공수병",
    "신증후군출혈열",
    "후천성면역결핍증(AIDS)",
    "크로이츠펠트-야콥병(CJD) 및 변종크로이츠펠트-야콥병(vCJD)",
    "황열",
    "뎅기열",
    "큐열",
    "웨스트나일열",
    "라임병",
    "진드기매개뇌염",
    "유비저",
    "치쿤구니야열",
    "중증열성혈소판감소증후군(SFTS)",
    "지카바이러스 감염증",
    "엠폭스(Mpox)",
    # 제4급 — 성매개감염병
    "매독",
    "임질",
    "클라미디아 감염증",
    "연성하감",
    "성기단순포진",
    "첨규콘딜롬",
    "사람유두종바이러스 감염증",
    # 제4급 — 기타
    "인플루엔자",
    "회충증",
    "편충증",
    "요충증",
    "간흡충증",
    "폐흡충증",
    "장흡충증",
    "수족구병",
    # 제4급 — 의료관련감염병
    "반코마이신내성장알균(VRE) 감염증",
    "메티실린내성황색포도알균(MRSA) 감염증",
    "다제내성녹농균(MRPA) 감염증",
    "다제내성아시네토박터바우마니균(MRAB) 감염증",
    # 제4급 — 장관감염병
    "살모넬라균 감염증",
    "장염비브리오균 감염증",
    "장독소성대장균(ETEC) 감염증",
    "장침습성대장균(EIEC) 감염증",
    "장병원성대장균(EPEC) 감염증",
    "캄필로박터균 감염증",
    "클로스트리듐 퍼프린젠스 감염증",
    "황색포도알균 감염증",
    "바실루스 세레우스균 감염증",
    "예르시니아 엔테로콜리티카 감염증",
    "리스테리아 모노사이토제네스 감염증",
    "그룹 A형 로타바이러스 감염증",
    "아스트로바이러스 감염증",
    "장내 아데노바이러스 감염증",
    "노로바이러스 감염증",
    "사포바이러스 감염증",
    "이질아메바 감염증",
    "람블편모충 감염증",
    "작은와포자충 감염증",
    "원포자충 감염증",
    # 제4급 — 급성호흡기감염병
    "아데노바이러스 감염증",
    "사람 보카바이러스 감염증",
    "파라인플루엔자바이러스 감염증",
    "호흡기세포융합바이러스 감염증",
    "리노바이러스 감염증",
    "사람 메타뉴모바이러스 감염증",
    "사람 코로나바이러스 감염증",
    "마이코플라스마 폐렴균 감염증",
    "클라미디아 폐렴균 감염증",
    # 제4급 — 해외유입기생충
    "리슈만편모충증",
    "바베스열원충증",
    "아프리카수면병",
    "주혈흡충증",
    "샤가스병",
    "광동주혈선충증",
    "악구충증",
    "사상충증",
    "포충증",
    "톡소포자충증",
    "메디나충증",
    # 기타
    "엔테로바이러스 감염증",
    "코로나바이러스감염증-19",
]

# 정규화 키 → 공식 명칭 매핑
# 정규화: 소문자 + 알파벳·한글·숫자만 남김 (공백·괄호·하이픈 제거)
def _normalize(s: str) -> str:
    return re.sub(r'[^가-힣a-z0-9]', '', s.lower())

_DISEASE_LOOKUP: dict[str, str] = {
    _normalize(d): d for d in CANONICAL_DISEASES
}

# 추가 별칭 매핑 (원본 JSON 에서 다를 수 있는 표기)
_ALIASES = {
    # 남아메리카출혈열 계열 (아르헨티나·볼리비아·베네수엘라·브라질 통칭)
    _normalize("남아메리카출혈열"): "아르헨티나출혈열",   # 최선 매핑
    _normalize("아르헨티나출혈열(후닌)"): "아르헨티나출혈열",
    _normalize("볼리비아출혈열(마추포)"): "볼리비아출혈열",
    _normalize("베네수엘라출혈열(구아나리토)"): "베네수엘라출혈열",
    _normalize("브라질출혈열(사비아)"): "브라질출혈열",
    # 약어·한영 혼용
    _normalize("SARS"): "중증급성호흡기증후군(SARS)",
    _normalize("MERS"): "중동호흡기증후군(MERS)",
    _normalize("AIDS"): "후천성면역결핍증(AIDS)",
    _normalize("CJD"): "크로이츠펠트-야콥병(CJD) 및 변종크로이츠펠트-야콥병(vCJD)",
    _normalize("vCJD"): "크로이츠펠트-야콥병(CJD) 및 변종크로이츠펠트-야콥병(vCJD)",
    _normalize("SFTS"): "중증열성혈소판감소증후군(SFTS)",
    _normalize("CRE"): "카바페넴내성장내세균목(CRE) 감염증",
    _normalize("VRSA"): "반코마이신내성황색포도알균(VRSA) 감염증",
    _normalize("VRE"): "반코마이신내성장알균(VRE) 감염증",
    _normalize("MRSA"): "메티실린내성황색포도알균(MRSA) 감염증",
    _normalize("MRPA"): "다제내성녹농균(MRPA) 감염증",
    _normalize("MRAB"): "다제내성아시네토박터바우마니균(MRAB) 감염증",
    _normalize("Mpox"): "엠폭스(Mpox)",
    _normalize("엠폭스"): "엠폭스(Mpox)",
    _normalize("코로나19"): "코로나바이러스감염증-19",
    _normalize("코로나바이러스감염증19"): "코로나바이러스감염증-19",
    _normalize("COVID-19"): "코로나바이러스감염증-19",
    _normalize("COVID19"): "코로나바이러스감염증-19",
    _normalize("HPV감염증"): "사람유두종바이러스 감염증",
    # 표기 변형
    _normalize("신증후군출혈열(유행성출혈열)"): "신증후군출혈열",
    _normalize("유행성출혈열"): "신증후군출혈열",
    _normalize("공수병(광견병)"): "공수병",
    _normalize("광견병"): "공수병",
    _normalize("b형헤모필루스인플루엔자감염증"): "b형헤모필루스인플루엔자",
}
_DISEASE_LOOKUP.update(_ALIASES)


def resolve_disease_name(raw: str) -> str | None:
    """
    원본 JSON disease_name 을 공식 법정감염병 명칭으로 변환한다.
    매핑 실패 시 None 반환.
    """
    raw = raw.strip()
    key = _normalize(raw)
    # 1) 정확 매핑
    if key in _DISEASE_LOOKUP:
        return _DISEASE_LOOKUP[key]
    # 2) 부분 포함 매핑 (공식 명칭 키가 key 에 포함되거나 key 가 공식 명칭 키에 포함)
    for canon_key, canon_name in _DISEASE_LOOKUP.items():
        if canon_key and (canon_key in key or key in canon_key):
            return canon_name
    return None


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
    # 진단검사 공통어 (모든 섹션에 반복 등장)
    '검사법', '진단검사', '검사기준', '세부검사법', '유전자검출검사',
    '검체에서', '특이유전자', '채취용기', '채취량', '채취시기',
    '보관온도', '혈청분리', '항응고제', '유전자', '확인진단',
}


# ── 사이드바 노이즈 제거 패턴 ─────────────────────────────────────────────
_NOISE_PATTERNS = [
    # (1) 수직 "제N급 감염병" 사이드바 전체 시퀀스
    re.compile(r'제\s*\n\s*\d+\s*\n\s*급\s*\n\s*감\s*\n\s*염\s*\n\s*병\s*\n?'),
    re.compile(r'제\s*\n\s*\d+\s*\n\s*급\s*\n?'),

    # (2) "개요" 수직 사이드바
    re.compile(r'개\s*\n\s*요\s*\n?'),

    # (3) [제개N급요-N] 목차 잔여물 (다음 질병 헤더 링크)
    re.compile(r'\[제개\d+급요-\d+\][^\n]*'),

    # (4) 줄 끝 단독 사이드바 한글자 (공백 + 글자 + 줄바꿈)
    re.compile(r'[ \t]+[급감염병개요제]\n'),

    # (5) 단독 줄의 사이드바 한글자 (줄 전체가 한 글자)
    re.compile(r'^\s*[급감염병개요제]\s*$', re.MULTILINE),

    # (6) 줄 끝 단독 숫자 (페이지·섹션 번호 사이드바)
    re.compile(r'(?<=[가-힣A-Za-z℃%])\s[0-9]\n'),

    # (7) 단독 숫자 줄 (페이지 번호)
    re.compile(r'^\s*\d{1,3}\s*$', re.MULTILINE),

    # (8) www.kdca.go.kr 헤더/푸터
    re.compile(r'www\.kdca\.go\.kr[^\n]*'),

    # (9) NUL 문자
    re.compile(r'\x00'),
]


def clean_content(text: str) -> str:
    """content 필드 사이드바 노이즈 제거 및 공백 정리."""
    for pat in _NOISE_PATTERNS:
        text = pat.sub('', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    return text.strip()


def clean_section_title(title: str) -> str:
    """section_title 끝에 흘러들어온 사이드바 글자 제거."""
    title = re.sub(r'\s+[급감염병개요제]\s*\d*\s*$', '', title)
    title = re.sub(r'\s+\d+\s*$', '', title)
    return title.strip()


# ── 키워드 / 임베딩 유틸 ──────────────────────────────────────────────────

def extract_keywords(text: str, max_kw: int = 10) -> list[str]:
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
    """가비지 청크 판별."""
    kor_chars = len(re.findall(r'[가-힣]', content))
    if kor_chars < 30:
        return True
    total = len(content.replace(' ', '').replace('\n', ''))
    if total > 0 and kor_chars / total < 0.4:
        return True
    return False


# ── 입력 파일 탐색 ────────────────────────────────────────────────────────

def resolve_input_path(cli_input: str | None) -> Path:
    if cli_input:
        p = Path(cli_input)
        if p.exists():
            return p
        raise FileNotFoundError(f"--input 경로를 찾을 수 없음: {p}")

    env = os.environ.get("DATA_002_SRC")
    if env:
        p = Path(env)
        if p.exists():
            return p

    for p in _DEFAULT_SRC_CANDIDATES:
        if p.exists():
            return p

    raise FileNotFoundError(
        "원본 JSON을 찾을 수 없습니다.\n"
        "다음 중 하나로 지정하세요:\n"
        "  python DATA_002_parse_diagnostic.py "
        '--input "경로/DATA_002_chunks_diagnostic_원본.json"\n'
        f"  또는 파일을 아래 위치에 복사:\n"
        f"  {_DEFAULT_SRC_CANDIDATES[0]}"
    )


# ── 메인 처리 ─────────────────────────────────────────────────────────────

def process(src_path: Path) -> list[dict]:
    """원본 JSON 로드 → 정제 → 새 필드 추가 → 청크 리스트 반환."""
    with open(src_path, encoding='utf-8') as f:
        original: list[dict] = json.load(f)

    print(f"  원본 청크: {len(original)}개")

    chunks      = []
    skipped     = 0
    noise_fixed = 0
    unmatched   = {}   # {raw_name: count}

    for item in original:
        raw_content   = item.get('content', '')
        raw_sec_title = item.get('section_title', '')

        # ── 정제 ──────────────────────────────────────────────
        content   = clean_content(raw_content)
        sec_title = clean_section_title(raw_sec_title)

        if content != raw_content:
            noise_fixed += 1

        raw_dname = item['disease_name'].strip()
        chapter   = item.get('chapter', '').strip()
        source    = item.get('source', DOC_TITLE)

        # ── disease_name 정규화 ────────────────────────────────
        dname = resolve_disease_name(raw_dname)
        if dname is None:
            # 법정감염병 명칭과 매핑 안 되면 스킵
            unmatched[raw_dname] = unmatched.get(raw_dname, 0) + 1
            skipped += 1
            continue

        # chunk_text: BM25 색인 + LLM 컨텍스트용
        # DOC_TITLE 은 모든 청크에 동일 → BM25 변별력 없음 → 제외
        # chapter·disease_name·section_title 은 키워드 매칭에 직접 기여
        chunk_text = f"{chapter} {dname} {sec_title}\n{content}"

        # ── 가비지 필터 ────────────────────────────────────────
        if is_garbage_chunk(content):
            skipped += 1
            continue

        chunks.append({
            'source_id':       item['id'],
            'data_id':         DATA_ID,
            'source_category': SOURCE_CATEGORY,
            'knowledge_type':  KNOWLEDGE_TYPE,
            'disease_name':    dname,
            'document_title':  DOC_TITLE,
            'chapter':         chapter,
            'section_title':   sec_title,
            'content':         content,
            'chunk_text':      chunk_text,
            'embed_text':      build_embed_text(dname, sec_title, content),
            'chunk_index':     item.get('chunk_index', 0),
            'keywords':        extract_keywords(f"{dname} {sec_title} {content}"),
            'source':          source,
            'embedding':       None,
        })

    print(f"  노이즈 정제: {noise_fixed}개 청크")
    print(f"  가비지 제거: {skipped}개 청크")
    print(f"  최종 청크  : {len(chunks)}개")

    if unmatched:
        print(f"\n  ⚠ 법정감염병 명칭 불일치 → 제외 ({len(unmatched)}종, 총 {sum(unmatched.values())}청크):")
        for name, cnt in sorted(unmatched.items(), key=lambda x: -x[1]):
            print(f"    [{cnt:3d}청크] {name}")

    return chunks


def main():
    parser = argparse.ArgumentParser(
        description="DATA_002 진단검사 통합지침 원본 JSON 후처리"
    )
    parser.add_argument(
        '--input', '-i',
        help='원본 JSON 파일 경로 (미지정 시 기본 위치 자동 탐색)',
        default=None,
    )
    parser.add_argument(
        '--preview', action='store_true',
        help='샘플 10개 출력만, JSON 저장 없음',
    )
    args = parser.parse_args()

    print("[DATA_002 진단검사 통합지침 후처리] 시작")

    try:
        src_path = resolve_input_path(args.input)
    except FileNotFoundError as e:
        print(f"\n[오류] {e}")
        sys.exit(1)

    print(f"  입력: {src_path}")
    print(f"  출력: {OUTPUT_FILE}\n")

    chunks = process(src_path)

    # ── 미리보기 ───────────────────────────────────────────────────────────
    print("\n── 샘플 청크 (처음 5개) ────────────────────────")
    for c in chunks[:5]:
        print(f"  source_id   : {c['source_id']}")
        print(f"  disease_name: {c['disease_name']}")
        print(f"  chapter     : {c['chapter']}")
        print(f"  section     : {c['section_title']}")
        print(f"  keywords    : {c['keywords']}")
        print(f"  content 길이: {len(c['content'])}자")
        print()

    if args.preview:
        print("[preview] JSON 저장 건너뜀")
        return

    # ── 저장 ──────────────────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    print(f"[완료] 저장: {OUTPUT_FILE}")

    # ── 질병·등급별 통계 ──────────────────────────────────────────────────
    from collections import defaultdict
    by_chapter: dict[str, list] = defaultdict(list)
    for c in chunks:
        by_chapter[c['chapter']].append(c['disease_name'])

    print("\n── 등급별 질병 현황 ────────────────────────────")
    for chapter in sorted(by_chapter):
        diseases = sorted(set(by_chapter[chapter]))
        print(f"  {chapter}: {len(diseases)}종")
        for d in diseases:
            cnt = sum(1 for c in chunks if c['disease_name'] == d)
            print(f"    {d} ({cnt}청크)")


if __name__ == '__main__':
    main()

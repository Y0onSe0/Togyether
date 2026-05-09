"""
parsers/DATA_015_parse_faq.py
질병관리청 감염병포털 FAQ (90건) → 청킹 → JSON 저장

데이터 구조:
  category: 감염병정보(19) / 코로나19(71)
  question: 질문 내용
  answer:   답변 내용

source_category 규칙:
  질문 + 답변에 _SYSTEM_KEYWORDS 포함 → 'system'
  그 외                              → 'disease'

disease_name 규칙 (source_category == 'disease' 인 경우):
  category == '코로나19'              → '코로나바이러스감염증-19'
  '인플루엔자' or '독감' in question  → '인플루엔자'
  'AIDS' or '후천성면역결핍' in q     → '후천성면역결핍증(AIDS)'
  그 외                              → None

section_title / keywords:
  GPT-4o-mini 배치 호출로 AI 생성 (10건씩 묶어서 처리)
  --no-ai 플래그 시 정규식 폴백 사용

출력: parsed/DATA_015_chunks_faq.json
"""

import sys
import re
import json
import time
from collections import Counter
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from config import CHUNK_SIZE, OPENAI_API_KEY

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 설정 ─────────────────────────────────────────────────────────────────
INPUT_FILE  = Path(__file__).parent.parent.parent.parent / "data" / "DATA_015_FAQ.json"
OUTPUT_DIR  = Path(__file__).parent.parent / "parsed"
OUTPUT_FILE = OUTPUT_DIR / "DATA_015_chunks_faq.json"

DATA_ID        = "DATA-015"
DOC_TITLE      = "질병관리청 감염병포털 FAQ"
KNOWLEDGE_TYPE = "faq"
SOURCE         = "질병관리청 감염병포털 > 알림자료 > 자주찾는 질문"

AI_MODEL       = "gpt-4o-mini"
AI_BATCH_SIZE  = 10   # 한 번에 보낼 항목 수

# ── 시스템 판별 키워드 ─────────────────────────────────────────────────
_SYSTEM_KEYWORDS: set[str] = {
    '자동신고',
    '웹통계',
    '에러코드',
    '감염병코드',
    'icdgrp_cd',
    'icd_cd',
    'pthgogan_cd',
    '개발자 가이드',
    '방역통합정보시스템',
}

# ── disease_name 판별용 ────────────────────────────────────────────────
_INFLUENZA_KEYWORDS = {'인플루엔자', '독감'}
_AIDS_KEYWORDS      = {'AIDS', '후천성면역결핍'}

# ── 폴백용 STOPWORDS ──────────────────────────────────────────────────
STOPWORDS = {
    '관련', '통해', '경우', '대한', '따른', '위한', '통한', '기반',
    '따라서', '그러나', '하지만', '또한', '그리고', '이후', '이전',
    '이내', '이상', '이하', '있는', '있음', '있으며', '되어',
    '이를', '위해', '모든', '각각', '경우에', '관리', '지침',
    '개요', '현황', '절차', '정의', '목적', '대상', '범위',
    '내용', '방향', '원칙', '기본', '방법', '기준', '환자',
    '발생', '실시', '진행', '시행', '사용', '여부', '수행',
    '제공', '확인', '통보', '신고', '조치', '판단', '검토',
    '결과', '수준', '기간', '필요', '해당', '포함', '바랍니다',
    '질병관리청', '감염병', '선생님', '안내',
}


# ── 유틸 ─────────────────────────────────────────────────────────────────

def is_system_item(question: str, answer: str) -> bool:
    text = question + ' ' + answer
    return any(kw in text for kw in _SYSTEM_KEYWORDS)


def resolve_disease_name(category: str, question: str) -> str | None:
    if category == '코로나19':
        return '코로나바이러스감염증-19'
    if any(kw in question for kw in _INFLUENZA_KEYWORDS):
        return '인플루엔자'
    if any(kw in question for kw in _AIDS_KEYWORDS):
        return '후천성면역결핍증(AIDS)'
    return None


def is_garbage(text: str) -> bool:
    kor = len(re.findall(r'[가-힣]', text))
    if kor < 20:
        return True
    total = len(text.replace(' ', '').replace('\n', ''))
    if total > 0 and kor / total < 0.3:
        return True
    return False


# ── 폴백: 정규식 기반 section_title / keywords ────────────────────────

def _fallback_section_title(question: str) -> str:
    """AI 호출 실패 시 사용하는 단순 폴백."""
    title = re.sub(r'[?？\s]+$', '', question).strip()
    if len(title) > 20:
        title = title[:20].rstrip()
    return title or question[:15]


def _fallback_keywords(question: str, answer: str, max_kw: int = 10) -> list[str]:
    kor = re.findall(r'[가-힣]{2,}', question + ' ' + answer)
    eng = re.findall(r'\b[A-Z][A-Za-z]{1,}\b', question + ' ' + answer)
    freq = Counter(w for w in kor + eng if w not in STOPWORDS)
    return [w for w, _ in freq.most_common(max_kw)]


# ── AI: GPT-4o-mini 배치 생성 ────────────────────────────────────────

_AI_SYSTEM_PROMPT = """\
당신은 감염병 FAQ 데이터를 처리하는 전문가입니다.
주어진 FAQ 항목들에 대해 section_title과 keywords를 생성하세요.

규칙:
- section_title: 질문과 답변의 핵심 내용을 담은 한글 명사구로, 반드시 "에 관한 문의" 또는 "에 대한 문의"로 끝내세요.
  핵심 주제를 구체적으로 표현하되 30자 이내로 작성.
  예) "라게브리오 병용금기 약물에 관한 문의"
      "인플루엔자 예방접종 시기 및 효과에 대한 문의"
      "코로나19 먹는치료제 과량 투여 처치에 관한 문의"
      "감염병 자동신고 시스템 오류 증상에 대한 문의"
- keywords: 핵심 키워드 최대 10개 리스트 (한글 우선, 중요 영문 약어 포함 가능)
  일반적이고 반복적인 단어("환자", "감염병", "관련", "경우") 제외

중요: 입력 항목 수와 정확히 같은 수의 결과를 반환해야 합니다.
반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{"items": [
  {"section_title": "...", "keywords": ["k1", "k2", ...]},
  ...
]}
"""

def _build_ai_user_prompt(batch: list[dict]) -> str:
    lines = []
    for i, item in enumerate(batch, 1):
        q = item['question']
        a = item['answer'][:200].replace('\n', ' ')  # 답변 앞 200자만
        lines.append(f"[{i}]\nQ: {q}\nA: {a}")
    return "\n\n".join(lines)


def generate_ai_meta(items: list[dict]) -> list[dict]:
    """
    items: [{'question': ..., 'answer': ...}, ...]
    returns: [{'section_title': ..., 'keywords': [...]}, ...]
    AI 호출 실패 시 폴백값으로 채움.
    """
    try:
        from openai import OpenAI
    except ImportError:
        print("  [경고] openai 패키지 미설치 → 폴백 사용")
        return [
            {
                'section_title': _fallback_section_title(it['question']),
                'keywords':      _fallback_keywords(it['question'], it['answer']),
            }
            for it in items
        ]

    client = OpenAI(api_key=OPENAI_API_KEY)
    results: list[dict] = []
    total = len(items)

    for start in range(0, total, AI_BATCH_SIZE):
        batch = items[start:start + AI_BATCH_SIZE]
        batch_no = start // AI_BATCH_SIZE + 1
        total_batches = (total + AI_BATCH_SIZE - 1) // AI_BATCH_SIZE
        print(f"  AI 배치 {batch_no}/{total_batches} ({len(batch)}건) ...", end=' ', flush=True)

        try:
            resp = client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": _AI_SYSTEM_PROMPT},
                    {"role": "user",   "content": _build_ai_user_prompt(batch)},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content.strip()

            # response_format=json_object 는 최상위가 object여야 함
            # 모델이 {"items": [...]} 또는 {"results": [...]} 로 감쌀 수 있음
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                batch_results = parsed
            elif isinstance(parsed, dict):
                # {"items": [...]} 또는 다른 list 값
                batch_results = parsed.get('items') or next(
                    v for v in parsed.values() if isinstance(v, list)
                )
            else:
                raise ValueError(f"예상치 못한 응답 형식: {type(parsed)}")

            if len(batch_results) != len(batch):
                raise ValueError(
                    f"반환 개수 불일치: 요청 {len(batch)}건, 수신 {len(batch_results)}건"
                )

            # 필드 검증 및 정규화
            for r in batch_results:
                if not isinstance(r.get('section_title'), str):
                    r['section_title'] = ''
                if not isinstance(r.get('keywords'), list):
                    r['keywords'] = []

            results.extend(batch_results)
            print("완료")

        except Exception as e:
            print(f"실패 ({e}) → 폴백 사용")
            for it in batch:
                results.append({
                    'section_title': _fallback_section_title(it['question']),
                    'keywords':      _fallback_keywords(it['question'], it['answer']),
                })

        time.sleep(0.3)   # Rate limit 여유

    return results


# ── 메인 ─────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='샘플 출력만, JSON 저장 없음')
    parser.add_argument('--no-ai',   action='store_true', help='AI 생성 건너뛰고 정규식 폴백 사용')
    args = parser.parse_args()

    print(f"[FAQ 파서] DATA-015 시작")
    print(f"  입력: {INPUT_FILE}")
    print(f"  출력: {OUTPUT_FILE}\n")

    if not INPUT_FILE.exists():
        print(f"[오류] 파일 없음: {INPUT_FILE}")
        return

    with open(INPUT_FILE, encoding='utf-8') as f:
        raw = json.load(f)

    items = raw['items']
    print(f"  총 {len(items)}건  카테고리: {raw['categories']}\n")

    # ── 1단계: source_category / disease_name 결정 ────────────────────
    meta_list = []   # AI에 넘길 원본 Q&A
    skip_idx  = set()

    for idx, item in enumerate(items):
        answer = item['answer'].strip()
        if is_garbage(answer):
            skip_idx.add(idx)
            continue
        meta_list.append({'idx': idx, 'question': item['question'].strip(), 'answer': answer})

    # ── 2단계: AI로 section_title / keywords 생성 ─────────────────────
    use_ai = not args.no_ai and bool(OPENAI_API_KEY)
    if use_ai:
        print(f"  GPT-4o-mini로 section_title·keywords 생성 중 ({len(meta_list)}건)...")
        ai_results = generate_ai_meta(meta_list)
        print()
    else:
        print("  정규식 폴백으로 section_title·keywords 생성 중...")
        ai_results = [
            {
                'section_title': _fallback_section_title(m['question']),
                'keywords':      _fallback_keywords(m['question'], m['answer']),
            }
            for m in meta_list
        ]

    # ── 3단계: 청크 조립 ──────────────────────────────────────────────
    chunks: list[dict] = []

    for i, m in enumerate(meta_list):
        idx         = m['idx']
        item        = items[idx]
        category    = item['category']
        question_raw = m['question']
        answer       = m['answer']

        source_category = 'system' if is_system_item(question_raw, answer) else 'disease'
        disease_name    = None if source_category == 'system' \
                          else resolve_disease_name(category, question_raw)

        ai = ai_results[i]
        section_title = (ai.get('section_title') or '').strip() \
                        or _fallback_section_title(question_raw)
        keywords      = ai.get('keywords') or \
                        _fallback_keywords(question_raw, answer)

        content    = f"Q: {question_raw}\nA: {answer}"
        chunk_text = f"{category} {question_raw}\n{answer}"
        embed_text = question_raw[:500]

        if len(chunk_text) > CHUNK_SIZE * 3:
            chunk_text = f"{category} {question_raw}\n{answer[:CHUNK_SIZE * 2]}"

        chunks.append({
            'source_id':       f'faq015_{idx:04d}',
            'data_id':         DATA_ID,
            'source_category': source_category,
            'knowledge_type':  KNOWLEDGE_TYPE,
            'disease_name':    disease_name,
            'document_title':  DOC_TITLE,
            'chapter':         category,
            'section_title':   section_title,
            'content':         content,
            'chunk_text':      chunk_text,
            'embed_text':      embed_text,
            'chunk_index':     idx,
            'keywords':        keywords,
            'source':          SOURCE,
            'embedding':       None,
        })

    skipped = len(skip_idx)
    total   = len(chunks)
    sys_cks = [c for c in chunks if c['source_category'] == 'system']
    dis_cks = [c for c in chunks if c['source_category'] == 'disease']

    cat_cnts: dict[str, dict] = {}
    for c in chunks:
        cat = c['chapter']
        if cat not in cat_cnts:
            cat_cnts[cat] = {'total': 0, 'system': 0, 'disease': 0}
        cat_cnts[cat]['total']              += 1
        cat_cnts[cat][c['source_category']] += 1

    # ── 결과 요약 ─────────────────────────────────────────────────────
    print("══ 파싱 결과 ══════════════════════════════════════")
    for cat, cnt in cat_cnts.items():
        print(f"  [{cat}]  총 {cnt['total']}건  "
              f"(disease={cnt['disease']} / system={cnt['system']})")
    print(f"\n  총 {total}개 청크  (스킵: {skipped}건)")
    print(f"  disease: {len(dis_cks)}청크  /  system: {len(sys_cks)}청크")

    dn_counts: dict = {}
    for c in dis_cks:
        dn = c['disease_name'] or '(None)'
        dn_counts[dn] = dn_counts.get(dn, 0) + 1
    print("\n  disease_name 분포:")
    for dn, cnt in sorted(dn_counts.items(), key=lambda x: -x[1]):
        print(f"    {dn}: {cnt}건")

    # ── 샘플 출력 ─────────────────────────────────────────────────────
    print("\n── AI 생성 샘플 (처음 5개) ──────────────────────")
    for c in chunks[:5]:
        print(f"  [{c['source_id']}] {c['source_category']:7s} | "
              f"section_title: {c['section_title']!r}")
        print(f"    keywords : {c['keywords']}")
        print(f"    question : {c['embed_text'][:60]}")
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

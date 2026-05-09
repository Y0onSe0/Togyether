"""
05_load_diagnostic_guideline.py
본책_법정감염병 진단검사 통합지침 PDF → 감염병별 섹션 청킹 → guidelines 테이블 적재

청킹 구조:
  [제N급-N] 감염병명          ← 질병 경계 감지
      Ⅰ. 원인병원체            ← 서브섹션 1
      Ⅱ. 진단을 위한 검사기준  ← 서브섹션 2  (검색 핵심)
      Ⅲ. 참고사항              ← 서브섹션 3

DB 구조 (guidelines 테이블):
  id            : diag_에볼라바이러스병_02  (질병명_섹션번호)
  disease_name  : 에볼라바이러스병
  document_title: 본책_법정감염병 진단검사 통합지침(제4-2판)
  chapter       : 제1급 감염병
  section_title : Ⅱ. 진단을 위한 검사기준 및 검사법
  content       : 실제 내용 (LLM 컨텍스트용)
  chunk_text    : 질병명 + 섹션 + 내용 (임베딩용)
  content_type  : diagnostic
  source        : PDF 파일명

실행:
    python 05_load_diagnostic_guideline.py           ← 전체
    python 05_load_diagnostic_guideline.py --dry-run ← DB 적재 없이 청크 확인
"""

import sys
import re
import argparse
from pathlib import Path

import pdfplumber
from psycopg2.extras import execute_batch

sys.path.append(str(Path(__file__).parent))
from config import GUIDELINE_PDF_DIR, BATCH_SIZE, COMMIT_INTERVAL
from modules.embedder import embed_texts, embedding_to_pgvector
from modules.connect_db import connect_db

# ── 설정 ─────────────────────────────────────────────────────────────────
PDF_FILENAME = "1. 본책_법정감염병 진단검사 통합지침(제4-2판)_전자용_최종.pdf"
PDF_PATH     = GUIDELINE_PDF_DIR / PDF_FILENAME
DOC_TITLE    = "본책_법정감염병 진단검사 통합지침(제4-2판)"
CONTENT_TYPE = "diagnostic"

# ── 패턴 ─────────────────────────────────────────────────────────────────
# 앵커: 실제 질병 섹션에만 나타나는 패턴 (목차에는 없음)
ANCHOR_RE   = re.compile(r'Ⅰ\.\s*원인병원체')

# 서브섹션: Ⅰ. Ⅱ. Ⅲ.
SUBSECTION_RE = re.compile(r'(Ⅰ|Ⅱ|Ⅲ|Ⅳ)\.\s+[^\n]+', re.MULTILINE)

# 급수 패턴 (사이드바 노이즈 허용)
GRADE_RE = re.compile(r'제.{0,4}(\d)급')

# 급수 → 텍스트 매핑
GRADE_MAP = {'1': '제1급', '2': '제2급', '3': '제3급', '4': '제4급'}

# ── INSERT SQL ────────────────────────────────────────────────────────────
INSERT_SQL = """
INSERT INTO guidelines
    (id, disease_name, document_title, chapter, section_title,
     content, chunk_text, chunk_index, keywords, embedding, source)
VALUES
    (%s, %s, %s, %s, %s,
     %s, %s, %s, %s, %s::vector, %s)
ON CONFLICT (id) DO UPDATE SET
    content       = EXCLUDED.content,
    chunk_text    = EXCLUDED.chunk_text,
    embedding     = EXCLUDED.embedding,
    keywords      = EXCLUDED.keywords;
"""

# ── NUL 문자 제거 (PostgreSQL은 \x00 허용 안 함) ────────────────────────
def remove_nul(text: str) -> str:
    return text.replace('\x00', '')


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


# ── 사이드바 노이즈 제거 ──────────────────────────────────────────────────
# PDF 사이드바: "제\n1\n급\n감\n염\n병" 형태 → 제거
def clean_sidebar(text: str) -> str:
    # 세로 사이드바 텍스트 패턴 제거
    text = re.sub(r'제\n\d+\n급\s*\n감\n염\n병\n?', '', text)
    text = re.sub(r'부\n록\n?', '', text)
    text = re.sub(r'개\n요\n?', '', text)
    # 페이지 푸터 제거
    text = re.sub(r'www\.kdca\.go\.kr\s*_\s*\d+', '', text)
    text = re.sub(r'\d+\s*_\s*질병관리청', '', text)
    # 문서 헤더 제거
    text = re.sub(r'법정감염병 진단검사 통합지침\n', '', text)
    return text


# ── 키워드 추출 ───────────────────────────────────────────────────────────
def extract_keywords(text: str, max_kw: int = 12) -> list:
    words = re.findall(r'[가-힣]{2,}', text)
    seen, result = set(), []
    for w in words:
        if w not in seen and w not in ('감염병', '검사법', '세부', '진단'):
            seen.add(w)
            result.append(w)
        if len(result) >= max_kw:
            break
    return result


# ── 감염병별 섹션 파싱 ────────────────────────────────────────────────────
def parse_disease_sections(full_text: str) -> list[dict]:
    """
    전략:
      ① 'Ⅰ. 원인병원체' 를 앵커로 실제 질병 섹션 위치 감지 (목차 제외)
      ② 앵커 직전 200자에서 감염병명 + 급수 추출
      ③ 앵커부터 다음 앵커까지를 한 질병 블록으로 묶어 Ⅰ/Ⅱ/Ⅲ로 분할
    """
    anchor_positions = [m.start() for m in ANCHOR_RE.finditer(full_text)]

    if not anchor_positions:
        print("  [경고] Ⅰ. 원인병원체 앵커를 찾지 못했습니다.")
        return []

    diseases = []
    for i, apos in enumerate(anchor_positions):
        # ── 블록 범위 ─────────────────────────────────────────────
        block_start = apos
        block_end   = anchor_positions[i + 1] if i + 1 < len(anchor_positions) else len(full_text)
        block       = full_text[block_start:block_end]
        block       = clean_sidebar(block)

        # ── 감염병명·급수 추출 (앵커 직전 300자) ──────────────────
        prefix     = clean_sidebar(full_text[max(0, apos - 300): apos])
        # 한글 질병명: 영문명 직전 줄, 또는 마지막 한글 덩어리
        lines      = [ln.strip() for ln in prefix.splitlines() if ln.strip()]
        # 마지막 한글 줄을 감염병명으로
        disease_name = ''
        for ln in reversed(lines):
            if re.search(r'[가-힣]{2,}', ln) and not re.search(r'\d{2,}', ln):
                # 숫자(페이지번호) 없고 한글 있는 줄
                candidate = re.sub(r'[A-Za-z].*$', '', ln).strip()  # 영문 이후 제거
                if len(candidate) >= 2:
                    disease_name = candidate
                    break

        # 급수 추출
        grade_num    = '1'
        grade_match  = GRADE_RE.search(prefix)
        if grade_match:
            grade_num = grade_match.group(1)
        grade = GRADE_MAP.get(grade_num, f'제{grade_num}급')

        if not disease_name:
            continue   # 질병명 못 찾으면 스킵

        # ── 서브섹션 분할 (Ⅰ Ⅱ Ⅲ) ───────────────────────────────
        sub_pos = [(m.start(), m.group(0)) for m in SUBSECTION_RE.finditer(block)]

        sections = []
        if not sub_pos:
            sections.append({'title': '전체', 'content': block.strip()})
        else:
            for j, (spos, stitle) in enumerate(sub_pos):
                send    = sub_pos[j + 1][0] if j + 1 < len(sub_pos) else len(block)
                content = block[spos:send].strip()
                if content:
                    sections.append({'title': stitle.strip(), 'content': content})

        diseases.append({
            'disease_name': disease_name,
            'grade':        grade,
            'chapter':      f"{grade} 감염병",
            'sections':     sections,
        })

    return diseases


# ── 청크 생성 ─────────────────────────────────────────────────────────────
def build_chunks(diseases: list[dict]) -> list[dict]:
    chunks = []
    for disease in diseases:
        dname   = disease['disease_name']
        chapter = disease['chapter']

        for sec_idx, sec in enumerate(disease['sections']):
            sec_title = remove_nul(sec['title'])
            content   = remove_nul(sec['content'])

            if not content.strip() or len(content) < 30:
                continue

            # ID: 한글 안전하게 처리
            safe_name = re.sub(r'[^\w가-힣]', '', dname)[:20]
            chunk_id  = f"diag_{safe_name}_{sec_idx:02d}"

            # 임베딩용 텍스트 (컨텍스트 풍부하게)
            chunk_text = (
                f"{DOC_TITLE} {chapter} {dname} {sec_title}\n{content}"
            )

            chunks.append({
                'id':             chunk_id,
                'disease_name':   remove_nul(dname),
                'document_title': DOC_TITLE,
                'chapter':        remove_nul(chapter),
                'section_title':  sec_title,
                'content':        content,
                'chunk_text':     chunk_text,
                'chunk_index':    sec_idx,
                'keywords':       extract_keywords(f"{dname} {content}"),
                'source':         PDF_FILENAME,
            })

    return chunks


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true',
                        help='청크 확인만, DB 적재 없음')
    args = parser.parse_args()

    print(f"[진단검사지침] PDF 파싱 시작")
    print(f"  파일: {PDF_FILENAME}\n")

    # ── 1. 텍스트 추출 ───────────────────────────────────────────────────
    print("[1단계] PDF 텍스트 추출 중...")
    full_text = extract_full_text(PDF_PATH)
    print(f"  추출 완료: {len(full_text):,}자\n")

    # ── 2. 질병별 섹션 파싱 ─────────────────────────────────────────────
    print("[2단계] 감염병별 섹션 파싱 중...")
    diseases = parse_disease_sections(full_text)
    print(f"  감염병 {len(diseases)}종 감지\n")

    # ── 3. 청크 생성 ─────────────────────────────────────────────────────
    chunks = build_chunks(diseases)
    print(f"[3단계] 청크 생성 완료: {len(chunks)}개\n")

    # dry-run: 샘플 출력
    if args.dry_run or True:
        print("── 샘플 청크 (처음 10개) ─────────────────")
        for c in chunks[:10]:
            print(f"  ID           : {c['id']}")
            print(f"  disease_name : {c['disease_name']}")
            print(f"  chapter      : {c['chapter']}")
            print(f"  section_title: {c['section_title']}")
            print(f"  content 길이 : {len(c['content'])}자")
            print(f"  keywords     : {c['keywords'][:5]}")
            print()

    if args.dry_run:
        print("[dry-run] DB 적재 건너뜀")
        return

    # ── 4. 임베딩 생성 ───────────────────────────────────────────────────
    print("[4단계] 임베딩 생성 중...")
    texts      = [c['chunk_text'] for c in chunks]
    embeddings = embed_texts(texts, prefix='passage')

    rows = []
    for chunk, emb in zip(chunks, embeddings):
        rows.append((
            chunk['id'],
            chunk['disease_name'],
            chunk['document_title'],
            chunk['chapter'],
            chunk['section_title'],
            chunk['content'],
            chunk['chunk_text'],
            chunk['chunk_index'],
            chunk['keywords'],
            embedding_to_pgvector(emb),
            chunk['source'],
        ))

    # ── 5. DB 적재 ───────────────────────────────────────────────────────
    print("\n[5단계] DB 적재 중...")
    conn   = connect_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM guidelines WHERE source = %s", (PDF_FILENAME,))
    print(f"  기존 청크 삭제 완료")

    total, done = len(rows), 0
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i: i + BATCH_SIZE]
        execute_batch(cursor, INSERT_SQL, batch, page_size=BATCH_SIZE)
        done += len(batch)
        if done % COMMIT_INTERVAL == 0 or done == total:
            conn.commit()
            print(f"  적재 중... {done}/{total}")

    cursor.close()
    conn.close()
    print(f"\n✓ guidelines 테이블에 {total}개 청크 적재 완료")
    print(f"  content_type = '{CONTENT_TYPE}'")
    print(f"  감염병 {len(diseases)}종 × 평균 {total//max(len(diseases),1)}개 섹션")


if __name__ == '__main__':
    main()

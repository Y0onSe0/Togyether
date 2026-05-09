"""
04_load_guidelines.py
감염병 관리지침 PDF → 단락 청킹 → 임베딩 → guidelines 테이블 적재

청킹 전략:
  1. \n\n 기준 1차 단락 분리
  2. 섹션 헤더 패턴(제N장, 1., 가. 등) 감지 → 추가 분리
  3. 너무 짧은 단락(<80자) → 인접 단락과 합치기
  4. 너무 긴 단락(>800자) → 문장 경계(다./요. 등)에서 추가 분할

실행:
    python 04_load_guidelines.py             ← 전체 PDF 처리
    python 04_load_guidelines.py --limit 2   ← PDF 2개만 (테스트)
    python 04_load_guidelines.py --dry-run   ← DB 적재 없이 청크 수만 확인
"""

import sys
import re
import argparse
from pathlib import Path

import pdfplumber
from psycopg2.extras import execute_batch

sys.path.append(str(Path(__file__).parent))
from config import (
    GUIDELINE_PDF_DIR, CHUNK_SIZE,
    BATCH_SIZE, COMMIT_INTERVAL,
)
from modules.embedder import embed_texts, embedding_to_pgvector
from modules.connect_db import connect_db


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


# ── 파일명에서 감염병명 추출 ──────────────────────────────────────────────
def extract_disease_name(filename: str) -> str:
    name = Path(filename).stem

    # 앞부분 노이즈 제거
    name = re.sub(r'^\+\+',        '', name)  # ++ 접두어
    name = re.sub(r'^\d+\.\s*',    '', name)  # 1. 2. 숫자 목차
    name = re.sub(r'^\d+_',        '', name)  # 1_ 접두어
    name = re.sub(r'^본책_|^별책_', '', name)

    # 연도 패턴 제거
    name = re.sub(r'\d{4}년도?\s*', '', name)
    name = re.sub(r'^\d{4}\s+',     '', name)

    # 등급 감염병 접두어 제거
    name = re.sub(r'제\d+급감염병\s*', '', name)

    # 뒤쪽 노이즈 제거 (지침명 이후)
    for suffix in ['관리지침', '대응지침', '사용자 이용설명서', '사용자이용설명서',
                   '임상진료지침', '집단감염 대응지침', '진단검사 통합지침']:
        idx = name.find(suffix)
        if idx > 0:
            name = name[:idx]
            break

    # 괄호, 특수문자 정리
    name = re.sub(r'\(.*?\)', '', name)
    name = name.replace('_', ' ').strip()

    return name if name.strip() else Path(filename).stem


# ── PDF 텍스트 추출 ───────────────────────────────────────────────────────
def extract_pdf_text(pdf_path: Path) -> str:
    """페이지별 텍스트 추출. 페이지 사이는 \n\n으로 구분."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                # NUL 문자 제거 (PostgreSQL은 \x00 허용 안 함)
                pages.append(text.strip().replace('\x00', ''))
    return "\n\n".join(pages)


# ── 섹션 헤더 판별 ────────────────────────────────────────────────────────
_HEADER_RE = re.compile(
    r'^('
    r'제\s*\d+\s*[장절조편]'           # 제1장 제2절 제3조
    r'|\d{1,2}\.\s+\S'                  # 1. 제목  2. 내용
    r'|[가나다라마바사아자차카타파하]\.\s'  # 가. 나.
    r'|[①②③④⑤⑥⑦⑧⑨⑩]\s'            # ① ②
    r'|[○●▶■□▷◆]\s'                  # 불릿
    r')'
)

def _is_header(line: str) -> bool:
    return bool(_HEADER_RE.match(line.strip()))


# ── 1단계: 단락 분리 ─────────────────────────────────────────────────────
def _split_paragraphs(text: str) -> list[str]:
    """
    \n\n 기준 1차 분리 후,
    각 블록 안에서 헤더 패턴이 나오면 추가 분리.
    """
    raw_blocks = re.split(r'\n{2,}', text)
    paragraphs = []

    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue

        lines   = block.split('\n')
        current = []

        for line in lines:
            if current and _is_header(line):
                # 헤더 만나면 이전 블록 확정
                paragraphs.append(' '.join(current))
                current = [line]
            else:
                current.append(line)

        if current:
            paragraphs.append(' '.join(current))

    return [p.strip() for p in paragraphs if p.strip()]


# ── 2단계: 길이 정제 ─────────────────────────────────────────────────────
_SENT_END_RE = re.compile(r'(?<=[다요함됨임])\.\s+')   # 문장 끝 패턴

def _refine(paragraphs: list[str],
            max_size: int = CHUNK_SIZE,
            min_size: int = 80) -> list[str]:
    """
    짧은 단락 → 합치기 / 긴 단락 → 문장 단위 추가 분할
    """
    # 짧은 단락 합치기
    merged, buf = [], ''
    for para in paragraphs:
        if not buf:
            buf = para
        elif len(buf) + len(para) + 1 <= min_size * 3:
            buf = buf + ' ' + para
        else:
            merged.append(buf)
            buf = para
    if buf:
        merged.append(buf)

    # 긴 단락 분할
    result = []
    for para in merged:
        if len(para) <= max_size:
            result.append(para)
            continue

        # 문장 경계에서 분할
        sentences = _SENT_END_RE.split(para)
        chunk = ''
        for sent in sentences:
            if len(chunk) + len(sent) + 1 <= max_size:
                chunk = (chunk + ' ' + sent).strip()
            else:
                if chunk:
                    result.append(chunk)
                # 문장 자체가 max_size 초과 → 강제로 자르기
                if len(sent) > max_size:
                    for i in range(0, len(sent), max_size):
                        result.append(sent[i:i + max_size].strip())
                    chunk = ''
                else:
                    chunk = sent
        if chunk:
            result.append(chunk)

    return [r for r in result if r.strip()]


# ── 단락 청킹 통합 함수 ───────────────────────────────────────────────────
def make_chunks(text: str) -> list[str]:
    paragraphs = _split_paragraphs(text)
    return _refine(paragraphs)


# ── 청크에서 키워드 추출 ──────────────────────────────────────────────────
def extract_keywords(text: str, max_kw: int = 10) -> list[str]:
    words = re.findall(r'[가-힣A-Z]{2,}', text)
    seen, result = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            result.append(w)
        if len(result) >= max_kw:
            break
    return result


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit',   type=int, default=None,
                        help='처리할 PDF 파일 수 제한 (테스트용)')
    parser.add_argument('--dry-run', action='store_true',
                        help='청크 수만 확인하고 DB 적재는 건너뜀')
    args = parser.parse_args()

    pdf_files = sorted(GUIDELINE_PDF_DIR.glob('*.pdf'))
    if not pdf_files:
        print(f'[오류] PDF 파일 없음: {GUIDELINE_PDF_DIR}')
        return

    if args.limit:
        pdf_files = pdf_files[:args.limit]

    print(f'[가이드라인] PDF {len(pdf_files)}개 처리 시작')
    print(f'  최대 청크 크기: {CHUNK_SIZE}자 / 최소 단락 크기: 80자\n')

    # ── 1. PDF 파싱 + 청킹 ───────────────────────────────────────────────
    all_chunks = []

    for file_idx, pdf_path in enumerate(pdf_files, start=1):
        print(f'  [{file_idx:02d}/{len(pdf_files)}] {pdf_path.name}')

        try:
            raw_text = extract_pdf_text(pdf_path)
        except Exception as e:
            print(f'    ✗ 텍스트 추출 실패: {e}')
            continue

        if not raw_text.strip():
            print(f'    ✗ 텍스트 없음, 스킵')
            continue

        chunks        = make_chunks(raw_text)
        disease_name  = extract_disease_name(pdf_path.name)
        doc_title     = pdf_path.stem

        print(f'    → {len(raw_text):,}자 / {len(chunks)}청크 / 감염병: {disease_name}')

        for chunk_idx, content in enumerate(chunks):
            chunk_id         = f'guideline_{file_idx:03d}_chunk_{chunk_idx:04d}'
            chunk_text_embed = f'{doc_title} {content}'   # 임베딩용 (제목+본문)
            keywords         = extract_keywords(content)

            all_chunks.append({
                'id':             chunk_id,
                'disease_name':   disease_name,
                'document_title': doc_title,
                'chapter':        None,
                'section_title':  None,
                'content':        content,
                'chunk_text':     chunk_text_embed,
                'chunk_index':    chunk_idx,
                'keywords':       keywords,
                'source':         pdf_path.name,
            })

    total = len(all_chunks)
    print(f'\n[청킹 완료] 총 {total}개 청크')

    if args.dry_run:
        print('[dry-run] DB 적재 건너뜀')
        return

    # ── 2. 임베딩 생성 ───────────────────────────────────────────────────
    print('\n[임베딩] 생성 중...')
    texts      = [c['chunk_text'] for c in all_chunks]
    embeddings = embed_texts(texts, prefix='passage')

    rows = []
    for chunk, emb in zip(all_chunks, embeddings):
        rows.append((
            chunk['id'],
            chunk['disease_name'],
            chunk['document_title'],
            chunk['chapter'],
            chunk['section_title'],
            chunk['content'],
            chunk['chunk_text'],
            chunk['chunk_index'],
            chunk['keywords'],            # TEXT[] — psycopg2가 리스트 → 배열 변환
            embedding_to_pgvector(emb),   # vector 문자열
            chunk['source'],
        ))

    # ── 3. DB 적재 ───────────────────────────────────────────────────────
    print('\n[DB] 적재 중...')
    conn   = connect_db()
    cursor = conn.cursor()

    # 재실행 대비: 같은 source 파일의 기존 청크 삭제
    sources = list({c['source'] for c in all_chunks})
    cursor.execute('DELETE FROM guidelines WHERE source = ANY(%s)', (sources,))
    print(f'  기존 청크 삭제 (source {len(sources)}개 파일)')

    done = 0
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        execute_batch(cursor, INSERT_SQL, batch, page_size=BATCH_SIZE)
        done += len(batch)

        if done % COMMIT_INTERVAL == 0 or done == total:
            conn.commit()
            print(f'  적재 중... {done}/{total}')

    cursor.close()
    conn.close()
    print(f'\n✓ guidelines 테이블에 {total}개 청크 적재 완료')


if __name__ == '__main__':
    main()

# Knowledge Chunks 전처리 설계 명세

## 1. 개요

`knowledge_chunks` 테이블에 적재되는 데이터는 RAG(Retrieval-Augmented Generation) 파이프라인에서 사용된다.
각 필드는 **검색 단계**와 **생성 단계**의 역할이 명확히 분리되어 있으며,
향후 BM25 + 벡터 검색 하이브리드(RRF) 확장을 고려한 구조로 설계되었다.

---

## 2. RAG 파이프라인 전체 흐름

```
사용자 질문
    │
    ├──► embed_text 임베딩 → pgvector 유사도 검색 ──┐
    │                                                 │
    └──► chunk_text BM25 키워드 검색 ────────────────┤
                                                      ▼
                                             RRF (Reciprocal Rank Fusion)
                                             두 랭킹 합산 → 상위 K개 선택
                                                      │
                                                      ▼
                                    content (상위 3개) → LLM 프롬프트 삽입
                                                      │
                                                      ▼
                                                  최종 답변
```

---

## 3. 필드별 설계 의도

### 3-1. `embed_text` — 벡터 검색용

```python
embed_text = f"{disease_name} {section_title}: {content}"  # 500자 이내
```

**왜 이렇게 했나:**
- pgvector 유사도 검색의 입력값. 이 텍스트를 임베딩 모델에 넣어 `embedding` 벡터를 생성한다.
- 텍스트가 길수록 임베딩 품질이 분산되므로 **500자 이내**로 제한한다.
- `disease_name`과 `section_title`을 앞에 붙이는 이유: 임베딩 모델이 "이 청크가 어떤 질병의 어떤 섹션인가"를 벡터 공간에 반영하게 하기 위함. 본문만 있으면 질병명 없이 비슷한 내용이 다른 질병 청크와 혼동될 수 있다.

---

### 3-2. `chunk_text` — BM25 검색 + LLM 컨텍스트용

```python
chunk_text = f"{chapter} {disease_name} {section_title}\n{content}"
```

**왜 이렇게 했나:**

**BM25 관점:**
- BM25는 `chunk_text` 전체를 색인하여 쿼리 키워드의 TF-IDF 점수로 랭킹을 매긴다.
- 사용자가 "결핵 진단기준"으로 검색하면 `chunk_text`에 "결핵", "진단기준"이 직접 있어야 점수가 높아진다.
- `chapter`(제2급 감염병), `disease_name`(결핵), `section_title`(Ⅱ. 진단기준)을 명시적으로 포함시켜 키워드 매칭 범위를 넓힌다.
- 초기 설계에서 `document_title`(문서 제목 전체)을 포함했으나 모든 청크에 동일하게 반복되어 BM25 변별력이 없으므로 제외했다.

**LLM 컨텍스트 관점:**
- 검색으로 선택된 상위 3개 청크의 `chunk_text`가 LLM 프롬프트에 삽입된다.
- LLM이 "이 내용이 어떤 질병의 어떤 섹션인지" 알 수 있도록 헤더(`chapter disease_name section_title`)를 포함한다.
- 헤더가 없으면 LLM이 문맥 없이 본문만 보게 되어 답변 품질이 떨어진다.

---

### 3-3. `content` — 정제된 원본 본문

```python
content = clean_content(raw_content)  # 사이드바 노이즈 제거 + 공백 정리
```

**왜 이렇게 했나:**
- DB에 저장되는 원본 텍스트. `chunk_text`와 `embed_text` 생성의 기반이 된다.
- PDF 다단 레이아웃에서 발생하는 사이드바 잔여물("제\n1\n급\n감\n염\n병" 등)을 정규식으로 제거한다.
- 페이지 번호, 헤더/푸터(`www.kdca.go.kr`) 등 의미 없는 텍스트도 제거한다.

---

### 3-4. `keywords` — 프론트 태그 + 사전 필터링용

```python
keywords = extract_keywords(f"{disease_name} {section_title} {content}", max_kw=10)
# Counter 빈도 기반: 한글 2자 이상 단어 + 대문자 영문 약어, STOPWORDS 제거
```

**왜 이렇게 했나:**
- BM25는 `chunk_text` 전체를 직접 색인하므로 `keywords` 필드가 BM25 검색 자체에 영향을 주지 않는다.
- 용도:
  1. **프론트엔드 태그 표시**: 검색 결과 카드에 "관련 키워드: 결핵, PCR, 진단기준" 형태로 표시
  2. **사전 필터링**: BM25/벡터 검색 전에 특정 키워드 태그가 있는 청크만 추리는 pre-filter로 활용 가능
- 첫 N개 단어를 순서대로 뽑는 방식(이전 방식)은 "속하며", "지질로"처럼 의미 없는 단어가 포함되어 빈도 기반 Counter 방식으로 변경했다.
- STOPWORDS로 "환자", "발생", "관리" 등 모든 문서에 반복 등장하는 단어를 제거해 구별력 있는 키워드만 남긴다.

---

### 3-5. `disease_name` — 공식 법정감염병 명칭

```python
disease_name = resolve_disease_name(raw_name)  # 130종 공식 명칭으로 정규화
```

**왜 이렇게 했나:**
- 원본 PDF/JSON에서 파싱 오류로 disease_name 자리에 "참고사항", "질병관리청 세균분석과에 의뢰할 수 있음" 등 엉뚱한 텍스트가 들어오는 경우가 있다.
- 법정감염병 130종 공식 명칭 목록(`CANONICAL_DISEASES`)을 정의하고, 정규화 매핑으로 일치시킨다.
- 매핑 실패(공식 명칭과 일치하지 않는) 청크는 **전부 제외**한다.
- 이를 통해 DB의 `disease_name` 컬럼이 일관된 값을 가지게 되어, 프론트의 질병별 필터링과 백엔드의 메타데이터 검색이 정확하게 동작한다.

---

### 3-6. `embedding` — 벡터 (적재 시 생성)

```python
embedding = None  # 파서 단계에서는 None, 02_generate_embeddings.py 에서 채움
```

**왜 이렇게 했나:**
- 임베딩 생성은 OpenAI API 호출이 필요하므로 파싱 단계와 분리한다.
- 파서는 JSON 파일만 생성하고, `02_generate_embeddings.py`가 `embed_text`를 읽어 OpenAI API를 호출한 후 벡터를 채워 DB에 적재한다.

---

## 4. 가비지 필터

```python
def is_garbage_chunk(content: str) -> bool:
    kor_chars = len(re.findall(r'[가-힣]', content))
    if kor_chars < 30:          # 한글 30자 미만
        return True
    total = len(content.replace(' ', '').replace('\n', ''))
    if kor_chars / total < 0.4: # 한글 비율 40% 미만
        return True
    return False
```

**왜 이렇게 했나:**
- PDF 파싱 결과 목차, 서식 잔여물, 표 셀 단편 등이 청크로 들어오는 경우가 있다.
- 한글 30자 미만: 실질적인 문장이 없는 파편 청크 제거
- 한글 비율 40% 미만: 영문/숫자/기호만 가득한 표/코드 청크 제거 (한국어 문서이므로 한글이 주가 되어야 함)

---

## 5. 공통 DB 필드 매핑

| 필드 | 내용 | 비고 |
|---|---|---|
| `source_id` | 원본 파일/JSON 내 고유 ID | 원본 추적용 |
| `data_id` | DATA-001 ~ DATA-00N | 데이터 소스 구분 |
| `source_category` | `disease` | 현재 모든 소스 동일 |
| `knowledge_type` | `disease_guideline` | 소스 유형 구분 |
| `disease_name` | 공식 법정감염병 명칭 | 130종 정규화 |
| `document_title` | 원본 문서 제목 | 출처 표시용 |
| `chapter` | 급수 또는 장 번호 | 제1급/제2급/... |
| `section_title` | 섹션 제목 | Ⅰ.개요 / Ⅱ.진단기준 |
| `content` | 정제된 본문 | 노이즈 제거 완료 |
| `chunk_text` | BM25 색인 + LLM 컨텍스트 | chapter+disease+section+content |
| `embed_text` | 벡터 임베딩 입력 | 500자 이내 |
| `chunk_index` | 청크 순번 | 같은 질병 내 순서 |
| `keywords` | 빈도 기반 키워드 10개 | 프론트 태그용 |
| `source` | 원본 파일명 또는 URL | 출처 |
| `embedding` | VECTOR(1536) | 적재 시 생성 |

---

## 6. 향후 확장 고려사항

### BM25 + Vector 하이브리드 (RRF)

현재는 벡터 검색만 구현되어 있으나, BM25를 추가하면:
- `chunk_text`를 BM25 엔진(Elasticsearch, PostgreSQL FTS 등)에 색인
- 벡터 검색 랭킹 + BM25 랭킹을 RRF로 합산
- `keywords` 필드를 BM25 부스팅 필드로 활용 가능

현재 `chunk_text` 형식(`chapter disease_name section_title\ncontent`)은 이 확장을 고려해 설계되었다.

### Re-ranking

RRF 이후 Cross-Encoder 모델로 상위 K개를 재랭킹하는 단계를 추가할 수 있다.
이 경우에도 `chunk_text`의 구조화된 형식이 유리하다.

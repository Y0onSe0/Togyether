# 전처리 명세서 v1.0
## 질병관리청 1339 콜센터 AI 지원 시스템 — knowledge_chunks 적재용

> 작성일: 2026-05-06
> 대상 테이블: `knowledge_chunks`
> 참조: DB 설계서 v2.0 · 기능명세서 v3.0

---

## 목차

1. [데이터 소스 매핑 개요](#1-데이터-소스-매핑-개요)
2. [공통 출력 포맷 (chunks_data JSON 스키마)](#2-공통-출력-포맷)
3. [DATA-001~007 | 감염병 관리지침 PDF (parsed)](#3-data-001007--감염병-관리지침-pdf)
4. [DATA-008 | 감염병 FAQ](#4-data-008--감염병-faq)
5. [DATA-009 | 감염병 크롤링](#5-data-009--감염병-크롤링)
6. [DATA-010~014 | 시스템 매뉴얼 (system_merged)](#6-data-010014--시스템-매뉴얼)
7. [DATA-015 | 시스템 FAQ](#7-data-015--시스템-faq)
8. [공통 품질 기준 및 필터링 규칙](#8-공통-품질-기준-및-필터링-규칙)
9. [출력 파일 목록 및 경로](#9-출력-파일-목록-및-경로)

---

## 1. 데이터 소스 매핑 개요

| # | DATA ID | 설명 | 입력 파일 | 전처리 단계 | 출력 파일 |
|---|---------|------|-----------|------------|-----------|
| 1 | DATA-001~007 | 감염병 관리지침 PDF (파싱 완료) | `db/scripts/parsed/DATA_00N_chunks_*.json` × 7 | 3단계 | `chunks_data001~007.json` |
| 2 | DATA-008 | 감염병 FAQ (공개 Q&A) | `data/DATA_008_FAQ.json` | 4단계 | `chunks_data008.json` |
| 3 | DATA-009 | 감염병 크롤링 (질병별 정보) | `data/DATA_009_감염병_크롤링.json` | 4단계 | `chunks_data009.json` |
| 4 | DATA-010~014 | 시스템 매뉴얼 (결핵 시스템) | `data/DATA_010_014_system_merged.json` | 3단계 | `chunks_data010~014.json` |
| 5 | DATA-015 | 시스템 FAQ (감염병 포털 Q&A) | `data/DATA_015_FAQ.json` | 4단계 | `chunks_data015.json` |

**knowledge_type / source_category 매핑**

| DATA ID | knowledge_type | source_category |
|---------|----------------|-----------------|
| DATA-001~007 | `disease_guideline` | `disease` |
| DATA-008 | `faq` | `disease` |
| DATA-009 | `disease_info` | `disease` |
| DATA-010~014 | `system_manual` | `system` |
| DATA-015 | `faq` | `system` |

---

## 2. 공통 출력 포맷

### 2.1 chunks_data JSON 스키마

각 전처리 결과는 아래 JSON 배열 형태로 저장된다.
`embedding` 필드는 전처리 단계에서 `null`로 두고, 이후 임베딩 적재 스크립트에서 채운다.

```json
[
  {
    "source_id":       "covid_0042",
    "data_id":         "DATA-001",
    "source_category": "disease",
    "knowledge_type":  "disease_guideline",
    "disease_name":    "코로나19",
    "document_title":  "2025년도 코로나19 관리지침",
    "chapter":         "PART I. 개요",
    "section_title":   "가. 격리 기간",
    "content":         "확진자 격리 기간은 증상 발생일로부터 5일...",
    "chunk_text":      "[코로나19 관리지침] PART I. 개요 > 가. 격리 기간\n확진자 격리 기간은 증상 발생일로부터 5일...",
    "embed_text":      "코로나19 격리 기간 확진자 격리 기간은 증상 발생일로부터 5일",
    "chunk_index":     42,
    "keywords":        ["격리", "확진자", "5일"],
    "source":          "++2025년도 코로나19 관리지침_최종-전자용.pdf",
    "embedding":       null
  }
]
```

### 2.2 필드 정의

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `source_id` | string | ✅ | 원본 파일의 id 값 (파싱 결과의 `id` 또는 구성한 고유키) |
| `data_id` | string | ✅ | `'DATA-001'` ~ `'DATA-015'` |
| `source_category` | string | ✅ | `'disease'` \| `'system'` |
| `knowledge_type` | string | ✅ | `'disease_guideline'` \| `'disease_info'` \| `'faq'` \| `'system_manual'` |
| `disease_name` | string\|null | — | 질병명 (감염병 관련만) |
| `document_title` | string\|null | — | 원본 문서 제목 |
| `chapter` | string\|null | — | 장/편 (없으면 null) |
| `section_title` | string\|null | — | 소제목 |
| `content` | string\|null | — | 원본 텍스트 (정제 전) |
| `chunk_text` | string | ✅ | GPT에 전달할 전체 텍스트 (컨텍스트 헤더 포함) |
| `embed_text` | string | ✅ | 실제 임베딩 대상 텍스트 (핵심만) |
| `chunk_index` | int | ✅ | 소스 내 순서 (0-based) |
| `keywords` | list\[str\] | ✅ | 키워드 배열 (없으면 `[]`) |
| `source` | string\|null | — | 원본 파일명 또는 URL |
| `embedding` | null | — | 전처리 시 null, 임베딩 스크립트에서 채움 |

### 2.3 chunk_text vs embed_text 원칙

| 필드 | 목적 | 포함 내용 |
|------|------|-----------|
| `chunk_text` | GPT에 RAG 컨텍스트로 전달 | `[출처 헤더]\n본문 전체` — 문서 위치 정보 포함, 완전한 문장 |
| `embed_text` | 벡터 검색 정확도 | 핵심 의미 텍스트만 — 불필요한 헤더·기호·OCR 노이즈 제거, 500자 이내 권장 |

---

## 3. DATA-001~007 | 감염병 관리지침 PDF

### 3.0 입력 파일 구조

```
db/scripts/parsed/
├── DATA_001_chunks_covid.json       → DATA-001  코로나19
├── DATA_002_chunks_diagnostic.json  → DATA-002  진단검사 통합지침
├── DATA_003_chunks_dupest.json      → DATA-003  원인불명 집단감염 대응지침
├── DATA_004_chunks_hiv.json         → DATA-004  HIV/AIDS
├── DATA_005_chunks_mers.json        → DATA-005  MERS/SARS
├── DATA_006_chunks_tb.json          → DATA-006  결핵
└── DATA_007_chunks_vhf.json         → DATA-007  바이러스성출혈열
```

**입력 레코드 필드**: `id, disease_name, document_title, chapter, section_title, content, chunk_text, chunk_index, keywords, source, content_type`

**실측 문제점**
- OCR 노이즈: 한글 자소 분리 (`코 로 나 19`), 특수문자 (`ㆍ`, `·····`, `|`, `=`, `a=)`), 영문 OCR 오인식 (`KIO`, `Bora`, `AVE`)
- 목차 페이지 청크: `content`가 `ㆍ 37\nㆍ 40\n...` 형식의 페이지 번호만 있음
- `chapter = "전체"` : 일부 파일(covid)에서 챕터 미분류
- `section_title = ""` : 빈 소제목 다수
- `embed_text` 미존재: DB 적재 시 별도 생성 필요

### 3.1 전처리 단계

#### STEP 1 — 품질 필터링 (저품질 청크 제거)

제거 기준 (아래 중 하나라도 해당하면 제거):

| 조건 | 판단 기준 |
|------|-----------|
| 내용이 너무 짧음 | `content` 한글 기준 유효 글자 수 < 30자 |
| 목차/페이지 번호만 | `content`가 `·····`, `ㆍ N`, 페이지 번호 패턴만으로 구성 |
| OCR 불량 (영어 비율 과다) | 전체 길이 대비 비한글·비한자 문자 비율 > 60% |
| 빈 section_title + 빈 content | 둘 다 공백인 경우 |

```python
# 판단 예시
def is_garbage_chunk(chunk: dict) -> bool:
    content = chunk.get("content", "").strip()
    korean_chars = len(re.findall(r'[가-힣]', content))
    total_chars  = len(content.replace(" ", "").replace("\n", ""))
    
    if korean_chars < 30:
        return True
    if total_chars > 0 and korean_chars / total_chars < 0.4:
        return True
    # 페이지 번호 패턴: "ㆍ 37\nㆍ 40\n..."
    if re.match(r'^[\s\nㆍ·\d]+$', content):
        return True
    return False
```

#### STEP 2 — OCR 노이즈 클리닝

`content` 및 `chunk_text` 적용:

| 노이즈 유형 | 예시 | 처리 방법 |
|-------------|------|-----------|
| 한글 자소 사이 공백 | `코 로 나 19` | 한글 단어 내 공백 제거 (정규식: `(?<=[가-힣]) (?=[가-힣])`) |
| 목차 점선 | `검진사업·····262` | `[가-힣a-zA-Z\s]+[·.]{5,}\d+` 패턴 제거 |
| 영문 OCR 오인식 단어 | `KIO`, `Bora`, `AVE`, `a=)`, `eens` | 독립 단어로 존재하는 2~5글자 영문 + 전후 한글 없는 경우 제거 |
| 반복 특수문자 | `\|\n=\n`, `ㆍ`, `◾` | `\n`으로 대체 또는 제거 |
| 과도한 줄바꿈 | `\n\n\n` 이상 | `\n\n`으로 정규화 |

```python
import re

def clean_ocr_noise(text: str) -> str:
    # 1. 한글 자소 사이 공백 제거
    text = re.sub(r'(?<=[가-힣]) (?=[가-힣])', '', text)
    # 2. 목차 점선 제거
    text = re.sub(r'[가-힣a-zA-Z\s]+[·.]{5,}\d+', '', text)
    # 3. 반복 특수문자 정리
    text = re.sub(r'[ㆍ◾▢]\s*', '\n', text)
    text = re.sub(r'[|=]{1,}\s*\n', '', text)
    # 4. 과도한 줄바꿈 정규화
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
```

#### STEP 3 — DB 필드 매핑 및 embed_text 생성

```python
# DATA_ID 매핑 (파일명 기반)
DATA_ID_MAP = {
    "DATA_001_chunks_covid.json":       "DATA-001",
    "DATA_002_chunks_diagnostic.json":  "DATA-002",
    "DATA_003_chunks_dupest.json":      "DATA-003",
    "DATA_004_chunks_hiv.json":         "DATA-004",
    "DATA_005_chunks_mers.json":        "DATA-005",
    "DATA_006_chunks_tb.json":          "DATA-006",
    "DATA_007_chunks_vhf.json":         "DATA-007",
}

def build_chunk_text(row: dict) -> str:
    """GPT 컨텍스트 헤더 포함 텍스트"""
    parts = [f"[{row['document_title']}]"]
    if row.get("chapter") and row["chapter"] != "전체":
        parts.append(row["chapter"])
    if row.get("section_title"):
        parts.append(row["section_title"])
    header = " > ".join(parts)
    return f"{header}\n{row['content_clean']}"

def build_embed_text(row: dict) -> str:
    """임베딩용 핵심 텍스트 (500자 이내)"""
    parts = []
    if row.get("disease_name"):
        parts.append(row["disease_name"])
    if row.get("section_title"):
        parts.append(row["section_title"])
    parts.append(row["content_clean"])
    text = " ".join(parts)
    return text[:500]

def map_to_db(row: dict, data_id: str) -> dict:
    content_clean = clean_ocr_noise(row["content"])
    return {
        "source_id":       row["id"],
        "data_id":         data_id,
        "source_category": "disease",
        "knowledge_type":  "disease_guideline",
        "disease_name":    row.get("disease_name"),
        "document_title":  row.get("document_title"),
        "chapter":         row.get("chapter") if row.get("chapter") != "전체" else None,
        "section_title":   row.get("section_title") or None,
        "content":         row["content"],                  # 원본 보존
        "chunk_text":      build_chunk_text({**row, "content_clean": content_clean}),
        "embed_text":      build_embed_text({**row, "content_clean": content_clean}),
        "chunk_index":     row["chunk_index"],
        "keywords":        row.get("keywords", []),
        "source":          row.get("source"),
        "embedding":       None,
    }
```

### 3.2 출력 예시

```json
{
  "source_id":       "tb_0001",
  "data_id":         "DATA-006",
  "source_category": "disease",
  "knowledge_type":  "disease_guideline",
  "disease_name":    "결핵",
  "document_title":  "2026 국가결핵관리지침",
  "chapter":         "PART Ⅸ. 제1절 취약계층 대상 검진사업",
  "section_title":   "1. 찾아가는 결핵검진",
  "content":         "1. 찾아가는 결핵검진······262\n결핵 검진 사업",
  "chunk_text":      "[2026 국가결핵관리지침] PART Ⅸ. 취약계층 대상 검진사업 > 1. 찾아가는 결핵검진\n결핵 검진 사업",
  "embed_text":      "결핵 찾아가는 결핵검진 결핵 검진 사업",
  "chunk_index":     1,
  "keywords":        ["취약계층", "검진사업"],
  "source":          "2026 국가결핵관리지침.pdf",
  "embedding":       null
}
```

---

## 4. DATA-008 | 감염병 FAQ

### 4.0 입력 파일 구조

```json
// data/DATA_008_FAQ.json
{
  "total": 166,
  "source": "https://www.kdca.go.kr/...",
  "categories": { "감염병": 54, "예방접종": 70, "검역": 15, ... },
  "items": [
    {
      "category": "감염병",
      "question": "[매독] 매독 신고 기준과 방법은...",
      "answer": "신고는 방역통합정보시스템을 통해..."
    }
  ]
}
```

**특징**: 깨끗한 Q&A 구조, category + question 앞 `[질병명]` 태그 패턴 존재

### 4.1 전처리 단계

#### STEP 1 — Q/A 쌍 추출

- `items` 배열의 각 아이템이 1개 청크
- `question` + `answer`를 합쳐 단일 청크 구성
- `chunk_index`: items 내 순서 (0-based)

#### STEP 2 — disease_name 추출

`question` 앞의 `[질병명]` 태그 패턴에서 추출:

```python
import re

# category-to-disease_name 기본 매핑
CATEGORY_DISEASE_MAP = {
    "감염병": None,      # 질병명 태그에서 추출
    "예방접종": None,    # 질병명 태그에서 추출
    "검역": None,
    "만성": None,
    "기타": None,
}

def extract_disease_name(question: str, category: str) -> str | None:
    # "[매독]", "[수족구병]", "[에이즈]" 등 추출
    match = re.match(r'^\[([^\]]+)\]', question.strip())
    if match:
        tag = match.group(1)
        # "기타" 태그는 질병명 아님
        if tag not in ("기타", "일반", "해외", "기관"):
            return tag
    return None
```

**disease_name 추출 규칙**:

| question 패턴 | disease_name |
|---------------|--------------|
| `[매독] 매독 신고...` | `매독` |
| `[수족구병] 자녀가...` | `수족구병` |
| `[에이즈] 성접촉 후...` | `에이즈` |
| `[기타] 집에서 화상벌레...` | `null` (기타 태그) |
| `[예방접종] 인플루엔자...` | `null` (카테고리 태그) |

#### STEP 3 — DB 필드 매핑

```python
def map_faq_item(item: dict, idx: int, source_url: str) -> dict:
    disease_name = extract_disease_name(item["question"], item["category"])
    question_clean = re.sub(r'^\[[^\]]+\]\s*', '', item["question"]).strip()
    
    return {
        "source_id":       f"faq008_{idx:04d}",
        "data_id":         "DATA-008",
        "source_category": "disease",
        "knowledge_type":  "faq",
        "disease_name":    disease_name,
        "document_title":  "질병관리청 FAQ",
        "chapter":         item["category"],
        "section_title":   question_clean[:100],     # 질문 앞 100자
        "content":         f"Q: {item['question']}\nA: {item['answer']}",
        "chunk_text":      None,   # STEP 4에서 생성
        "embed_text":      None,   # STEP 4에서 생성
        "chunk_index":     idx,
        "keywords":        [],
        "source":          source_url,
        "embedding":       None,
    }
```

#### STEP 4 — chunk_text / embed_text 생성

```python
def build_faq_texts(row: dict) -> dict:
    q = row["section_title"]   # 질문 (태그 제거 후)
    a = row["content"].split("\nA: ", 1)[-1] if "\nA: " in row["content"] else ""
    
    # chunk_text: GPT에 전달할 전체 Q/A
    disease_prefix = f"[{row['disease_name']}] " if row["disease_name"] else ""
    chunk_text = f"{disease_prefix}Q: {q}\nA: {a}"
    
    # embed_text: 질문 핵심 + 답변 앞 200자
    embed_text = f"{q} {a[:200]}"
    
    return {**row, "chunk_text": chunk_text, "embed_text": embed_text}
```

### 4.2 출력 예시

```json
{
  "source_id":       "faq008_0047",
  "data_id":         "DATA-008",
  "source_category": "disease",
  "knowledge_type":  "faq",
  "disease_name":    "매독",
  "document_title":  "질병관리청 FAQ",
  "chapter":         "감염병",
  "section_title":   "매독 신고 기준과 방법은 어떻게 되며, 언제까지 신고해야 하나요?",
  "content":         "Q: [매독] 매독 신고 기준과 방법은...\nA: 신고는 방역통합정보시스템을...",
  "chunk_text":      "[매독] Q: 매독 신고 기준과 방법은 어떻게 되며...\nA: 신고는 방역통합정보시스템을 통해 신고가 가능하며...",
  "embed_text":      "매독 신고 기준과 방법은 어떻게 되며 언제까지 신고해야 하나요? 신고는 방역통합정보시스템을 통해 신고가 가능하며 2024년부터 전수 감시체계로",
  "chunk_index":     47,
  "keywords":        [],
  "source":          "https://www.kdca.go.kr/...",
  "embedding":       null
}
```

---

## 5. DATA-009 | 감염병 크롤링

### 5.0 입력 파일 구조

```json
// data/DATA_009_감염병_크롤링.json
[
  {
    "name": "(급성호흡기감염증)리노바이러스 감염증",
    "icd_cd": "ND0705",
    "lcd_sn": "101",
    "department": "감염병관리과",
    "english_name": null,
    "group_name": "4급",
    "sections": {
      "content": "▢\n정의\n◾\n사람 리노바이러스...\n▢\n원인 병원체\n◾\n..."
    }
  }
]
```

**특징**:
- 한 질병당 1개 레코드, `sections.content`가 모든 섹션 통합된 단일 텍스트
- `▢` = 대분류 섹션 마커, `◾` = 소항목 마커
- `\n` 과다 삽입 (크롤링 파싱 artifact)

**섹션 구조**: 정의 / 원인 병원체 / 전파경로 / 임상증상 / 잠복기 및 전염기간 / 치료 / 예방 / 진단·신고 기준 / 담당부서

### 5.1 전처리 단계

#### STEP 1 — 섹션 분리

`▢\n[섹션명]` 패턴 기준으로 분리 → 질병당 N개 청크 생성 (섹션별 1청크):

```python
def split_into_sections(content: str) -> list[dict]:
    """▢ 마커 기준으로 섹션 분리"""
    # ▢ 또는 ▢\n 로 시작하는 섹션 분리
    raw_sections = re.split(r'▢\s*\n?', content)
    sections = []
    for raw in raw_sections:
        raw = raw.strip()
        if not raw:
            continue
        lines = raw.split('\n')
        # 첫 번째 비어있지 않은 줄이 섹션 제목
        title = lines[0].strip()
        body_lines = [l.strip() for l in lines[1:] if l.strip()]
        body = '\n'.join(body_lines)
        if title and body:
            sections.append({"section_title": title, "body": body})
    return sections

# 기대 섹션 목록 (없으면 제외)
VALID_SECTIONS = {
    "정의", "원인 병원체", "전파경로", "임상증상",
    "잠복기 및 전염기간", "치료", "예방", "진단·신고 기준", "담당부서"
}
```

**담당부서 섹션 제외**: `section_title == "담당부서"`인 청크는 제외 (기관명만 있어 RAG 가치 낮음)

#### STEP 2 — 노이즈 클리닝

```python
def clean_crawling_noise(text: str) -> str:
    # 1. ◾ 마커 → 줄바꿈
    text = re.sub(r'◾\s*', '\n', text)
    # 2. 한글 자소 사이 공백 제거
    text = re.sub(r'(?<=[가-힣]) (?=[가-힣])', '', text)
    # 3. 영문+한글 사이 불필요 공백 (ex: "Rhinovirus\n감염에")
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 4. 과학명 괄호 내용 처리: "(Human Rhinovirus)" → 보존 (검색 키워드)
    # 5. 선행/후행 공백 정리
    return text.strip()

def extract_disease_name(item: dict) -> str:
    """name 필드에서 질병명 정제"""
    name = item["name"]
    # "(급성호흡기감염증)리노바이러스 감염증" → "리노바이러스 감염증"
    name = re.sub(r'^\([^)]+\)', '', name).strip()
    return name
```

#### STEP 3 — DB 필드 매핑

```python
def map_crawling_item(item: dict, section: dict, idx: int, chunk_index: int) -> dict:
    disease_name = extract_disease_name(item)
    body_clean = clean_crawling_noise(section["body"])
    
    return {
        "source_id":       f"crawl009_{item['icd_cd']}_{section['section_title'][:10]}",
        "data_id":         "DATA-009",
        "source_category": "disease",
        "knowledge_type":  "disease_info",
        "disease_name":    disease_name,
        "document_title":  f"감염병 정보 — {disease_name}",
        "chapter":         item.get("group_name"),      # 1급, 2급, 4급 등
        "section_title":   section["section_title"],
        "content":         section["body"],             # 정제 전 원본
        "chunk_text":      None,   # STEP 4에서 생성
        "embed_text":      None,   # STEP 4에서 생성
        "chunk_index":     chunk_index,
        "keywords":        [],
        "source":          f"https://www.kdca.go.kr (icd_cd={item['icd_cd']})",
        "embedding":       None,
    }
```

#### STEP 4 — chunk_text / embed_text 생성

```python
def build_crawling_texts(row: dict) -> dict:
    body_clean = clean_crawling_noise(row["content"])
    
    # chunk_text: 질병명 + 섹션명 + 본문
    chunk_text = (
        f"[{row['disease_name']}] {row['section_title']}\n"
        f"{body_clean}"
    )
    
    # embed_text: 질병명 + 섹션명 + 본문 핵심 (500자)
    embed_text = f"{row['disease_name']} {row['section_title']} {body_clean}"[:500]
    
    return {**row, "chunk_text": chunk_text, "embed_text": embed_text}
```

### 5.2 출력 예시

```json
{
  "source_id":       "crawl009_ND0705_임상증상",
  "data_id":         "DATA-009",
  "source_category": "disease",
  "knowledge_type":  "disease_info",
  "disease_name":    "리노바이러스 감염증",
  "document_title":  "감염병 정보 — 리노바이러스 감염증",
  "chapter":         "4급",
  "section_title":   "임상증상",
  "content":         "다른 호흡기바이러스에 비해 발열은 적은 편이며 기침,\n콧물, 코막힘이 흔함...",
  "chunk_text":      "[리노바이러스 감염증] 임상증상\n다른 호흡기바이러스에 비해 발열은 적은 편이며 기침, 콧물, 코막힘이 흔함. 그 외 인후통, 가래, 두통, 근육통...",
  "embed_text":      "리노바이러스 감염증 임상증상 다른 호흡기바이러스에 비해 발열은 적은 편이며 기침 콧물 코막힘이 흔함",
  "chunk_index":     3,
  "keywords":        [],
  "source":          "https://www.kdca.go.kr (icd_cd=ND0705)",
  "embedding":       null
}
```

---

## 6. DATA-010~014 | 시스템 매뉴얼

### 6.0 입력 파일 구조

```json
// data/DATA_010_014_system_merged.json
[
  {
    "id": "tb_med_01_가_인증서로그인",
    "title": "인증서 로그인",
    "content": "가. 인증서 로그인\nl 접근경로 : 질병보건통합관리시스템 접속\n...",
    "text": "[결핵] 인증서 로그인\n가. 인증서 로그인\n...",
    "metadata": {
      "disease_name": "결핵",
      "chapter": "1. 접속 및 권한신청",
      "section_title": "인증서 로그인",
      "chunk_index": 0
    }
  }
]
```

**특징**:
- 이미 청크 분리 + 메타데이터 정제 완료된 최고 품질 데이터
- `text` 필드 = `[질병명] 섹션제목\n내용` → `chunk_text`로 직접 사용 가능
- `id` 패턴으로 DATA-010~014 구분 필요

**id 패턴 → DATA ID 매핑 규칙**

| id 접두사 예시 | 시스템 | DATA ID |
|----------------|--------|---------|
| `tb_med_*` | 결핵관리시스템 (의료기관용) | DATA-010 |
| `tb_pub_*` | 결핵관리시스템 (보건소용) | DATA-011 |
| `vacc_*` | 예방접종 관리 시스템 | DATA-012 |
| `nid_*` | 감염병 신고 시스템 | DATA-013 |
| `etc_*` | 기타 시스템 | DATA-014 |

> ⚠️ **확인 필요**: 실제 `id` 패턴을 데이터 파일에서 직접 확인하여 매핑 규칙 확정 필요

### 6.1 전처리 단계

#### STEP 1 — DATA_ID 분류

```python
def get_data_id(item_id: str) -> str:
    """id 패턴으로 DATA-010~014 분류"""
    if item_id.startswith("tb_med"):
        return "DATA-010"
    elif item_id.startswith("tb_pub") or item_id.startswith("tb_ph"):
        return "DATA-011"
    elif item_id.startswith("vacc"):
        return "DATA-012"
    elif item_id.startswith("nid") or item_id.startswith("inf"):
        return "DATA-013"
    else:
        return "DATA-014"
```

> ⚠️ **코드 실행 전 확인**: `set([item["id"].split("_")[0] for item in data])` 로 실제 접두사 목록 먼저 출력하고 매핑 확정

#### STEP 2 — DB 필드 매핑

```python
def map_system_manual(item: dict) -> dict:
    meta = item.get("metadata", {})
    data_id = get_data_id(item["id"])
    
    return {
        "source_id":       item["id"],
        "data_id":         data_id,
        "source_category": "system",
        "knowledge_type":  "system_manual",
        "disease_name":    meta.get("disease_name"),
        "document_title":  None,    # id에서 유추 불가 → null
        "chapter":         meta.get("chapter"),
        "section_title":   meta.get("section_title") or item.get("title"),
        "content":         item["content"],
        "chunk_text":      None,    # STEP 3에서 생성
        "embed_text":      None,    # STEP 3에서 생성
        "chunk_index":     meta.get("chunk_index", 0),
        "keywords":        [],
        "source":          None,
        "embedding":       None,
    }
```

#### STEP 3 — chunk_text / embed_text 생성

```python
def build_system_texts(row: dict) -> dict:
    # chunk_text: 기존 text 필드 = "[결핵] 인증서 로그인\n..." 형식 → 그대로 사용
    # 단, 기존 text 필드가 없으면 재구성
    chunk_text = item.get("text") or (
        f"[{row['disease_name']}] {row['section_title']}\n{row['content']}"
    )
    
    # embed_text: 섹션제목 + 본문 핵심 (절차 중심)
    section = row.get("section_title", "")
    content_short = row["content"][:400]
    embed_text = f"{row.get('disease_name', '')} {section} {content_short}"[:500]
    
    return {**row, "chunk_text": chunk_text, "embed_text": embed_text}
```

### 6.2 출력 예시

```json
{
  "source_id":       "tb_med_01_가_인증서로그인",
  "data_id":         "DATA-010",
  "source_category": "system",
  "knowledge_type":  "system_manual",
  "disease_name":    "결핵",
  "document_title":  null,
  "chapter":         "1. 접속 및 권한신청",
  "section_title":   "인증서 로그인",
  "content":         "가. 인증서 로그인\nl 접근경로 : 질병보건통합관리시스템 접속\n...",
  "chunk_text":      "[결핵] 인증서 로그인\n가. 인증서 로그인\nl 접근경로 : 질병보건통합관리시스템 접속\n개요 : 간편인증, 공동인증서, 디지털원패스로 로그인합니다...",
  "embed_text":      "결핵 인증서 로그인 접근경로 질병보건통합관리시스템 접속 간편인증 공동인증서 디지털원패스로 로그인합니다",
  "chunk_index":     0,
  "keywords":        [],
  "source":          null,
  "embedding":       null
}
```

---

## 7. DATA-015 | 시스템 FAQ

### 7.0 입력 파일 구조

```json
// data/DATA_015_FAQ.json
{
  "total": 90,
  "source": "https://dportal.kdca.go.kr/...",
  "categories": {
    "감염병정보": 19,
    "코로나19": 71
  },
  "items": [
    {
      "category": "감염병정보",
      "question": "자동신고 진행시 감염병 항목이 선택되지 않는 증상 확인 중",
      "answer": "시스템을 확인중이며..."
    }
  ]
}
```

**특징**:
- `감염병정보` 카테고리: 감염병 신고 시스템 관련 (시스템 운영·오류) → `source_category = 'system'`
- `코로나19` 카테고리: 코로나19 신고/관리 정보 → `source_category = 'system'` (시스템 포털)
- question에 `[질병명]` 태그가 없는 경우 다수 (시스템 공지 형태)

### 7.1 전처리 단계

#### STEP 1 — Q/A 쌍 추출

- DATA-008과 동일하게 items 배열 → 1아이템 1청크
- `chunk_index`: items 내 순서

#### STEP 2 — source_category 분류 및 disease_name 추출

```python
def classify_faq015(item: dict) -> dict:
    category = item["category"]
    question = item["question"]
    
    # source_category: 이 FAQ는 감염병 포털(시스템) 기준 → 전체 'system'
    source_category = "system"
    
    # disease_name 추출 (question에서)
    disease_name = None
    if category == "코로나19":
        disease_name = "코로나19"
    else:
        # [질병명] 패턴 시도
        match = re.match(r'^\[([^\]]+)\]', question.strip())
        if match:
            tag = match.group(1)
            if tag not in ("기타", "일반", "안내", "공지"):
                disease_name = tag
    
    return {
        "source_category": source_category,
        "disease_name": disease_name,
    }
```

#### STEP 3 — DB 필드 매핑

```python
def map_faq015_item(item: dict, idx: int, source_url: str) -> dict:
    classification = classify_faq015(item)
    question_clean = re.sub(r'^\[[^\]]+\]\s*', '', item["question"]).strip()
    
    return {
        "source_id":       f"faq015_{idx:04d}",
        "data_id":         "DATA-015",
        "source_category": classification["source_category"],
        "knowledge_type":  "faq",
        "disease_name":    classification["disease_name"],
        "document_title":  "감염병 포털 FAQ",
        "chapter":         item["category"],
        "section_title":   question_clean[:100],
        "content":         f"Q: {item['question']}\nA: {item['answer']}",
        "chunk_text":      None,    # STEP 4에서 생성
        "embed_text":      None,    # STEP 4에서 생성
        "chunk_index":     idx,
        "keywords":        [],
        "source":          source_url,
        "embedding":       None,
    }
```

#### STEP 4 — chunk_text / embed_text 생성

```python
def build_faq015_texts(row: dict) -> dict:
    q = row["section_title"]
    a = row["content"].split("\nA: ", 1)[-1] if "\nA: " in row["content"] else ""
    
    category_label = f"[{row['chapter']}]"
    disease_label = f"[{row['disease_name']}] " if row["disease_name"] else ""
    
    chunk_text  = f"{category_label} {disease_label}Q: {q}\nA: {a}"
    embed_text  = f"{row.get('disease_name', '')} {q} {a[:200]}".strip()[:500]
    
    return {**row, "chunk_text": chunk_text, "embed_text": embed_text}
```

### 7.2 출력 예시

```json
{
  "source_id":       "faq015_0002",
  "data_id":         "DATA-015",
  "source_category": "system",
  "knowledge_type":  "faq",
  "disease_name":    null,
  "document_title":  "감염병 포털 FAQ",
  "chapter":         "감염병정보",
  "section_title":   "코로나11 급수 변경에 따른 자동신고 관련 안내사항",
  "content":         "Q: 코로나11 급수 변경에 따른...\nA: 안녕하세요. 이번에 코로나19 감염병의 급수가...",
  "chunk_text":      "[감염병정보] Q: 코로나11 급수 변경에 따른 자동신고 관련 안내사항\nA: 안녕하세요. 이번에 코로나19 감염병의 급수가 2급 > 4급으로 변경됨에 따라...",
  "embed_text":      "코로나11 급수 변경에 따른 자동신고 관련 안내사항 이번에 코로나19 감염병의 급수가 2급 4급으로 변경됨에 따라",
  "chunk_index":     2,
  "keywords":        [],
  "source":          "https://dportal.kdca.go.kr/...",
  "embedding":       null
}
```

---

## 8. 공통 품질 기준 및 필터링 규칙

### 8.1 전체 공통 필터 (모든 데이터 소스 적용)

| 조건 | 처리 |
|------|------|
| `chunk_text` 길이 < 20자 | 제거 |
| `chunk_text` 한글 비율 < 30% | 제거 |
| `embed_text` 비어있음 | 제거 |
| `embed_text` > 500자 | 500자로 truncate |
| `keywords`가 None | `[]`로 대체 |
| `disease_name`이 빈 문자열 | `null`로 대체 |
| `section_title` > 300자 | 300자로 truncate |

### 8.2 데이터 소스별 최소 청크 수 기준 (참고)

| DATA ID | 예상 청크 수 |
|---------|-------------|
| DATA-001 (코로나19) | 300~600개 (필터 후) |
| DATA-002~007 | 각 50~300개 |
| DATA-008 (FAQ) | 약 160개 (166개 중 필터) |
| DATA-009 (크롤링) | 질병 수 × 섹션 수 (약 700~1,200개) |
| DATA-010~014 (시스템) | 약 300~500개 |
| DATA-015 (FAQ) | 약 85개 (90개 중 필터) |

### 8.3 embed_text 품질 체크 포인트

```
□ 의미 있는 한글 단어가 3개 이상 포함되는가?
□ 질병명이 있는 경우 embed_text에 포함되는가?
□ 섹션 제목의 핵심 키워드가 포함되는가?
□ OCR 노이즈 문자열이 제거되었는가?
□ 500자 이내인가?
```

---

## 9. 출력 파일 목록 및 경로

```
db/scripts/output/
├── chunks_data001~007.json    ← DATA-001~007 통합 (7개 파일 → 1개 출력)
├── chunks_data008.json        ← DATA-008 FAQ
├── chunks_data009.json        ← DATA-009 크롤링
├── chunks_data010~014.json    ← DATA-010~014 통합
└── chunks_data015.json        ← DATA-015 FAQ
```

### 9.1 통합 스크립트 실행 순서 (예정)

```
1. python preprocess_001_007.py  → chunks_data001~007.json
2. python preprocess_008.py      → chunks_data008.json
3. python preprocess_009.py      → chunks_data009.json
4. python preprocess_010_014.py  → chunks_data010~014.json
5. python preprocess_015.py      → chunks_data015.json

6. python embed_and_load.py      → 전체 JSON → embedding 생성 → DB INSERT
```

### 9.2 임베딩 적재 순서 (embed_and_load.py)

```python
# embed_and_load.py 흐름
for json_file in OUTPUT_FILES:
    chunks = load_json(json_file)
    for chunk in chunks:
        chunk["embedding"] = openai_embed(chunk["embed_text"])  # text-embedding-3-small
        db_insert(chunk)   # knowledge_chunks INSERT
```

---

*전처리 명세서 v1.0 — DB 설계서 v2.0 기반 · 코드 작성 전 검토용*

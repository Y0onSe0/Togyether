# 데이터 파이프라인 명세서 v1.0
## 질병관리청 1339 콜센터 AI 지원 시스템

> 작성일: 2026-05-08
> 참조: DB 설계서 v2.0

---

## 1. 개요
### 1.1 데이터 수집 및 전처리 목적
본 시스템은 RAG 기반으로 동작한다. LLM이 정확한 답변을 생성하려면 관련 문서를 검색해 컨텍스트로 주입해야 하며, 이를 위해 원본 데이터를 검색 가능한 단위로 가공해 DB에 저장하는 것이 전처리의 목적이다.
- **검색 가능한 크기로 분할** — PDF 전체를 통째로 넣을 수 없으므로 의미 단위(절·항목·대화 1건)로 분할
- **노이즈 제거** — 페이지번호·사이드바·러닝헤더 등 PDF 추출 부산물 및 크롤링 깨짐 복원
- **메타데이터 구조화** — 질병명·챕터·섹션·카테고리 태깅으로 출처 추적 및 필터링 가능

본 시스템은 **PostgreSQL 16 (pgvector)** 단일 DB를 사용하며, 데이터 용도에 따라 3개 테이블로 분리한다.

| 테이블 | 용도 |
| --- | --- |
| `knowledge_chunks` | AI 답변 생성용 RAG 검색 |
| `acw_cards` | 유사 상담 사례 검색 + 대시보드 시각화 |
| `transfer_agencies` | 이관 대상 기관 검색 |

### 1.2 데이터 소스 목록

| DATA ID | 데이터 명 | 데이터 출처 | 테이블 | 청크 수 |
| --- | --- | --- | --- | --- |
| DATA-001 | chunks_covid | 2025년도 코로나19 관리지침 | knowledge_chunks | 138 |
| DATA-002 | chunks_diagnostic | 법정감염병 진단검사 통합지침(제4-2판) | knowledge_chunks | 296 |
| DATA-003 | chunks_dupest | 제1급감염병 두창·페스트·탄저·보툴리눔·야토병 대응지침 | knowledge_chunks | 140 |
| DATA-004 | chunks_hiv | 2026년 HIV/AIDS 관리지침 | knowledge_chunks | 187 |
| DATA-005 | chunks_mers | 제1급감염병 MERS·SARS 대응지침 | knowledge_chunks | 280 |
| DATA-006 | chunks_tb | 2026 국가결핵관리지침 | knowledge_chunks | 419 |
| DATA-007 | chunks_vhf | 제1급감염병 바이러스성출혈열 대응지침 | knowledge_chunks | 245 |
| DATA-008 | chunks_질병관리청_FAQ | 질병관리청 FAQ | knowledge_chunks | 164 |
| DATA-009 | chunks_crawl | 질병관리청 법정감염병 정보 (크롤링) | knowledge_chunks | 1,082 |
| DATA-010 | chunks_감염병포털_FAQ | 질병관리청 감염병포털 FAQ | knowledge_chunks | 90 |
| DATA-011 | chunks_hiv_system | 2026년 HIV/AIDS 관리지침 (에이즈지원시스템) | knowledge_chunks | 1 |
| DATA-012 | chunks_covid19_system | 2025년도 코로나19 관리지침 (방역통합정보시스템) | knowledge_chunks | 12 |
| DATA-013 | chunks_tb_system | 결핵관리 사용자 이용설명서 (보건소용) | knowledge_chunks | 96 |
| DATA-014 | chunks_tb_hospital | 결핵관리 사용자 이용설명서 (의료기관용) | knowledge_chunks | 48 |
| DATA-015 | 질병관리청_소속기관 | 질병관리청 홈페이지 | transfer_agencies | 123 |
| DATA-016 | acw_cards_all | AI Hub 홈페이지 | acw_cards | 3,744 |

### 1.3 전체 파이프라인
```
┌─────────────────────────────────────────────────────────────────────┐
│                          데이터 수집                                  │
│                                                                     │
│  질병관리청 사이트                감염병 포털           AI Hub          │
│  ┌──────────────┐  ┌─────────┐  ┌────────────────┐  ┌──────────┐  │
│  │ PDF 다운로드  │  │유관기관  │  │법정감염병 크롤링│  │상담 대화  │  │
│  │ (수동 수집)  │  │연락처   │  │133종 + FAQ 256건│  │스크립트   │  │
│  │ 지침서 16종  │  │수집     │  │                │  │451,865턴 │  │
│  └──────┬───────┘  └────┬────┘  └───────┬────────┘  └────┬─────┘  │
└─────────┼───────────────┼───────────────┼────────────────┼────────┘
          │               │               │                │
          ▼               ▼               ▼                ▼
     PDF 16종         CSV 원본        JSON 원본        JSON 원본
                    (123개 기관)
┌──────────────────────────────┐  ┌────────────┐  ┌─────────────────┐
│   knowledge_chunks 전처리     │  │이관기관 전처리│  │ ACW Cards 전처리 │
│                              │  │            │  │                 │
│ PDF파서: 텍스트추출→TOC스킵   │  │description │  │Step1 그룹핑     │
│   →노이즈제거→계층분리→청킹   │  │→LLM 요약   │  │Step2 LLM 필드   │
│ FAQ파서: 분류→GPT→Q&A청크    │  │→embed_text │  │     생성        │
│ 크롤링: 포맷감지→섹션→청크    │  │  생성       │  │Step3~6 샘플링   │
└──────────────┬───────────────┘  └─────┬──────┘  │ 및 메타데이터   │
               │                         │         └────────┬────────┘
               ▼                         ▼                  ▼
      JSON 청크 파일 16종           CSV (V7)         acw_cards_all.json
        (~3,200+ 청크)            (123개 기관)           (3,744개)
               │                         │                  │
               └─────────────────────────┴──────────────────┘
                                          │
┌─────────────────────────────────────────▼───────────────────────────┐
│                           DB 적재                                     │
│                                                                     │
│  embed_text ──▶ OpenAI 임베딩 생성 ──▶ pgvector 저장                │
│                                                                     │
│  knowledge_chunks │ transfer_agencies │ acw_cards                   │
│  (벡터+메타데이터) │  (벡터+기관정보)  │ (벡터+상담카드+mock메타)     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 데이터 수집

### 2.1 PDF 수집 (knowledge_chunks)
질병관리청 사이트에서 감염병 관리지침·대응지침·시스템 매뉴얼 총 16종을 수동 다운로드.

### 2.2 유관기관 연락처 수집 (transfer_agencies)
질병관리청 홈페이지에서 이관 대상 유관기관 연락처 123개 기관 수집 후 CSV 정리.

### 2.3 크롤링 수집 (knowledge_chunks — DATA-009)
질병관리청 감염병포털 법정감염병 정보 페이지. 133종 법정감염병 정보 크롤링.

### 2.4 FAQ 수집 (knowledge_chunks — DATA-008, 010)
질병관리청 민원 FAQ(166건), 감염병포털 FAQ(90건) 스크래핑.

### 2.5 AI Hub 상담 데이터 (acw_cards)
AI Hub 공개 상담 데이터셋. 451,865 턴 / 21,982 대화셋.

---

## 3. 데이터 전처리

### 3.1 Knowledge Chunks 공통 파이프라인

#### 3.1.1 PDF 파서 (DATA-001~007, 011~014)
```
① pdfplumber 텍스트 추출
② TOC 스킵 (TOC_END_POS 이전 구간 제거)
③ SIDEBAR_PATTERNS 노이즈 제거
   (페이지번호 · 러닝헤더 · 사이드바 라벨)
④ 계층 구조 분리
   PART/장/절 → 번호항목(1.) → 가나다항목(가.)
⑤ refine_content: 800자 초과 시 문장 단위 분할
⑥ is_garbage_chunk 필터
   한글 30자 미만 or 한글비율 40% 미만 제거
```

> **800자 기준**: 의학 지침 한 단락 분량 = 임베딩 품질·검색 정밀도 균형점 (한국어 800자 ≈ BPE 400~600 토큰)
> **가비지 필터**: PDF 레이아웃 파괴로 생기는 페이지번호·사이드바 조각·표 셀 파편 제거

#### 3.1.2 FAQ 파서 (DATA-008, 010)
```
① JSON 입력 (question / answer 필드)
② category 기반 source_category 분류
   시스템 운영 관련 → 'system' / 그 외 → 'disease'
③ GPT-4o-mini 배치 호출 (10건씩)
   → section_title 생성, keywords 생성
④ chunk_text = "Q: {question}\nA: {answer}"
```

#### 3.1.3 크롤링 파서 (DATA-009)
```
① 질병명 앞 카테고리 괄호 제거
   "(급성호흡기감염증)노로바이러스 감염증" → "노로바이러스 감염증"
② 포맷 자동 감지
   ◾ 있으면 Format A / ○·⊙ 있으면 Format B
③ 섹션 분리 → (섹션명, 본문) 쌍 리스트
④ clean_bullet_text() 크롤링 깨짐 복원
⑤ 섹션 하나 = 청크 하나
```

### 3.2 데이터별 전처리 특이사항

| DATA | 특이사항 |
| --- | --- |
| 001 | `총론/각론` 단위 분리 → `제N장` → `번호` → `가나다` 계층 |
| 002 | PDF 재파싱 대신 **원본 JSON 후처리** — 노이즈 제거 + 병명 공식명 정규화 (~130종) |
| 003, 007 | `PART Ⅰ 총론 / PART Ⅱ 각론` 분리 → 각론 내 `제N장(질병별)` → `번호` → `가나다` |
| 004 | 로마숫자 단원(Ⅰ~Ⅶ) 분리. **스킵**: 민간보조사업·서식·부록. `마. 의료기관 자체판정 등록`은 DATA-011 중복으로 제외 |
| 005 | **분리 후 정제** 순서 핵심. raw 텍스트에서 MERS/SARS 구간 먼저 분리 → 각각 clean → PART별 청킹 |
| 006 | 매 페이지 러닝헤더로 PART 수백 개 생성 → `merge_parts()`로 14개 병합. `ⅩⅠ/Ⅺ`, `ⅩⅡ/Ⅻ` 유니코드 정규화. PART ⅩⅣ 부록 키로 직접 스킵 |

### 3.3 ACW Cards 전처리 (6단계)
```
Step 1  그룹핑
        대화셋일련번호 기준 턴 묶기
        → {conversation_id, turns[], 고객의도[], 용어사전[]}
        (21,982개)

Step 2  LLM 필드 생성  — GPT-4o-mini, 10건 배치
        입력: turns 전문 + 고객의도(힌트)
        출력: title / customer_type /
              category · category_major · category_mid /
              disease_name / qa_summary / keywords

Step 3  대시보드 샘플링
        카테고리 현실 가중치로 200개 추출
        감염병 57% / 접수처리 36% / 범위외 7%

Step 4  Mock 메타데이터 생성
        상담사 5명, 통화 200건
        날짜 구간: 오늘 15건 / 이번주 30건 / 이번달 155건
        통화시간: 90~900초 / 해결·이관: 카테고리별 가중치

Step 5  ai_hub 레코드 추출
        정상 레코드 전체 - 대시보드 200개 → ~3,544개

Step 6  최종 스키마 정리
        system 200 + ai_hub 3,544 = 3,744개
```

### 3.4 Transfer Agencies 전처리
```
① 원본 CSV 로드 (123개 기관)
② description 컬럼 → GPT LLM 입력
   담당업무 원문이 길고 복잡해 검색에 부적합
   → LLM으로 핵심 업무만 간결하게 요약
③ description_summary 컬럼 생성 (프론트 표시용)
④ description 필드 임베딩
   담당업무 원문 그대로 description_embedding 생성
⑤ DB 적재 (embedding은 적재 시 생성)
```

```python
# description 필드를 임베딩 소스로 사용
# description_embedding = embed(description)
# description_summary는 LLM 요약본 (프론트 표시용)
```

---

## 4. 결과

### knowledge_chunks 테이블

| knowledge_type | 청크 수 |
| --- | --- |
| disease_guideline | 1,705 |
| disease_info | 1,082 |
| system_manual | 157 |
| faq | 254 |
| **합계** | **3,198** |

### acw_cards 테이블

| source | 개수 | 용도 |
| --- | --- | --- |
| ai_hub | ~3,544 | RAG 유사 사례 검색 |
| system (대시보드) | 200 | 대시보드 시연 |
| system (시연·테스트) | 51 | 기능 테스트 |
| **합계** | **~3,795** | |

### transfer_agencies 테이블

| 항목 | 내용 |
| --- | --- |
| 기관 수 | 123개 |
| 출처 | 질병관리청 홈페이지 |
| 임베딩 소스 | `description` (담당업무 원문) |
| 임베딩 컬럼 | `description_embedding` |

### 전체 요약

| 테이블 | 레코드 수 | 임베딩 소스 | 임베딩 컬럼 |
| --- | --- | --- | --- |
| `knowledge_chunks` | 3,198 청크 | `embed_text` (문서 내용) | `embedding` |
| `acw_cards` | ~3,795개 | `qa_summary` Q 파트 | `q_embedding` |
| `transfer_agencies` | 123개 | `description` (기관 업무) | `description_embedding` |

---

*데이터 파이프라인 명세서 v1.0 — DB 설계서 v2.0 기반*

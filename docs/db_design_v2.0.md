# 데이터베이스 설계서 v2.1
## 질병관리청 1339 콜센터 AI 지원 시스템

> 작성일: 2026-05-05  
> v2.1 수정 (2026-05-06):  
> - `agents`: `username` 컬럼 추가 (로그인 아이디, UNIQUE)  
> - `acw_cards.ai_guidance`: `oos_type` 필드 추가  
> - `category_master`: 분류 체계 변경 (`시스템`·`이관` → `접수처리`, `기타` → `범위외`) 및 시드 데이터 17행으로 재정의

---

## 1. 개요

### 1.1 시스템 목적
질병관리청 1339 콜센터 상담사가 실시간 통화 중 AI 안내, 유사사례, 이관기관 정보를 즉시 참조할 수 있도록 지원하는 RAG 기반 AI 시스템의 데이터베이스.

### 1.2 DB 선택 근거

| 항목 | 선택 | 근거 |
| --- | --- | --- |
| RDBMS | PostgreSQL 16 | 안정성, JSON 지원, pgvector 확장 지원 |
| 벡터 확장 | pgvector | 별도 벡터DB 없이 RDBMS와 통합 관리, 운영 복잡도 감소 |
| 임베딩 모델 | text-embedding-3-small (1536d) | OpenAI 공식 권장, 비용/성능 균형 |
| 인덱스 | ivfflat (cosine) | ANN 근사 검색, 대용량 벡터 검색 성능 확보 |

### 1.3 전체 테이블 목록

| # | 테이블명 | 설명 | 데이터 출처 |
| --- | --- | --- | --- |
| 1 | `agents` | 상담사 계정 관리 | 수동 입력 |
| 2 | `calls` | 통화 세션 | 시스템 자동 생성 |
| 3 | `acw_cards` | ACW 후처리 카드 + 유사사례 (3,744건) | DATA-016 (system 200 + ai_hub 3,544) |
| 4 | `knowledge_chunks` | 통합 RAG 지식 청크 (3,058청크) | DATA-001~014 (DATA-003 미적재) |
| 5 | `transfer_agencies` | 이관기관 정보 (123건) | DATA-015 |
| 6 | `category_master` | ACW 분류 시드 | 수동 정의 |

---

## 2. 테이블 정의서

### 2.1 `agents`

**설명**: 상담사 계정 정보 저장. 로그인, 권한 관리, 통화/ACW 이력 연결에 사용.  
**데이터 출처**: 운영팀 수동 입력 (시드 스크립트)

| 컬럼명 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| agent_id | SERIAL | NOT NULL | auto | PK, 상담사 고유 ID |
| username | VARCHAR(50) | NOT NULL | — | 로그인 아이디 (UNIQUE) |
| name | VARCHAR(50) | NOT NULL | — | 상담사 이름 |
| password_hash | VARCHAR(255) | NOT NULL | — | bcrypt 해시 (평문 저장 금지) |
| created_at | TIMESTAMP | NOT NULL | now() | 생성일 |

---

### 2.2 `calls`

**설명**: 상담사와 고객 간 통화 세션 정보. 통화 시작 시 생성, 종료 시 업데이트.  
**데이터 출처**: 통화 시작/종료 시 API 자동 생성

| 컬럼명 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| call_id | SERIAL | NOT NULL | auto | PK, 통화 고유 ID |
| agent_id | INT | NULL | — | FK → agents.agent_id |
| status | VARCHAR(20) | NOT NULL | `'active'` | `'active'` \| `'acw'` \| `'ended'` |
| conversation_history | JSONB | NOT NULL | `'[]'` | 실시간 대화 내역 |
| started_at | TIMESTAMP | NOT NULL | `now()` | 통화 시작 시각 |
| ended_at | TIMESTAMP | NULL | — | 통화 종료 시각 |
| duration_sec | INT | NULL | — | 통화 시간(초) |
| created_at | TIMESTAMP | NOT NULL | `now()` | 생성일 |

**conversation_history JSONB 구조**
```json
[
  { "speaker": "agent",    "text": "안녕하세요, 1339입니다.", "timestamp": "2026-05-02T14:23:01" },
  { "speaker": "customer", "text": "코로나19 격리기간 문의드립니다.", "timestamp": "2026-05-02T14:23:05" }
]
```

**상태 전이**
```
통화 시작 → status = 'active'
통화 종료 → status = 'acw', ended_at = now()
ACW 완료  → status = 'ended'
```

---

### 2.3 `acw_cards`

**설명**: 통화 종료 후 상담사가 작성하는 후처리 카드. 유사사례 검색 소스로도 활용.

**데이터 출처 2종**

| source 값 | 출처 | 설명 |
| --- | --- | --- |
| `'system'` | 실제 통화 후 상담사 작성 | call_id, agent_id 필수 |
| `'ai_hub'` | DATA-016 AI Hub 상담내역 | call_id, agent_id NULL, 시연용 |

| 컬럼명 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| acw_id | SERIAL | NOT NULL | auto | PK |
| call_id | INT | NULL | — | FK → calls.call_id (UNIQUE), ai_hub는 NULL |
| agent_id | INT | NULL | — | FK → agents.agent_id, ai_hub는 NULL |
| source | VARCHAR(20) | NOT NULL | `'system'` | `'system'` \| `'ai_hub'` |
| title | VARCHAR(200) | NULL | — | 상담 제목 |
| customer_type | VARCHAR(20) | NULL | — | `'citizen'` \| `'medical'` \| `'other'` |
| customer_type_custom | VARCHAR(100) | NULL | — | 기타 고객 유형 직접 입력 |
| category | VARCHAR(50) | NULL | — | 상담 분류 (category_master 참조) |
| category_major | VARCHAR(100) | NULL | — | 대분류 |
| category_mid | VARCHAR(100) | NULL | — | 중분류 |
| category_mid_list | JSONB | NULL | — | 복수 중분류 선택 시 배열 |
| category_mid_custom | VARCHAR(100) | NULL | — | 기타 중분류 직접 입력 |
| disease_name | VARCHAR(100) | NULL | — | 관련 질병명 |
| qa_summary | JSONB | NULL | — | GPT 자동 생성 Q/A 요약 |
| transcript | TEXT | NULL | — | 전체 대화 원문 |
| ai_response_summary | TEXT | NULL | — | 단일 서술형 단락 (고객문의→AI·상담사안내→처리결과 순) |
| is_transferred | BOOLEAN | NULL | `false` | 이관 여부 |
| transfer_target | VARCHAR(200) | NULL | — | 이관 기관명 |
| keywords | JSONB | NULL | — | 키워드 배열 |
| satisfaction | SMALLINT | NULL | — | AI 답변 만족도 1~5 (상담사 선택, 선택 입력) |
| agent_memo | TEXT | NULL | — | 상담사 메모 |
| is_resolved | BOOLEAN | NULL | — | 해결 여부 |
| agent_used_ai | VARCHAR(20) | NULL | — | AI 활용 여부: `'yes'` \| `'partial'` \| `'no'` |
| q_embedding | VECTOR(1536) | NULL | — | qa_summary 첫 번째 Q 임베딩 |
| acw_started_at | TIMESTAMP | NULL | — | ACW 시작 시각 |
| acw_ended_at | TIMESTAMP | NULL | — | ACW 종료 시각 |
| acw_duration_sec | INT | NULL | — | ACW 소요 시간(초) |
| created_at | TIMESTAMP | NOT NULL | `now()` | 생성일 |
| ai_guidance | JSONB | NULL | — | 통화 중 AI 안내 카드 전체 내용. STEP 1~3 결과 저장. {query, disease_name, answer, is_oos, oos_type, oos_reason, sources[]} |

**1) ai_guidance JSONB 구조**

`is_oos=false` (정상 상담):
```json
{
  "query": "코로나19 격리 기간 기준은?",
  "disease_name": "코로나19",
  "answer": "현행 지침 기준으로 확진일로부터 7일 격리를 권고합니다.",
  "is_oos": false,
  "oos_type": null,
  "oos_reason": null,
  "sources": [
    {
      "chunk_id": 42,
      "document_title": "2026년 코로나19 관리지침",
      "section_title": "격리 기간 기준",
      "data_id": "DATA-001"
    },
    {
      "chunk_id": 87,
      "document_title": "2026년 코로나19 관리지침",
      "section_title": "격리 해제 기준",
      "data_id": "DATA-001"
    },
    {
      "chunk_id": 134,
      "document_title": "코로나19 FAQ",
      "section_title": "격리 기간 관련 자주 묻는 질문",
      "data_id": "DATA-008"
    }
  ]
}
```

`is_oos=true` (범위외):
```json
{
  "query": "날씨 어때요",
  "disease_name": null,
  "answer": null,
  "is_oos": true,
  "oos_type": "unrelated",
  "oos_reason": "날씨 관련 정보는 기상청으로 문의주세요",
  "sources": []
}
```

> `oos_type`: `"unrelated"` | `"action_required"`

**2) qa_summary JSONB 구조**
```json
[
  { "q": "코로나19 격리기간이 어떻게 되나요?", "a": "확진일로부터 7일 격리 권고입니다." }
]
```

---

### 2.4 `knowledge_chunks`

**설명**: RAG 검색을 위한 통합 지식 청크 저장소. 감염병 지침, 크롤링 정보, FAQ, 시스템 매뉴얼을 단일 테이블에 통합 관리.

**단일 테이블 설계 근거**: 동일 임베딩 모델(text-embedding-3-small) 사용 시 문서 타입에 관계없이 동일한 의미 공간에 투영되므로 통합 검색이 가능함. (Gao et al., 2024; LangChain, 2024)

**데이터 출처 (실제 적재 기준)**

| data_id | 파일명 | 문서명 | source_category | knowledge_type | 청크 수 |
| --- | --- | --- | --- | --- | --- |
| DATA-001 | DATA_001_chunks_covid | 2025년도 코로나19 관리지침 | `disease` | `disease_guideline` | 138 |
| DATA-002 | DATA_002_chunks_diagnostic | 법정감염병 진단검사 통합지침(제4-2판) | `disease` | `disease_guideline` | 296 |
| DATA-003 | *(미적재)* | 두창 관리지침 | — | — | — |
| DATA-004 | DATA_004_chunks_hiv | 2026년 HIV/AIDS 관리지침 | `disease` | `disease_guideline` | 187 |
| DATA-005 | DATA_005_chunks_mers | MERS·SARS 대응지침 | `disease` | `disease_guideline` | 280 |
| DATA-006 | DATA_006_chunks_tb | 2026 국가결핵관리지침 | `disease` | `disease_guideline` | 419 |
| DATA-007 | DATA_007_chunks_vhf | 제1급감염병 바이러스성출혈열 대응지침 | `disease` | `disease_guideline` | 245 |
| DATA-008 | DATA_008_chunks_질병관리청_FAQ | 질병관리청 FAQ | `disease`+`system` | `faq` | 164 |
| DATA-009 | DATA_009_chunks_crawl | 질병관리청 법정감염병 정보 (크롤링) | `disease` | `disease_info` | 1,082 |
| DATA-010 | DATA_010_chunks_faq | 질병관리청 감염병포털 FAQ | `disease`+`system` | `faq` | 90 |
| DATA-011 | DATA_011_chunks_hiv_system | 2026년 HIV/AIDS 관리지침 (시스템 매뉴얼) | `system` | `system_manual` | 1 |
| DATA-012 | DATA_012_chunks_covid19_system | 2025년도 코로나19 관리지침 (시스템 매뉴얼) | `system` | `system_manual` | 12 |
| DATA-013 | DATA_013_chunks_tb_system | 결핵관리 사용자 이용 설명서[보건소] | `system` | `system_manual` | 96 |
| DATA-014 | DATA_014_chunks_tb_hospital | 결핵관리 사용자 이용 설명서[의료기관] | `system` | `system_manual` | 48 |

> **DATA-003 미적재**: 두창(Mpox) 원본 데이터 미확보  
> **총 knowledge_chunks**: 3,058청크 (DATA-003 제외)

| 컬럼명 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | SERIAL | NOT NULL | auto | PK |
| source_id | VARCHAR(200) | NULL | — | 원본 파일의 id 값 |
| data_id | VARCHAR(20) | NOT NULL | — | `'DATA-001'` ~ `'DATA-014'` (DATA-003 미적재) |
| source_category | VARCHAR(10) | NOT NULL | — | `'disease'` \| `'system'` |
| knowledge_type | VARCHAR(30) | NOT NULL | — | 아래 표 참고 |
| disease_name | VARCHAR(100) | NULL | — | 관련 질병명 (system_faq는 NULL 가능) |
| document_title | VARCHAR(300) | NULL | — | 문서 제목 |
| chapter | VARCHAR(200) | NULL | — | 챕터 또는 감염병 급 구분 |
| section_title | VARCHAR(300) | NULL | — | 섹션 제목 (FAQ는 질문 원문) |
| content | TEXT | NULL | — | 원본 텍스트 (가공 전) |
| chunk_text | TEXT | NOT NULL | — | GPT에 전달할 전체 텍스트 |
| embed_text | TEXT | NOT NULL | — | 실제 임베딩 대상 텍스트 |
| chunk_index | INT | NULL | `0` | 문서 내 청크 순번 |
| keywords | JSONB | NULL | — | 키워드 배열 |
| source | VARCHAR(500) | NULL | — | 원본 파일명 또는 URL |
| embedding | VECTOR(1536) | NULL | — | embed(embed_text) |

**knowledge_type 상세**

| knowledge_type | source_category | chunk_text 포맷 | embed_text | 비고 |
| --- | --- | --- | --- | --- |
| `disease_guideline` | disease | `[감염병 지침] 질병명 \| 챕터 > 섹션\n본문` | chunk_text 전체 | DATA-001, 002, 004~007 |
| `disease_info` | disease | `[감염병 정보] 질병명 \| 급 > 섹션\n본문` | chunk_text 전체 | DATA-009 |
| `faq` | disease/system | `[감염병 FAQ] 질병명\nQ: ...\nA: ...` / `[시스템 FAQ]\nQ: ...\nA: ...` | Q 텍스트만 | DATA-008, DATA-010 |
| `system_manual` | system | `[시스템 매뉴얼] 질병명 \| 챕터 > 섹션\n본문` | chunk_text 전체 | DATA-011, 012, 013, 014 |

> **embed_text 분리 이유**: FAQ는 사용자 질문과 FAQ 질문 간 유사도 비교가 목적이므로 Q만 임베딩. chunk_text(Q+A 전체)로 임베딩하면 긴 답변 텍스트가 벡터를 희석시켜 검색 정확도 저하.

---

### 2.5 `transfer_agencies`

**설명**: 이관 가능한 외부 기관 정보. 고객 문의 내용과 기관 담당업무 간 벡터 유사도 검색으로 적합 기관 추천.  
**데이터 출처**: DATA-015 (DATA_015_질병관리청_소속기관.csv)

| 컬럼명 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| agency_id | SERIAL | NOT NULL | auto | PK |
| category | VARCHAR(30) | NULL | — | `'관련 기관'` \| `'소속기관'` \| `'질병관리청 직원'` \| `'응급'` |
| org_name | VARCHAR(200) | NOT NULL | — | 기관명 (CSV 중분류) |
| dept_name | VARCHAR(200) | NULL | — | 부서명 (중분류와 동일하면 NULL) |
| phone | VARCHAR(100) | NULL | — | 전화번호 |
| description | TEXT | NULL | — | 담당업무 (임베딩 원문) |
| description_embedding | VECTOR(1536) | NULL | — | embed(description) |
| description_summary | TEXT | NULL | — | 담당업무 LLM 요약 (프론트 표시용) |

---

### 2.6 `category_master`

**설명**: ACW 카드 작성 시 분류 드롭다운 시드 데이터. 상담 분류 체계 관리.  
**데이터 출처**: 수동 정의

| 컬럼명 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | SERIAL | NOT NULL | auto | PK |
| category | VARCHAR(50) | NOT NULL | — | 카테고리: `'감염병'` \| `'접수처리'` \| `'범위외'` |
| major | VARCHAR(100) | NOT NULL | — | 대분류 (예: `'감염병 정보 문의'`, `'행정처리'`) |
| mid | VARCHAR(100) | NOT NULL | — | 중분류 (예: `'감염병기본정보'`, `'권한관리'`) |

> UNIQUE 제약: (category, major, mid) 조합 유일

**시드 데이터 (17행)**

| category | major | mid |
| --- | --- | --- |
| 감염병 | 감염병 정보 문의 | 감염병기본정보 |
| 감염병 | 감염병 정보 문의 | 증상·건강상태 |
| 감염병 | 감염병 정보 문의 | 소독·위생 |
| 감염병 | 감염병 정보 문의 | 독감·계절질환 |
| 감염병 | 감염병 정보 문의 | 백신 |
| 감염병 | 감염병 정보 문의 | 치료제·의약품 |
| 감염병 | 감염병 정보 문의 | 예방수칙·거리두기 |
| 감염병 | 감염병 정보 문의 | 항균·방역용품 |
| 감염병 | 감염병 지침 문의 | 감염병신고안내 |
| 감염병 | 해외/검역 정보 문의 | 여행·입국 |
| 감염병 | 감염병 통계·현황 | 국내외발생현황 |
| 접수처리 | 행정처리 | 권한관리 |
| 접수처리 | 행정처리 | 시스템오류 처리 |
| 접수처리 | 행정처리 | 환자정보확인 |
| 접수처리 | 행정처리 | 감염병신고 접수 |
| 접수처리 | 행정처리 | 기타행정처리 |
| 범위외 | 범위외 | 범위외 |

**category 분류 기준**

| category | 적용 조건 | is_oos / oos_type |
| --- | --- | --- |
| `감염병` | 감염병 관련 정상 상담 | `is_oos=false` |
| `접수처리` | 시스템 신고·이관 등 행정처리 | `is_oos=true`, `oos_type='action_required'` |
| `범위외` | 감염병과 무관한 문의 | `is_oos=true`, `oos_type='unrelated'` |

---

## 3. 인덱스 정의서

| 인덱스명 | 테이블 | 컬럼 | 종류 | 생성 이유 |
| --- | --- | --- | --- | --- |
| `idx_kc_embedding` | knowledge_chunks | embedding | ivfflat (cosine) | STEP 2-A 벡터 유사도 검색 |
| `idx_kc_source_category` | knowledge_chunks | source_category | B-tree | disease/system 필터링 |
| `idx_kc_knowledge_type` | knowledge_chunks | knowledge_type | B-tree | 타입별 조회 |
| `idx_kc_disease_name` | knowledge_chunks | disease_name | B-tree | 질병명 필터링 (STEP 2-A) |
| `idx_kc_data_id` | knowledge_chunks | data_id | B-tree | 소스별 관리/재적재 |
| `idx_acw_q_embedding` | acw_cards | q_embedding | ivfflat (cosine) | STEP 2-B 유사사례 검색 |
| `idx_acw_source` | acw_cards | source | B-tree | system/ai_hub 구분 |
| `idx_acw_disease_name` | acw_cards | disease_name | B-tree | 질병별 필터링 |
| `idx_acw_created_at` | acw_cards | created_at DESC | B-tree | 최신순 정렬 |
| `idx_ta_embedding` | transfer_agencies | description_embedding | ivfflat (cosine) | STEP 2-C 이관기관 검색 |
| `idx_ta_category` | transfer_agencies | category | B-tree | 기관 분류 조회 |

**ivfflat 설정**

| 테이블 | lists 값 | 근거 |
| --- | --- | --- |
| knowledge_chunks | 100 | 예상 행 수 4,000~6,000 (권장: √N) |
| acw_cards | 100 | 향후 증가 고려 |
| transfer_agencies | 50 | 소규모 (~100건) |

---

## 4. 관계 정의서

| 관계 | 부모 테이블 | 자식 테이블 | 컬럼 | 카디널리티 | 비고 |
| --- | --- | --- | --- | --- | --- |
| 상담사 → 통화 | agents | calls | agent_id | 1 : N | |
| 상담사 → ACW | agents | acw_cards | agent_id | 1 : N | ai_hub 행은 NULL |
| 통화 → ACW | calls | acw_cards | call_id | 1 : 1 | UNIQUE, ai_hub 행은 NULL |
| 분류 → ACW | category_master | acw_cards | — | 논리적 참조 | FK 없음, 드롭다운 시드 역할 |

**FK 없는 테이블**

| 테이블 | 이유 |
| --- | --- |
| knowledge_chunks | 독립 RAG 저장소, 런타임 벡터 검색만 사용 |
| transfer_agencies | 독립 이관기관 저장소, 런타임 벡터 검색만 사용 |

---

## 5. 데이터 흐름

### 5.1 사전 적재 (전처리 스크립트)

```
DATA-001~007  →  [전처리: chunk_text/embed_text 생성, 임베딩]     →  knowledge_chunks (disease_guideline, DATA-003 미적재)
DATA-008      →  [전처리: 감염병 카테고리 필터, Q 추출]           →  knowledge_chunks (faq, disease+system)
DATA-009      →  [전처리: 섹션 분리, 질병명 정제]                 →  knowledge_chunks (disease_info)
DATA-010      →  [전처리: 감염병포털 FAQ 파싱, Q 추출]            →  knowledge_chunks (faq, disease+system)
DATA-011~014  →  [전처리: 시스템 매뉴얼/지침 청킹, 임베딩]        →  knowledge_chunks (system_manual)
DATA-015      →  [전처리: 연락처 파싱, 임베딩]                    →  transfer_agencies (123건)
DATA-016      →  [전처리: 대화셋 그룹핑, Q/A 추출, 임베딩]        →  acw_cards (system 200 + ai_hub 3,544건)
수동 정의      →  [시드 스크립트]                                  →  category_master (17행)
수동 입력      →  [시드 스크립트]                                  →  agents
```

### 5.2 런타임 생성 (API)

```
통화 시작  →  calls INSERT (status='active')

STT 발화   →  서버 메모리 conversation_history 리스트에 append
              통화 종료 시 calls UPDATE conversation_history 1회 저장

STEP 1~3  →  ai_guidance 서버 캐시 구성
              {query, disease_name, answer, is_oos, oos_type, oos_reason, sources[]}
              (통화 중 ai_update 이벤트와 동시에 캐싱)

통화 종료  →  calls UPDATE (status='acw', ended_at, duration_sec)

transcript 변환  →  calls.conversation_history JSONB
                    → "[HH:MM:SS] 상담사/고객: ..." TEXT 변환
                    → acw_cards.transcript 저장
                    (ACW LLM 실행 전 선행 처리)

ACW LLM    →  입력 1: transcript (ACW-001 변환본)
              입력 2: ai_guidance 캐시
              출력: title, customer_type, customer_type_custom,
                    category, category_major, category_mid,
                    category_mid_list, disease_name, qa_summary,
                    ai_response_summary, is_transferred,
                    transfer_target, keywords
              ※ ai_guidance.answer·sources[]는 LLM 미생성, 캐시 직접 전달

ACW 완료   →  acw_cards INSERT (source='system')
              [LLM 생성]   title, customer_type 계열, category 계열,
                           disease_name, qa_summary, ai_response_summary,
                           is_transferred, transfer_target, keywords
              [캐시 직접]  ai_guidance JSONB
              [원본 보존]  transcript TEXT
              [상담사 입력] is_resolved, agent_used_ai, satisfaction, agent_memo
           →  q_embedding 생성 (qa_summary Q 파트)
           →  calls UPDATE (status='ended')
```

### 5.3 적재 순서

```
1단계  category_master     (시드 17행, FK 없음)
2단계  agents              (시드, FK 없음)
3단계  transfer_agencies   (DATA-015, FK 없음, 123건)
4단계  knowledge_chunks    (DATA-001~014, FK 없음, 3,058청크, DATA-003 제외)
5단계  acw_cards           (DATA-016, system 200건 + ai_hub 3,544건)
```

---

## 6. 설계 결정 사항

### 6.1 knowledge_chunks 단일 테이블 통합

**결정**: 감염병 지침, FAQ, 크롤링, 시스템 매뉴얼을 별도 테이블로 분리하지 않고 단일 `knowledge_chunks` 테이블로 통합

**근거**
- RAG 검색(STEP 2-A)은 소스 타입 구분 없이 의미 유사도만으로 검색
- 동일 임베딩 모델 사용 시 이질적 문서도 동일한 의미 공간에 투영됨 (Gao et al., RAG Survey 2024)
- 테이블 분리 시 UNION ALL 쿼리 필요, 단일 테이블이 쿼리 단순화에 유리
- `knowledge_type`, `source_category` 컬럼으로 타입 구분 가능

**고려한 대안**: disease_knowledge / system_knowledge 분리  
**기각 이유**: Option B 라우팅 채택(통합 검색)으로 분리 이점 소멸

---

### 6.2 embed_text 컬럼 분리

**결정**: `chunk_text`(GPT 전달용)와 `embed_text`(임베딩용)를 별도 컬럼으로 분리

**근거**
- FAQ의 경우 Q+A 전체보다 Q만 임베딩할 때 검색 정확도 향상
- 긴 답변 텍스트가 질문 벡터를 희석시키는 문제 방지
- 향후 임베딩 재생성 시 embed_text 기준으로 명확하게 처리 가능

---

### 6.3 disease_master 테이블 제거

**결정**: 별도 `disease_master` 테이블 미생성

**근거**
- 질병 기본정보(정의, 임상증상 등)는 DATA-009 청크로 `knowledge_chunks`에 포함
- 질병명 자동완성은 `SELECT DISTINCT disease_name FROM knowledge_chunks WHERE source_category = 'disease'`로 대체 가능
- ICD 코드 등 구조화 메타는 현재 시스템 기능에서 직접 사용되지 않음

---

### 6.4 acw_cards source 컬럼으로 system/ai_hub 통합 관리

**결정**: 실제 통화 후처리(`system`)와 시연용 AI Hub 데이터(`ai_hub`)를 단일 `acw_cards` 테이블에서 관리

**근거**
- 유사사례 검색(STEP 2-B)이 두 소스를 동시에 검색
- `source` 컬럼으로 명확히 구분 가능
- ai_hub 데이터는 NULL 필드를 임의값으로 채워 적재 (시연용)

---

### 6.5 ai_guidance 컬럼 설계

**결정**: ACW 카드에 `ai_guidance JSONB` 컬럼을 추가하여 통화 중 AI 안내 카드 내용(query, disease_name, answer, is_oos, oos_type, oos_reason, sources[])을 영속화

**근거**
- AI 안내 카드 내용(RAG 답변, 참조 출처)은 상담사 화면에만 표시되며 transcript에 포함되지 않음. ACW LLM이 `ai_response_summary`를 생성하려면 이 데이터가 필수
- RAGAS(Es et al., 2023) Faithfulness 지표 산출을 위해 `(query, answer, sources)` 트리플 저장이 필요
- Gao et al.(2024) RAG Survey에서 프로덕션 RAG 시스템의 `(query, retrieved_docs, generated_answer)` 로깅을 권장
- `disease_name`은 STEP 1 출력에 이미 포함되어 있어 ACW LLM 재추출 없이 직접 사용 가능

**ACW LLM 입력 개선 효과**

| ACW 필드 | 기존 (transcript만) | 변경 후 (+ ai_guidance) |
| --- | --- | --- |
| `disease_name` | transcript에서 재추출 | `ai_guidance.disease_name` 직접 복사 |
| `category` | transcript 기반 추론 | `ai_guidance.is_oos`로 즉시 확정 |
| `ai_response_summary` | 생성 불가 (transcript에 없음) | transcript + ai_guidance 전체 기반 3-section 서술형 생성 (고객문의/AI·상담사안내/처리결과) |
| `keywords` | raw 발화 기반 추출 | 정제된 query + answer 기반 추출 |

**추가 활용**
- 오프라인 RAG 품질 평가 (Faithfulness, Context Precision)
- 지침 변경 시 영향 범위 분석 (`sources[].data_id` 기준)
- 향후 RAG 파인튜닝 학습 데이터셋 구축

**고려한 대안**: 별도 컬럼 분리 (`ai_query`, `ai_answer`, `ai_sources`)  
**기각 이유**: 필드 수 증가 대비 이점 없음. is_oos 분기에 따라 null 필드가 달라지는 구조라 JSONB 단일 컬럼이 유연성 측면에서 유리

---

*DB 설계서 v2.1 — 2026-05-06*

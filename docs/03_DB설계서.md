# 데이터베이스 설계서 v3.0
## 질병관리청 1339 콜센터 AI 지원 시스템

> 작성일: 2026-05-05
> v2.1 수정 (2026-05-06): username 컬럼 추가, oos_type 추가, category_master 재정의
> v3.0 수정 (2026-06-10): PostgreSQL 16 로컬 → **Supabase 배포 환경**으로 변경, knowledge_chunks 스키마 정리
> v3.1 수정 (2026-06-10): knowledge_chunks 전체 재적재 완료, DATA-011 재정의 (AI Hub Q&A), notice_banners 제거

---

## 1. 개요

### 1.1 시스템 목적
질병관리청 1339 콜센터 상담사가 실시간 통화 중 AI 안내, 유사사례, 이관기관 정보를 즉시 참조할 수 있도록 지원하는 RAG 기반 AI 시스템의 데이터베이스.

### 1.2 DB 선택 근거

| 항목 | 선택 | 근거 |
| --- | --- | --- |
| 플랫폼 | **Supabase** | PostgreSQL 완전 호환, pgvector 내장 지원, 별도 서버 설정 없이 즉시 배포 가능, 무료 티어로 프로토타입 운영 가능 |
| RDBMS | PostgreSQL (Supabase 내장) | 안정성, JSONB 지원, pgvector 확장 지원 |
| 벡터 확장 | pgvector | 별도 벡터DB 없이 RDBMS와 통합 관리, 운영 복잡도 감소 |
| 임베딩 모델 | text-embedding-3-small (1536d) | OpenAI 공식 권장, 비용/성능 균형 |
| 인덱스 | ivfflat (cosine) | ANN 근사 검색, 대용량 벡터 검색 성능 확보 |

### 1.3 전체 테이블 목록

| # | 테이블명 | 설명 | 데이터 출처 |
| --- | --- | --- | --- |
| 1 | `agents` | 상담사 계정 관리 | 수동 입력 |
| 2 | `calls` | 통화 세션 | 시스템 자동 생성 |
| 3 | `acw_cards` | ACW 후처리 카드 + 유사사례 | DATA-016 (system + ai_hub) |
| 4 | `knowledge_chunks` | 통합 RAG 지식 청크 (4,911건) | DATA-001~011 |
| 5 | `transfer_agencies` | 이관기관 정보 (33건) | rebuild_transfer_agencies.py |
| 6 | `category_master` | ACW 분류 시드 | 수동 정의 |
| 7 | `kdca_notices` | 질병관리청 보도자료 크롤링 | kdca_crawler.py 자동 수집 |

---

## 2. 테이블 정의서

### 2.1 `agents`

**설명**: 상담사 계정 정보 저장. 로그인, 권한 관리, 통화/ACW 이력 연결에 사용.

| 컬럼명 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| agent_id | SERIAL | NOT NULL | auto | PK |
| username | VARCHAR(50) | NOT NULL | — | 로그인 아이디 (UNIQUE) |
| name | VARCHAR(50) | NOT NULL | — | 상담사 이름 |
| password_hash | VARCHAR(255) | NOT NULL | — | bcrypt 해시 |
| created_at | TIMESTAMP | NOT NULL | now() | 생성일 |

---

### 2.2 `calls`

**설명**: 상담사와 고객 간 통화 세션 정보.

| 컬럼명 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| call_id | SERIAL | NOT NULL | auto | PK |
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

**설명**: 통화 종료 후 상담사가 작성하는 후처리 카드. 유사사례 검색(STEP 2-B) 소스로도 활용.

**데이터 출처 2종**

| source 값 | 출처 | 설명 |
| --- | --- | --- |
| `'system'` | 실제 통화 후 상담사 작성 | call_id, agent_id 필수 |
| `'ai_hub'` | DATA-016 AI Hub 상담내역 | call_id, agent_id NULL, 시연용 |

| 컬럼명 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| acw_id | SERIAL | NOT NULL | auto | PK |
| call_id | INT | NULL | — | FK → calls.call_id (UNIQUE), ai_hub는 NULL |
| agent_id | INT | NULL | — | FK → agents.agent_id |
| source | VARCHAR(20) | NOT NULL | `'system'` | `'system'` \| `'ai_hub'` |
| title | VARCHAR(200) | NULL | — | 상담 제목 |
| customer_type | VARCHAR(20) | NULL | — | `'citizen'` \| `'medical'` \| `'other'` |
| customer_type_custom | VARCHAR(100) | NULL | — | 기타 고객 유형 직접 입력 |
| category | VARCHAR(50) | NULL | — | `'감염병'` \| `'접수처리'` \| `'범위외'` |
| category_major | VARCHAR(100) | NULL | — | 대분류 |
| category_mid | VARCHAR(100) | NULL | — | 중분류 |
| category_mid_list | JSONB | NULL | — | 복수 중분류 배열 |
| category_mid_custom | VARCHAR(100) | NULL | — | 기타 중분류 직접 입력 |
| disease_name | VARCHAR(100) | NULL | — | 관련 질병명 |
| qa_summary | JSONB | NULL | — | Q/A 요약 |
| transcript | TEXT | NULL | — | 전체 대화 원문 |
| ai_response_summary | TEXT | NULL | — | AI 상담 요약 (서술형 단락) |
| is_transferred | BOOLEAN | NULL | `false` | 이관 여부 |
| transfer_target | VARCHAR(200) | NULL | — | 이관 기관명 |
| keywords | JSONB | NULL | — | 키워드 배열 |
| satisfaction | SMALLINT | NULL | — | AI 답변 만족도 1~5 |
| agent_memo | TEXT | NULL | — | 상담사 메모 |
| is_resolved | BOOLEAN | NULL | — | 해결 여부 |
| agent_used_ai | VARCHAR(20) | NULL | — | `'yes'` \| `'partial'` \| `'no'` |
| q_embedding | VECTOR(1536) | NULL | — | qa_summary Q 임베딩 (STEP 2-B 검색 대상) |
| acw_started_at | TIMESTAMP | NULL | — | ACW 시작 시각 |
| acw_ended_at | TIMESTAMP | NULL | — | ACW 종료 시각 |
| acw_duration_sec | INT | NULL | — | ACW 소요 시간(초) |
| created_at | TIMESTAMP | NOT NULL | `now()` | 생성일 |
| ai_guidance | JSONB | NULL | — | 통화 중 AI 안내 전체 내용 (STEP 1~3 결과) |

**ai_guidance JSONB 구조**

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
    { "chunk_id": 42, "document_title": "2026년 코로나19 관리지침", "section_title": "격리 기간 기준", "data_id": "DATA-001" }
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

**qa_summary JSONB 구조**
```json
[
  { "q": "코로나19 격리기간이 어떻게 되나요?", "a": "확진일로부터 7일 격리 권고입니다." }
]
```

---

### 2.4 `knowledge_chunks`

**설명**: RAG 검색(STEP 2-A)을 위한 통합 지식 청크 저장소. 감염병 지침, 크롤링 정보, FAQ, 시스템 매뉴얼을 단일 테이블에 통합 관리.

**RAG 검색 흐름**
```
고객 발화 → STEP 1 (LLM 판정, query·disease_name 추출)
          → 쿼리 임베딩 (text-embedding-3-small)
          → STEP 2-A: knowledge_chunks Hybrid RAG (is_oos=false 시만 실행)
              ① Dense 검색 (NumPy 코사인 유사도, 인메모리 캐시)
                 - 서버 기동 후 첫 RAG 요청 시 knowledge_chunks 전체 로드 (lazy load)
                 - disease_name 있으면 감염병 청크 프리필터
                 - source_category='system' 청크 항상 포함
              ② BM25 검색 (rank-bm25, 인메모리)
              ③ RRF (Reciprocal Rank Fusion): Dense + BM25 결과 병합
              ④ Cross-Encoder Reranking
                 (bongsoo/klue-cross-encoder-v1, sentence-transformers 설치 시 자동 활성화)
              → 최종 Top-3 청크 반환
          → STEP 3 (LLM 안내 생성, 검색된 chunk_text 컨텍스트로 활용)

※ knowledge_chunks 테이블은 초기 적재용 소스로 활용.
   실제 RAG 검색은 서버 기동 시 인메모리 캐시로 처리됨 (DB 직접 쿼리 없음).
```

**데이터 출처 (실제 적재 기준)**

| data_id | 문서명 | source_category | knowledge_type | 청크 수 |
| --- | --- | --- | --- | --- |
| DATA-001 | 2025년도 코로나19 관리지침 | `disease` | `disease_guideline` | 56 |
| DATA-002 | 법정감염병 진단검사 통합지침(제4-2판) | `disease` | `disease_guideline` | 296 |
| DATA-003 | 두창·에볼라 등 제1급 감염병 관리지침 | `disease` | `disease_guideline` | 169 |
| DATA-004 | 2026년 HIV/AIDS 관리지침 | `disease` | `disease_guideline` | 187 |
| DATA-005 | MERS·SARS 대응지침 | `disease` | `disease_guideline` | 280 |
| DATA-006 | 2026 국가결핵관리지침 | `disease` | `disease_guideline` | 414 |
| DATA-007 | 제1급감염병 바이러스성출혈열 대응지침 | `disease` | `disease_guideline` | 494 |
| DATA-008 | 질병관리청 FAQ | `disease` | `faq` | 164 |
| DATA-009 | 질병관리청 법정감염병 정보 (크롤링) | `disease` | `disease_info` | 1,082 |
| DATA-010 | 질병관리청 감염병포털 FAQ | `disease` | `faq` | 90 |
| DATA-011 | AI Hub 헬스케어 Q&A | `disease` | `faq` | 1,679 |

> **총 knowledge_chunks**: 4,911청크 (DATA-001~011)

| 컬럼명 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | SERIAL | NOT NULL | auto | PK |
| data_id | VARCHAR(20) | NOT NULL | — | `'DATA-001'` ~ `'DATA-014'` |
| source_category | VARCHAR(10) | NOT NULL | — | `'disease'` \| `'system'` |
| knowledge_type | VARCHAR(30) | NOT NULL | — | 아래 표 참고 |
| disease_name | VARCHAR(100) | NULL | — | 관련 질병명 (system_manual은 NULL 가능) |
| document_title | VARCHAR(300) | NULL | — | 문서 제목 |
| chapter | VARCHAR(200) | NULL | — | 챕터 |
| section_title | VARCHAR(300) | NULL | — | 섹션 제목 (FAQ는 질문 원문) |
| chunk_text | TEXT | NULL | — | step2_search.py 폴백 벡터 검색용 텍스트 |
| clean_content | TEXT | NULL | — | retrieval.py Hybrid RAG 메인 사용 텍스트 (정제본) |
| chunk_index | INT | NULL | `0` | 문서 내 청크 순번 (chunk_id로 활용) |
| embedding | VECTOR(1536) | NULL | — | clean_content 기반 임베딩 벡터 |

> **v3.0 변경**: 미사용 컬럼 6개 삭제 — `source_id`, `content`, `embed_text`, `keywords`, `source`, `section_category`

**knowledge_type 상세**

| knowledge_type | source_category | 데이터 |
| --- | --- | --- |
| `disease_guideline` | disease | DATA-001~007 |
| `disease_info` | disease | DATA-009 |
| `faq` | disease | DATA-008, 010, 011 |

---

### 2.5 `transfer_agencies`

**설명**: 이관 가능한 외부 기관 정보. STEP 2-C에서 키워드 매핑(TRANSFER_KEYWORD_MAP) 우선 → 임베딩 유사도 검색 폴백으로 적합 기관 추천.

> **데이터 건수**: `rebuild_transfer_agencies.py` 실행 기준 33건
> 유사도 임계값: `TRANSFER_THRESHOLD = 0.60`

| 컬럼명 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| agency_id | SERIAL | NOT NULL | auto | PK |
| category | VARCHAR(30) | NULL | — | `'관련 기관'` \| `'소속기관'` \| `'질병관리청 직원'` \| `'응급'` |
| org_name | VARCHAR(200) | NOT NULL | — | 기관명 |
| dept_name | VARCHAR(200) | NULL | — | 부서명 |
| phone | VARCHAR(100) | NULL | — | 전화번호 |
| description | TEXT | NULL | — | 담당업무 (임베딩 원문) |
| description_embedding | VECTOR(1536) | NULL | — | embed(description) |
| description_summary | TEXT | NULL | — | 담당업무 LLM 요약 (프론트 표시용) |

---

### 2.6 `category_master`

**설명**: ACW 카드 분류 드롭다운 시드 데이터.

| 컬럼명 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| id | SERIAL | NOT NULL | auto | PK |
| category | VARCHAR(50) | NOT NULL | — | `'감염병'` \| `'접수처리'` \| `'범위외'` |
| major | VARCHAR(100) | NOT NULL | — | 대분류 |
| mid | VARCHAR(100) | NOT NULL | — | 중분류 |

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

| category | is_oos / oos_type |
| --- | --- |
| `감염병` | `is_oos=false` |
| `접수처리` | `is_oos=true`, `oos_type='action_required'` |
| `범위외` | `is_oos=true`, `oos_type='unrelated'` |

---

### 2.7 `notice_banners`

**설명**: 대시보드 및 공지사항 화면 상단에 표시되는 지침 변경 알림 배너. 관리자가 API를 통해 등록/삭제.

| 컬럼명 | 타입 | NULL | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| banner_id | SERIAL | NOT NULL | auto | PK |
| message | TEXT | NOT NULL | — | 배너 내용 (예: "2026.06.01 코로나19 격리 지침 변경") |
| level | VARCHAR(20) | NOT NULL | `'info'` | `'info'` \| `'warning'` \| `'danger'` |
| created_at | TIMESTAMP | NOT NULL | `now()` | 등록일 |

> 조회 시 최신 1건만 반환 (`ORDER BY created_at DESC LIMIT 1`)

---

## 3. 인덱스 정의서

| 인덱스명 | 테이블 | 컬럼 | 종류 | 생성 이유 |
| --- | --- | --- | --- | --- |
| `idx_kc_embedding` | knowledge_chunks | embedding | ivfflat (cosine) | STEP 2-A 벡터 유사도 검색 |
| `idx_kc_source_category` | knowledge_chunks | source_category | B-tree | disease/system 필터링 |
| `idx_kc_knowledge_type` | knowledge_chunks | knowledge_type | B-tree | 타입별 조회 |
| `idx_kc_disease_name` | knowledge_chunks | disease_name | B-tree | 질병명 프리필터 (STEP 2-A) |
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
| transfer_agencies | 50 | 소규모 (~30건) |

---

## 4. 관계 정의서

| 관계 | 부모 | 자식 | 컬럼 | 카디널리티 | 비고 |
| --- | --- | --- | --- | --- | --- |
| 상담사 → 통화 | agents | calls | agent_id | 1:N | |
| 상담사 → ACW | agents | acw_cards | agent_id | 1:N | ai_hub 행은 NULL |
| 통화 → ACW | calls | acw_cards | call_id | 1:1 | UNIQUE, ai_hub 행은 NULL |
| 분류 → ACW | category_master | acw_cards | — | 논리적 참조 | FK 없음, 드롭다운 시드 |

**FK 없는 테이블**

| 테이블 | 이유 |
| --- | --- |
| knowledge_chunks | 독립 RAG 저장소, 런타임 벡터 검색만 사용 |
| transfer_agencies | 독립 이관기관 저장소, 런타임 벡터 검색만 사용 |
| notice_banners | 독립 운영 테이블, 다른 테이블과 연관 없음 |

---

## 5. 데이터 흐름

### 5.1 사전 적재 (전처리 스크립트)

```
DATA-001~007  →  청킹 + 임베딩  →  knowledge_chunks (disease_guideline)
DATA-008      →  FAQ 파싱 + Q 임베딩  →  knowledge_chunks (faq)
DATA-009      →  섹션 분리 + 임베딩  →  knowledge_chunks (disease_info)
DATA-010      →  FAQ 파싱 + Q 임베딩  →  knowledge_chunks (faq)
DATA-011~014  →  청킹 + 임베딩  →  knowledge_chunks (system_manual)
DATA-015      →  연락처 파싱 + 임베딩  →  transfer_agencies (123건)
DATA-016      →  대화셋 그룹핑 + Q/A 추출 + q_embedding  →  acw_cards (3,744건)
수동 정의  →  category_master (17행)
수동 입력  →  agents
```

### 5.2 런타임 생성 (API)

```
통화 시작
  → calls INSERT (status='active')
  → WS /ws/stt/{call_id} 연결

Deepgram Nova-3 STT (실시간)
  → 발화 텍스트 + 화자 레이블 → 의료 도메인 정규화
  → 서버 메모리 conversation_history append
  → WebSocket push: conversation_update

STEP 1 (gpt-4o-mini JSON mode)
  → input: conversation_history
  → output: {ready, is_oos, oos_type, oos_reason, disease_name, query}

STEP 2 (병렬, ready=true 시)
  → 쿼리 임베딩 (text-embedding-3-small) → query_vector
  → 2-A: knowledge_chunks 벡터 검색 (is_oos=false 시만, cosine≥0.70, Top-3)
  → 2-B: acw_cards q_embedding 검색 (항상, cosine≥0.70, Top-3)
  → 2-C: transfer_agencies 검색 (항상, cosine≥0.70, Top-3)

STEP 3 (gpt-4o-mini, is_oos=false + 2-A결과>0 시)
  → input: knowledge_chunks.chunk_text + conversation_history
  → output: answer (1~3문장)
  → ai_guidance 캐시 구성 (서버 메모리)

통화 종료
  → calls UPDATE (status='acw', ended_at, duration_sec, conversation_history)
  → acw_cards INSERT (transcript 변환 저장)

ACW LLM (gpt-4o-mini, 1회)
  → input: transcript + ai_guidance 캐시
  → output: title, customer_type, category 계열, disease_name,
            qa_summary, ai_response_summary, is_transferred, keywords

ACW 완료
  → acw_cards UPDATE (모든 필드 저장)
  → q_embedding 생성 (qa_summary Q → text-embedding-3-small)
  → calls UPDATE (status='ended')
```

### 5.3 적재 순서

```
1단계  category_master     (17행, FK 없음)
2단계  agents              (시드, FK 없음)
3단계  transfer_agencies   (DATA-015, 123건)
4단계  knowledge_chunks    (DATA-001~014, 3,058청크, DATA-003 제외)
5단계  acw_cards           (DATA-016, system 200건 + ai_hub 3,544건)
```

---

## 6. 설계 결정 사항

### 6.1 knowledge_chunks 단일 테이블 통합

- 감염병 지침/FAQ/크롤링/시스템 매뉴얼을 단일 테이블로 통합
- RAG 검색은 소스 타입 구분 없이 의미 유사도만으로 검색
- `knowledge_type`, `source_category` 컬럼으로 타입 구분 가능

### 6.2 embed_text / chunk_text 분리

- `chunk_text`: GPT STEP 3에 컨텍스트로 전달 (Q+A 전체)
- `embed_text`: 임베딩 대상 텍스트 (FAQ는 Q만, 나머지는 chunk_text 동일)
- FAQ Q만 임베딩해야 사용자 질문 ↔ FAQ 질문 유사도가 정확히 측정됨

### 6.3 acw_cards source 컬럼으로 system/ai_hub 통합

- 실제 통화(`system`)와 시연용 AI Hub 데이터(`ai_hub`)를 단일 테이블 관리
- STEP 2-B 유사사례 검색이 두 소스를 동시에 검색

### 6.4 ai_guidance JSONB 컬럼 설계

- 통화 중 AI 안내 내용(query, disease_name, answer, is_oos, oos_type, oos_reason, sources[])을 acw_cards에 영속화
- ACW LLM이 `ai_response_summary` 생성 시 필수 입력
- RAG 품질 평가 데이터셋으로 활용 가능 (query, answer, sources 트리플)

---

*DB 설계서 v3.0 — 2026-06-10*

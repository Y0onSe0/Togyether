# 시스템 아키텍처 문서 v1.0
## 질병관리청 1339 콜센터 AI 지원 시스템

> 작성일: 2026-06-10

---

## 1. 시스템 개요

질병관리청 1339 콜센터 상담사를 위한 **실시간 AI 상담 지원 시스템**.
상담 중 고객 발화를 실시간으로 STT 변환하고, RAG 기반 AI 안내·유사사례·이관기관 정보를 즉시 제공한다.
통화 종료 후 ACW 카드를 자동 생성하여 상담사의 후처리 부담을 줄인다.

---

## 2. 전체 시스템 구성도

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              사용자 (상담사)                                │
│                          브라우저 (React + Vite)                           │
│                                                                            │
│  SCR-006       SCR-003           SCR-004       SCR-005       SCR-007      │
│  [공지사항]   [상담사 메인]      [ACW 작성]   [대시보드]   [상담 내역]    │
│                  ↕ WebSocket                                               │
└──────────────────────┬────────────────────────────────────────────────────┘
                       │ HTTPS / WSS
                       ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                         백엔드 (FastAPI)                                    │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │                       REST API Routers                                │ │
│  │  auth · agents · calls · acw · dashboard · disease_stats · categories│ │
│  │  notice · quarantine · vaccine · history                             │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │       WebSocket /ws/stt/{call_id} (STT) + /ws/call/{call_id} (AI)     │ │
│  │                                                                      │ │
│  │  PCM 오디오 수신                                                      │ │
│  │    → VAD (Silero VAD)                                                │ │
│  │    → Deepgram Nova-3 STT ──────────────────────► Deepgram API       │ │
│  │    → 의료 도메인 텍스트 정규화                                        │ │
│  │    → conversation_history 누적                                       │ │
│  │                                                                      │ │
│  │  STEP 1: gpt-4.1-mini ─────────────────────────► OpenAI API         │ │
│  │    → {ready, is_oos, oos_type, disease_name, query}                 │ │
│  │                                                                      │ │
│  │  STEP 2 (병렬):                                                      │ │
│  │    2-A: Hybrid RAG (Dense+BM25+RRF+Cross-Encoder, 인메모리)         │ │
│  │    2-B: 유사사례 검색 ───────────────── 현재 비활성화                │ │
│  │    2-C: 이관기관 (키워드매핑 우선 → 임베딩 폴백)                    │ │
│  │                                                                      │ │
│  │  STEP 3: gpt-4o-mini ──────────────────────────► OpenAI API         │ │
│  │    → answer (1~3문장 AI 안내)                                        │ │
│  │                                                                      │ │
│  │  WebSocket Push → 클라이언트                                          │ │
│  │    conversation_update / ai_update / similar_cases / transfer_suggestion│ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
└──────────────────────┬─────────────────────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────────────┐
         ▼             ▼                     ▼
┌─────────────┐  ┌───────────────┐  ┌─────────────────────┐
│  Supabase   │  │  OpenAI API   │  │  공공데이터포털 API  │
│  PostgreSQL │  │  gpt-4o-mini  │  │  검역관리지역        │
│  + pgvector │  │  text-emb-3s  │  │  예방접종 정보       │
│             │  └───────────────┘  │  질병관리청 통계     │
│  7개 테이블 │                     └─────────────────────┘
│  3,058 청크 │  ┌───────────────┐
│  3,744 사례 │  │ Deepgram API  │
│  123개 기관 │  │ Nova-3 STT    │
└─────────────┘  └───────────────┘
```

---

## 3. 기술 스택

### 3.1 Frontend

| 항목 | 기술 | 버전 |
| --- | --- | --- |
| 프레임워크 | React | **19.x** |
| 빌드 도구 | Vite | **8.x** |
| 언어 | JavaScript (JSX) | ES2022+ |
| 라우팅 | React Router DOM | **7.x** |
| 스타일 | Tailwind CSS | **4.x** |
| 차트 | Recharts | **3.x** |
| 아이콘 | lucide-react | 1.x |
| 상태 관리 | React Hooks (useState, useEffect) | — |
| HTTP 클라이언트 | Axios | **1.x** |
| 실시간 통신 | WebSocket API (브라우저 내장) | — |
| 음성 수집 | Web Audio API (PCM 16kHz Int16 변환) | — |

### 3.2 Backend

| 항목 | 기술 | 버전 |
| --- | --- | --- |
| 프레임워크 | FastAPI | 0.115.12 |
| ASGI 서버 | Uvicorn | 0.34.0 |
| 언어 | Python | 3.11 |
| DB 드라이버 | psycopg2-binary | 2.9.10 |
| 벡터 라이브러리 | pgvector | 0.3.6 |
| AI/ML | sentence-transformers | 3.4.1 |
| AI/ML | torch + torchaudio | 2.6.0 |
| AI/ML | onnxruntime | 1.24.4 |
| VAD | silero-vad | 5.1.2 |
| BM25 | rank-bm25 | 0.2.2 |
| 인증 | JWT (python-jose) | — |
| 암호화 | bcrypt | — |

### 3.3 외부 서비스

| 서비스 | 용도 | 모델/버전 |
| --- | --- | --- |
| OpenAI API | LLM 추론 STEP 1 판정 | gpt-4.1-mini |
| OpenAI API | LLM 추론 STEP 3 안내 생성·ACW | gpt-4o-mini |
| OpenAI API | 텍스트 임베딩 | text-embedding-3-small (1536d) |
| Deepgram API | 실시간 STT | Nova-3 (single/dual 모드) |
| 공공데이터포털 | 검역관리지역 정보 | — |
| 공공데이터포털 | 예방접종 정보 | — |
| 공공데이터포털 | 질병관리청 감염병 통계 | — |

### 3.4 데이터베이스 / 인프라

| 항목 | 기술 | 설명 |
| --- | --- | --- |
| DB 플랫폼 | **Supabase** | PostgreSQL 완전 호환, pgvector 내장 |
| 벡터 검색 | pgvector (ivfflat, cosine) | knowledge_chunks, acw_cards, transfer_agencies |
| 컨테이너 | Docker | 로컬 개발 환경용 PostgreSQL + pgvector |

---

## 4. RAG 파이프라인 상세

```
┌─────────────────────────────────────────────────────────────────┐
│                     RAG 파이프라인                               │
│                                                                 │
│  [고객 발화]                                                    │
│      │                                                          │
│      ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  STEP 1: gpt-4o-mini (통합 판정, JSON mode)              │   │
│  │                                                         │   │
│  │  입력: conversation_history 전체                         │   │
│  │  출력:                                                   │   │
│  │    ready: 질문 의도 파악 여부                             │   │
│  │    is_oos: 업무 범위 외 여부                              │   │
│  │    oos_type: unrelated | action_required | null          │   │
│  │    oos_reason: 범위 외 사유 1줄                           │   │
│  │    disease_name: 감염병명 (프리필터용)                    │   │
│  │    query: 검색용 정제 쿼리                                │   │
│  └─────────────────────────────────────────────────────────┘   │
│      │                                                          │
│      ├── ready=false → 다음 발화 대기                           │
│      │                                                          │
│      ▼ ready=true                                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  쿼리 임베딩: text-embedding-3-small → query_vector      │   │
│  └─────────────────────────────────────────────────────────┘   │
│      │                                                          │
│      ▼                                                          │
│  ┌──────────────────────── 병렬 실행 ─────────────────────┐   │
│  │                                                         │   │
│  │  2-A: knowledge_chunks Hybrid RAG (is_oos=false 시만)   │   │
│  │    ① Dense 검색 (NumPy 코사인, 인메모리 캐시)            │   │
│  │       - 서버 기동 후 첫 RAG 요청 시 DB 전체 청크 로드    │   │
│  │       - disease_name 있으면 감염병 청크 프리필터         │   │
│  │       - system 청크(source_category='system') 항상 포함  │   │
│  │    ② BM25 검색 (rank-bm25, 인메모리)                    │   │
│  │    ③ RRF (Reciprocal Rank Fusion) 병합                  │   │
│  │    ④ Cross-Encoder Reranking                            │   │
│  │       (bongsoo/klue-cross-encoder-v1,                   │   │
│  │        sentence-transformers 설치 시 자동 활성화)        │   │
│  │    → 최종 Top-3 청크 반환                                │   │
│  │                                                         │   │
│  │  2-B: acw_cards 유사사례 검색 ── 현재 비활성화           │   │
│  │    (ws.py에서 asyncio.sleep(0)으로 스킵 처리)            │   │
│  │                                                         │   │
│  │  2-C: transfer_agencies 이관기관 검색 (항상)             │   │
│  │    ① 키워드 매핑 우선 (TRANSFER_KEYWORD_MAP)             │   │
│  │       - 응급(119), 에이즈, 결핵 등 하드코딩 즉시 매핑    │   │
│  │    ② 임베딩 검색 폴백                                    │   │
│  │       - description_embedding cosine 유사도 Top-3       │   │
│  │    → WebSocket push: transfer_suggestion                │   │
│  └─────────────────────────────────────────────────────────┘   │
│      │                                                          │
│      ├── is_oos=true → ai_update(status:oos) push              │
│      ├── 2-A 결과=0  → ai_update(status:no_result) push        │
│      │                                                          │
│      ▼ is_oos=false + 2-A 결과 > 0                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  STEP 3: gpt-4o-mini (AI 안내 생성)                      │   │
│  │                                                         │   │
│  │  입력: knowledge_chunks 검색 결과 (Top-3)               │   │
│  │        + conversation_history                           │   │
│  │  출력: answer (1~3문장, hallucination 방지)              │   │
│  │                                                         │   │
│  │  → ai_guidance 캐시 구성 (서버 메모리)                   │   │
│  │  → WebSocket push: ai_update(status:success)            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. STT 파이프라인 상세

```
브라우저 Web Audio API
  → PCM 16kHz mono 16-bit 오디오 청크
  → WebSocket binary frame 전송

서버 stt.py (/ws/stt/{call_id}?token=...&mode=single|dual)
  → Silero VAD: 발화 구간 감지
  → Deepgram Nova-3 API 스트리밍 전송
      single 모드: diarize 기반 화자 분리
      dual 모드:   채널 분리 (채널 0=고객, 1=상담사)
  → 의료 도메인 텍스트 정규화
      - 한글 숫자 변환 (예: "이십일" → "21")
      - 오인식 단어 치환 (도메인 특화 사전)
  → conversation_history append
  → WebSocket push: conversation_update {speaker, text, timestamp}
  → STEP 1 파이프라인 트리거
```

---

## 6. ACW 파이프라인 상세

```
통화 종료
  → PATCH /api/calls/{call_id}/end
      calls 테이블: status='acw', ended_at, duration_sec 업데이트
      conversation_history → DB 저장

ACW 화면 마운트 (SCR-004)
  [Step A] GET /api/acw/{call_id}/init
    → conversation_history JSONB
      → "[HH:MM:SS] 고객/상담사: ..." TEXT 변환
      → acw_cards.transcript 저장
    → ai_guidance 캐시 조회
      → Section 4 표시 (읽기 전용)

  [Step B] POST /api/acw/{call_id}/generate
    입력: transcript + ai_guidance 캐시
    gpt-4o-mini JSON mode 1회 호출
    출력:
      title / customer_type / category 계열 / disease_name
      qa_summary / ai_response_summary
      is_transferred / keywords

  [Step C] GET /api/categories
    → 카테고리 드롭다운 데이터 로드

상담사 검토 및 수정
  → [임시저장] PUT /api/acw/{call_id} (필수값 미검증)
  → [완료] PUT /api/acw/{call_id}
      acw_cards 전체 UPDATE
      qa_summary Q → text-embedding-3-small → q_embedding 저장
      calls.status = 'ended' 업데이트
      → SCR-003 (대기 중) 복귀
```

---

## 7. 데이터 적재 구조

```
[전처리 스크립트]              [Supabase DB]

DATA-001~011 ──────────────► knowledge_chunks (4,911청크)
  docling(코랩) → MD 파싱 → JSON 변환
  clean_content 정제 + chunk_text 구성
  text-embedding-3-small 임베딩 → embedding 컬럼
  ivfflat 인덱스

DATA-015 ───────────────────► transfer_agencies (33건, rebuild 기준)
  연락처 파싱
  description 임베딩

DATA-016 ───────────────────► acw_cards
  AI Hub 상담내역
  qa_summary Q 임베딩 → q_embedding
  source='ai_hub'

수동 정의 ──────────────────► category_master

수동 입력 ──────────────────► agents (10명, agent01~10)
```

---

## 8. 배포 환경

| 구분 | 환경 | 상세 |
| --- | --- | --- |
| DB | **Supabase** (클라우드) | PostgreSQL + pgvector, 프로젝트 단위 배포 |
| 백엔드 | 로컬 또는 클라우드 서버 | `uvicorn app.main:app --reload` |
| 프론트엔드 | 로컬 개발 서버 | `npm run dev` (Vite, localhost:5173) |
| 로컬 개발 DB | Docker | `docker/` 내 PostgreSQL + pgvector 컨테이너 |

### 환경변수 (.env)

```env
DATABASE_URL=postgresql+asyncpg://[user]:[password]@[supabase-host]:5432/postgres
OPENAI_API_KEY=sk-...
JWT_SECRET_KEY=...
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=480
DEEPGRAM_API_KEY=...
HUGGINGFACE_TOKEN=...
DATA_GO_KR_API_KEY=...
QUARANTINE_API_URL=https://apis.data.go.kr/...
```

---

## 9. 프론트엔드 파일 구조

```
frontend/
├── index.html
├── package.json
├── vite.config.js
├── eslint.config.js
│
└── src/
    ├── main.jsx                    # 앱 진입점, StrictMode + createRoot
    ├── App.jsx                     # React Router 라우팅 설정, PrivateRoute
    ├── index.css                   # 전역 스타일
    │
    ├── pages/
    │   ├── Login.jsx               # SCR-001 로그인 (공개)
    │   ├── Register.jsx            # SCR-002 계정 생성 (공개)
    │   ├── Main.jsx                # SCR-003 상담사 메인 (대기/상담 중)
    │   ├── ACW.jsx                 # SCR-004 ACW 카드 작성
    │   ├── Dashboard.jsx           # SCR-005 대시보드
    │   ├── Notice.jsx              # SCR-006 공지사항 (로그인 후 진입점)
    │   └── History.jsx             # SCR-007 상담 내역
    │
    ├── components/
    │   ├── GNB.jsx                 # 상단 네비게이션 (로그아웃 팝오버)
    │   ├── LNB.jsx                 # 좌측 메뉴 (상담/대시보드/공지/내역)
    │   ├── AICard.jsx              # AI 안내 카드 (success/oos/no_result/error)
    │   ├── ChatPanel.jsx           # 실시간 대화 내역 말풍선
    │   ├── TransferCard.jsx        # 이관 기관 추천 카드
    │   ├── SimilarCasesCard.jsx    # 유사 상담 사례 카드 (AICard 내부 사용)
    │   └── SourceCarousel.jsx      # AI 답변 출처 캐러셀
    │
    ├── hooks/
    │   ├── useAuth.js              # JWT 토큰 관리, 로그인 상태
    │   ├── useSTT.js               # /ws/stt/{callId} 연결, PCM 오디오 전송
    │   └── useWebSocket.js         # /ws/call/{callId} 연결, AI 결과 수신
    │
    ├── api/
    │   ├── auth.js                 # login / logout / register
    │   ├── calls.js                # startCall / endCall
    │   ├── acw.js                  # initACW / generateACW / saveACW / getCategories
    │   ├── dashboard.js            # getDashboard / getDiseaseStats 계열
    │   └── notice.js               # getBanner / getPressReleases / getSimilarCases 등
    │
    └── assets/
        ├── hero.png                # 로그인 화면 히어로 이미지
        ├── react.svg               # Vite 템플릿 기본 파일 (미사용)
        └── vite.svg                # Vite 템플릿 기본 파일 (미사용)
```

> **삭제 후보**: `react.svg`, `vite.svg` — Vite 초기 템플릿 잔존 파일, 실제 코드에서 미사용

---

## 10. 외부 API 연동

| API | 용도 | 캐시 TTL | 엔드포인트 |
| --- | --- | --- | --- |
| 공공데이터포털 — 검역관리지역 | 해외 감염병 검역 정보 | 24시간 | `/api/quarantine/*` |
| 공공데이터포털 — 예방접종 | 예방접종 일정·대상 정보 | 24시간 | `/api/vaccine/search` |
| 공공데이터포털 — 감염병 통계 | 감염병별/성별/연령별 발생 통계, 조기경보 | 1시간 | `/api/disease-stats/*` |

---

*시스템 아키텍처 문서 v1.0 — 2026-06-10*

# API 설계서 v2.0
## 질병관리청 1339 콜센터 AI 지원 시스템

> 참조: 기능명세서 v4.0 · 화면설계서 v2.0 · DB 설계서 v2.0
> 작성일: 2026-05-05
> v1.1 수정: SCR 번호 전면 재정렬
> v1.2 수정: agents.username 분리 반영, ai_guidance에 oos_type 필드 추가
> v2.0 수정: STT Whisper → Deepgram Nova-3 (single/dual 모드), 신규 라우터 추가 (quarantine, vaccine, notice, history, disease_stats), SCR-006 Notice · SCR-007 History 추가, 알림 배너 DB 연동 반영

---

## 목차

1. [개요](#1-개요)
2. [전체 아키텍처](#2-전체-아키텍처)
3. [화면 ↔ API ↔ DB 연결 다이어그램](#3-화면--api--db-연결-다이어그램)
4. [실시간 파이프라인 흐름 (WebSocket)](#4-실시간-파이프라인-흐름-websocket)
5. [REST API 상세](#5-rest-api-상세)
6. [WebSocket 이벤트 명세](#6-websocket-이벤트-명세)
7. [FastAPI 파일 구조](#7-fastapi-파일-구조)
8. [공통 규칙](#8-공통-규칙)

---

## 1. 개요

| 항목 | 내용 |
|------|------|
| Base URL | `http://localhost:8000/api` |
| WebSocket | `ws://localhost:8000/ws` |
| 인증 방식 | JWT Bearer Token |
| 응답 형식 | `application/json` |
| DB | Supabase (PostgreSQL + pgvector) |
| LLM | gpt-4o-mini (STEP 1 · STEP 3 · ACW LLM) |
| 임베딩 | text-embedding-3-small (1536d) |
| STT | Deepgram Nova-3 (single / dual 채널) |

### 화면 목록 (화면설계서 v2.0 기준)

| 화면 ID | 화면명 | 접근 경로 |
|---------|--------|----------|
| SCR-001 | 로그인 | 진입점 |
| SCR-002 | 계정 생성 | SCR-001 → 계정 생성 링크 |
| SCR-003 | 상담사 메인 (대기 중 / 상담 중) | 로그인 성공 후 |
| SCR-004 | ACW 카드 작성 | 통화 종료 후 자동 전환 |
| SCR-005 | 대시보드 | LNB 메뉴 |
| SCR-006 | 공지사항 | LNB 메뉴 |
| SCR-007 | 상담 내역 | LNB 메뉴 |

### 화면 전환 흐름

```
[SCR-001 로그인]
    │ 성공
    ▼
[SCR-006 공지사항]  (로그인 후 진입점)
    │ LNB → 상담
    ▼
[SCR-003 대기 중]  ◄──────────────────────────────┐
    │ 상담 시작 버튼 (상태 전환, 화면 이동 없음)     │ ACW 저장 완료
    ▼                                              │
[SCR-003 상담 중]                                  │
    │ 통화 종료 (화면 이동)                         │
    ▼                                              │
[SCR-004 ACW 카드 작성] ────────────────────────────┘

[SCR-003/004/005/006/007] → GNB 상담사명 ▼ 팝오버 → 로그아웃 → [SCR-001]
[SCR-003/004/005/006/007] → LNB → [SCR-005 대시보드]
[SCR-003/004/005/006/007] → LNB → [SCR-006 공지사항]
[SCR-003/004/005/006/007] → LNB → [SCR-007 상담 내역]
[SCR-001] → 계정 생성 링크 → [SCR-002] → 완료 → [SCR-001]
```

### 엔드포인트 목록 요약

| 분류 | Method | Path | 화면 |
|------|--------|------|------|
| **인증** | POST | `/api/auth/login` | SCR-001 |
| | POST | `/api/auth/logout` | SCR-003/004/005 팝오버 |
| **계정** | POST | `/api/agents` | SCR-002 |
| | GET | `/api/agents/check-name` | SCR-002 (실시간 중복확인) |
| | GET | `/api/agents/me` | SCR-003/004/005 GNB |
| **통화** | POST | `/api/calls` | SCR-003 (상담 시작) |
| | PATCH | `/api/calls/{call_id}/end` | SCR-003 (통화 종료) |
| | GET | `/api/calls/{call_id}` | SCR-003 |
| **WebSocket STT** | WS | `/ws/stt/{call_id}` | SCR-003 상담 중 |
| **ACW** | GET | `/api/acw/{call_id}/init` | SCR-004 |
| | POST | `/api/acw/{call_id}/generate` | SCR-004 |
| | PUT | `/api/acw/{call_id}` | SCR-004 |
| | GET | `/api/acw/{call_id}` | SCR-004 |
| **대시보드** | GET | `/api/dashboard/my/today` | SCR-005 내 통계 탭 |
| | GET | `/api/dashboard/my/keywords` | SCR-005 내 통계 탭 |
| | GET | `/api/dashboard/my/summary` | SCR-005 내 통계 탭 |
| | GET | `/api/dashboard/my/weekly-trend` | SCR-005 내 통계 탭 |
| | GET | `/api/dashboard/all/summary` | SCR-005 전체 통계 탭 |
| | GET | `/api/dashboard/all/disease-trend` | SCR-005 전체 통계 탭 |
| | GET | `/api/dashboard/all/category-trend` | SCR-005 전체 통계 탭 |
| **감염병 통계** | GET | `/api/disease-stats/by-disease` | SCR-005 |
| | GET | `/api/disease-stats/by-gender` | SCR-005 |
| | GET | `/api/disease-stats/by-age` | SCR-005 |
| | GET | `/api/disease-stats/trend-with-calls` | SCR-005 |
| | GET | `/api/disease-stats/weekly-alert` | SCR-005 조기경보 |
| **카테고리** | GET | `/api/categories` | SCR-004 드롭다운 |
| **공지사항** | GET | `/api/notice/banner` | SCR-005/006 |
| | POST | `/api/notice/banner` | SCR-006 관리 |
| | DELETE | `/api/notice/banner/{banner_id}` | SCR-006 관리 |
| | GET | `/api/notice/stats` | SCR-006 |
| | GET | `/api/notice/press` | SCR-006 |
| | POST | `/api/notice/crawl` | SCR-006 |
| **검역** | GET | `/api/quarantine/country` | SCR-003 이관 카드 |
| | GET | `/api/quarantine/disease` | SCR-003 이관 카드 |
| | GET | `/api/quarantine/search` | SCR-003 이관 카드 |
| **예방접종** | GET | `/api/vaccine/search` | SCR-003 AI 카드 |
| **상담 내역** | GET | `/api/history` | SCR-007 |
| | GET | `/api/history/summary` | SCR-007 |
| | GET | `/api/history/{call_id}` | SCR-007 |

---

## 2. 전체 아키텍처

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Frontend  (React + Vite)                            │
│                                                                              │
│  SCR-001  SCR-002   SCR-003          SCR-004   SCR-005   SCR-006  SCR-007   │
│  [로그인][계정생성][상담사 메인]    [ACW 작성][대시보드][공지사항][상담내역] │
└────┬───────┬─────────┬────────────────────┬──────────┬───────────┬──────────┘
     │ HTTP  │ HTTP    │ HTTP + WS           │ HTTP     │ HTTP      │ HTTP
     ▼       ▼         ▼                    ▼          ▼           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        FastAPI  (app/main.py)                                │
│                                                                              │
│  /auth  /agents  /calls  /acw  /dashboard  /disease-stats  /categories      │
│  /notice  /quarantine  /vaccine  /history  /ws/stt                          │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                       Service / Pipeline Layer                        │   │
│  │  STEP 1: LLM 통합 판정 → STEP 2A/B/C 병렬 검색 → STEP 3: AI 안내    │   │
│  └──────────────────────────────────┬───────────────────────────────────┘   │
└─────────────────────────────────────┼────────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────┐
          │                           │                   │
┌─────────┴───────────┐   ┌──────────┴──────────┐  ┌─────┴────────────────┐
│     OpenAI API      │   │  Supabase             │  │   외부 공공 API      │
│  gpt-4o-mini        │   │  (PostgreSQL+pgvector) │  │  공공데이터포털      │
│  text-embedding-3s  │   │  agents / calls       │  │  질병관리청 통계     │
└─────────────────────┘   │  acw_cards            │  │  검역관리지역        │
                          │  knowledge_chunks      │  │  예방접종 정보       │
┌─────────────────────┐   │  transfer_agencies    │  └──────────────────────┘
│  Deepgram Nova-3    │   │  category_master       │
│  (STT, single/dual) │   │  notice_banners        │
└─────────────────────┘   └───────────────────────┘
```

---

## 3. 화면 ↔ API ↔ DB 연결 다이어그램

### SCR-001 ~ SCR-005 (기존과 동일, 하단 변경사항만 기재)

> SCR-001~005 상세 흐름은 v1.2와 동일합니다. 변경된 부분만 아래에 기재합니다.

#### SCR-005 변경사항 — 알림 배너 DB 연동

```
[SCR-005 대시보드 화면]
│
├── 화면 마운트 시
│   └──► GET /api/notice/banner          ← 기존 하드코딩 → DB 연동으로 변경
│            DB: SELECT * FROM notice_banners ORDER BY created_at DESC LIMIT 1
│            → { banner_id, message, created_at }
│            → 상단 알림 배너 표시
│
└── [X] 클릭 시 닫기 (프론트 상태만, DB 삭제 아님)
```

---

### SCR-006 | 공지사항

```
[SCR-006 공지사항 화면]
│  레이아웃: GNB + LNB + 알림 배너 + 콜센터 당일 통계 + 보도자료 + 유사 상담 사례
│
├── 화면 마운트 시
│   ├──► GET /api/notice/banner
│   │        → 알림 배너 표시
│   │
│   ├──► GET /api/notice/stats
│   │        DB: calls + acw_cards 당일 집계
│   │        → { total_calls, active_calls, avg_duration_sec, resolution_rate }
│   │        → 콜센터 당일 통계 카드 표시
│   │
│   ├──► GET /api/notice/press?page=1
│   │        → 질병관리청 보도자료 목록 표시
│   │
│   └──► GET /api/notice/similar?page=1
│            DB: acw_cards 완료된 상담 사례
│            → 유사 상담 사례 목록 표시
│
├── 보도자료 페이지네이션
│   └──► GET /api/notice/press?page={n}
│
├── [크롤링 실행] 버튼 (관리자용)
│   └──► POST /api/notice/crawl
│            → 질병관리청 웹사이트 수동 크롤링 실행
│
└── 알림 배너 관리
    ├──► POST /api/notice/banner   Body: { message }  → 배너 등록
    └──► DELETE /api/notice/banner/{banner_id}         → 배너 삭제
```

---

### SCR-007 | 상담 내역

```
[SCR-007 상담 내역 화면]
│  레이아웃: GNB + LNB + 요약 통계 카드 + 필터 + 상담 목록 + 상세 모달
│
├── 화면 마운트 시
│   ├──► GET /api/history/summary
│   │        → { total, today, resolved, transferred, resolution_rate, avg_duration_sec }
│   │        → 요약 통계 카드 표시
│   │
│   └──► GET /api/history?page=1
│            → 상담 목록 표시 (기본: 전체 기간)
│
├── 필터 적용
│   └──► GET /api/history?start_date={}&end_date={}&disease={}&page={n}
│            → 필터링된 목록 반환
│
└── 상담 카드 클릭
    └──► GET /api/history/{call_id}
             → 상담 상세 정보 (전사본, AI 응답, 카테고리 등) 모달 표시
```

---

## 4. 실시간 파이프라인 흐름 (WebSocket)

> STT가 Whisper → Deepgram Nova-3으로 변경되었습니다.
> WebSocket 엔드포인트: `/ws/stt/{call_id}?token={}&mode={single|dual}`

```
클라이언트 (SCR-003)                  서버 Pipeline                    외부 / DB
      │                                      │                            │
      │── WS connect ──────────────────────► │                            │
      │   /ws/stt/{call_id}?token=...        │ 인증 검증                  │
      │   &mode=single|dual                  │ 세션 초기화                │
      │                                      │                            │
      │── binary(PCM 16kHz) ───────────────► │                            │
      │                                      │ VAD 발화 감지              │
      │                                      │ (RTL-VOICE-001)            │
      │                                      │                            │
      │                                      │ Deepgram Nova-3 STT ──────►│ Deepgram API
      │                                      │ (single: diarize 기반      │
      │                                      │  dual: 채널 분리)           │
      │                                      │◄── 발화 텍스트 + 화자 ─────│
      │                                      │                            │
      │                                      │ 의료 도메인 텍스트 정규화  │
      │                                      │ (한글 숫자 변환, 오인식 치환)│
      │                                      │ conversation_history append │
      │                                      │                            │
      │◄── conversation_update ─────────────│                            │
      │    {speaker, text, timestamp}        │                            │
      │                                      │                            │
      │◄── ai_update {status:"loading"} ────│ STEP 1 시작                │
      │                                      │ gpt-4o-mini JSON mode ────►│ OpenAI
      │                                      │◄── {ready, is_oos,        │
      │                                      │     oos_type, oos_reason,  │
      │                                      │     disease_name, query}   │
      │                                      │                            │
      │                     ready=false? ────┤ 다음 발화 대기             │
      │                                      │                            │
      │                                      │ 쿼리 임베딩 ──────────────►│ text-emb-3s
      │                                      │◄── query_vector (1536d) ───│
      │                                      │                            │
      │                                      │ ┌─── 병렬 실행 ───────────┐│
      │                                      │ │ 2-A: knowledge_chunks   ││►pgvector
      │                                      │ │ 2-B: acw_cards          ││►pgvector
      │                                      │ │ 2-C: transfer_agencies  ││►pgvector
      │                                      │ └─────────────────────────┘│
      │                                      │                            │
      │◄── similar_cases ───────────────────│ 2-B 완료 즉시 push         │
      │◄── transfer_suggestion ─────────────│ 2-C 완료 즉시 push         │
      │                                      │                            │
      │                      is_oos=true? ───┤                            │
      │◄── ai_update {status:"oos"} ────────│                            │
      │                                      │                            │
      │                    2-A 결과=0? ──────┤                            │
      │◄── ai_update {status:"no_result"} ──│                            │
      │                                      │                            │
      │                                      │ STEP 3: AI 안내 ──────────►│ gpt-4o-mini
      │◄── ai_update {status:"success"} ────│                            │
      │                                      │                            │
      └── [통화 종료] PATCH /end ───────────►│ conversation_history → DB  │
```

---

## 5. REST API 상세

### 5-1. 인증 (Auth)

#### `POST /api/auth/login`
**Request Body**
```json
{ "username": "agent01", "password": "plaintext123" }
```
**Response 200**
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "agent": { "agent_id": 1, "username": "agent01", "name": "김상담" }
}
```
**Response 401**
```json
{ "detail": "아이디 또는 비밀번호가 올바르지 않습니다." }
```

---

#### `POST /api/auth/logout`
**Headers**: `Authorization: Bearer {token}`
**제약**: 통화 중(`calls.status = 'active'`) 시 `409 Conflict`
**Response 200**
```json
{ "message": "로그아웃 되었습니다." }
```

---

### 5-2. 계정 (Agents)

#### `POST /api/agents`
**Request Body**
```json
{ "username": "agent01", "name": "김상담", "password": "...", "password_confirm": "..." }
```
**Response 201**
```json
{ "agent_id": 11, "username": "agent01", "name": "김상담", "created_at": "2026-05-05T09:00:00" }
```

---

#### `GET /api/agents/check-name`
**Query Params**: `username={아이디}`
**Response 200**: `{ "available": true }` 또는 `{ "available": false }`

---

#### `GET /api/agents/me`
**Response 200**
```json
{ "agent_id": 1, "username": "agent01", "name": "김상담", "created_at": "2026-01-05T09:00:00" }
```

---

### 5-3. 통화 (Calls)

#### `POST /api/calls`
**Response 201**
```json
{ "call_id": 101, "agent_id": 1, "status": "active", "started_at": "2026-05-05T10:30:00" }
```

---

#### `PATCH /api/calls/{call_id}/end`
**Response 200**
```json
{ "call_id": 101, "status": "acw", "ended_at": "2026-05-05T10:55:00", "duration_sec": 1500 }
```

---

#### `GET /api/calls/{call_id}`
**Response 200**
```json
{ "call_id": 101, "agent_id": 1, "status": "active", "started_at": "...", "conversation_history": [] }
```

---

### 5-4. ACW 후처리

#### `GET /api/acw/{call_id}/init`
**Response 200**
```json
{
  "acw_id": 201,
  "transcript": "[09:30:15] 고객: 코로나19 격리 기간이 어떻게 되나요?\n...",
  "ai_guidance": {
    "query": "코로나19 격리 기간",
    "disease_name": "코로나19",
    "is_oos": false,
    "oos_type": null,
    "oos_reason": null,
    "answer": "코로나19 확진자의 격리 기간은 5일입니다.",
    "sources": [{ "chunk_id": 42, "document_title": "...", "section_title": "...", "data_id": "DATA-001" }]
  },
  "acw_started_at": "2026-05-05T10:55:05"
}
```

---

#### `POST /api/acw/{call_id}/generate`
**Response 200**
```json
{
  "title": "코로나19 격리 기간 및 절차 문의",
  "customer_type": "citizen",
  "customer_type_custom": null,
  "category": "감염병",
  "category_major": "코로나19",
  "category_mid": "격리",
  "category_mid_list": ["격리"],
  "category_mid_custom": null,
  "disease_name": "코로나19",
  "qa_summary": [{ "q": "코로나19 격리 기간이 어떻게 되나요?", "a": "확진자 격리 기간은 5일입니다." }],
  "ai_response_summary": "고객은 코로나19 격리 기간에 대해 문의하였습니다...",
  "is_transferred": false,
  "transfer_target": null,
  "keywords": ["코로나19", "격리", "격리기간", "확진자", "5일"]
}
```

---

#### `PUT /api/acw/{call_id}`
> [완료] 또는 [임시저장] 버튼

**[완료] 버튼 필수 검증**

| 필드 | 조건 |
|------|------|
| `is_resolved` | 필수 |
| `agent_used_ai` | 필수 (`yes` / `partial` / `no`) |
| `category_mid` | 1개 이상 |
| `category_mid_custom` | `category="범위외"` 시 필수 |

**Response 200**
```json
{ "acw_id": 201, "call_id": 101, "acw_ended_at": "2026-05-05T11:10:00", "acw_duration_sec": 900 }
```

---

### 5-5. 대시보드 (Dashboard)

#### `GET /api/dashboard/my/summary`
```json
{ "total_calls": 12, "resolved": 9, "unresolved": 3, "avg_duration_sec": 320 }
```

#### `GET /api/dashboard/my/today`
```json
{
  "total": 12,
  "by_major": [{ "category_major": "코로나19", "count": 5 }],
  "by_mid": [{ "category_mid": "격리", "count": 4 }]
}
```

#### `GET /api/dashboard/my/keywords`
```json
{ "keywords": [{ "keyword": "코로나19", "count": 8 }] }
```

#### `GET /api/dashboard/my/weekly-trend`
```json
{ "data": [{ "date": "2026-04-29", "disease_name": "코로나19", "count": 3 }] }
```

#### `GET /api/dashboard/all/summary`
```json
{ "today": 45, "this_week": 312, "this_month": 1203, "hourly": [{ "hour": 9, "count": 12 }] }
```

#### `GET /api/dashboard/all/disease-trend`
**Query Params**: `period` = `today` | `week` | `month`
```json
{ "period": "week", "data": [{ "date": "2026-04-29", "disease_name": "코로나19", "count": 15 }] }
```

#### `GET /api/dashboard/all/category-trend`
**Query Params**: `period` = `today` | `week` | `month`
```json
{ "period": "week", "data": [{ "date": "2026-04-29", "category_mid": "격리", "count": 10 }] }
```

---

### 5-6. 감염병 통계 (Disease Stats)

> 공공데이터포털 질병관리청 통계 API 연동. 1시간 TTL 캐시 적용.

#### `GET /api/disease-stats/by-disease`
> 이번 달 감염병별 발생현황 TOP 10

**Response 200**
```json
{ "data": [{ "disease_name": "코로나19", "count": 1203 }] }
```

---

#### `GET /api/disease-stats/by-gender`
**Query Params**: `year` (선택), `stat_type` (선택)

**Response 200**
```json
{ "data": [{ "gender": "남", "count": 620 }, { "gender": "여", "count": 583 }] }
```

---

#### `GET /api/disease-stats/by-age`
**Query Params**: `year` (선택), `age_unit` (선택)

**Response 200**
```json
{ "data": [{ "age_group": "20대", "count": 312 }] }
```

---

#### `GET /api/disease-stats/trend-with-calls`
> 주요 감염병 추세 + 1339 콜 건수 통합

**Response 200**
```json
{ "data": [{ "date": "2026-05-01", "disease_name": "코로나19", "stat_count": 80, "call_count": 15 }] }
```

---

#### `GET /api/disease-stats/weekly-alert`
> 전주 대비 감염병 발생 증감 Top 4 (조기경보)

**Response 200**
```json
{
  "data": [
    { "disease_name": "코로나19", "this_week": 120, "last_week": 90, "change_rate": 33.3 }
  ]
}
```

---

#### `DELETE /api/disease-stats/cache`
> 인메모리 캐시 초기화 (관리용)

---

### 5-7. 카테고리 마스터

#### `GET /api/categories`
```json
{
  "categories": [
    { "category": "감염병", "major": "코로나19", "mid": "격리" },
    { "category": "접수처리", "major": "이관", "mid": "보건소 이관" },
    { "category": "범위외", "major": "기타 문의", "mid": "일반 문의" }
  ]
}
```

---

### 5-8. 공지사항 (Notice)

#### `GET /api/notice/banner`
> 최신 공지 배너 1건 조회

**Response 200**
```json
{ "banner_id": 1, "message": "2026.06.01 코로나19 격리 지침 변경", "created_at": "2026-06-01T09:00:00" }
```

---

#### `POST /api/notice/banner`
**Request Body**
```json
{ "message": "2026.06.10 인플루엔자 유행 주의보 발령" }
```
**Response 201**
```json
{ "banner_id": 2, "message": "...", "created_at": "2026-06-10T10:00:00" }
```

---

#### `DELETE /api/notice/banner/{banner_id}`
**Response 200**
```json
{ "message": "삭제되었습니다." }
```

---

#### `GET /api/notice/stats`
> 콜센터 당일 통계

**Response 200**
```json
{
  "total_calls": 45,
  "active_calls": 3,
  "avg_duration_sec": 310,
  "resolution_rate": 0.87
}
```

---

#### `GET /api/notice/press`
> 질병관리청 보도자료 목록 (페이지네이션)

**Query Params**: `page` (기본값: 1)

**Response 200**
```json
{
  "total": 120,
  "page": 1,
  "items": [
    { "title": "코로나19 주간 현황", "url": "https://...", "date": "2026-06-09" }
  ]
}
```

---

#### `POST /api/notice/crawl`
> 질병관리청 웹사이트 수동 크롤링 즉시 실행

**Response 200**
```json
{ "message": "크롤링이 완료되었습니다.", "count": 5 }
```

---

### 5-9. 검역 (Quarantine)

> 공공데이터포털 검역관리지역 API 연동. 24시간 캐시 적용.

#### `GET /api/quarantine/country`
**Query Params**: `country` (국가명)

**Response 200**
```json
{
  "country": "태국",
  "diseases": [
    { "disease_name": "뎅기열", "risk_level": "주의", "monitoring_period": "14일" }
  ]
}
```

---

#### `GET /api/quarantine/disease`
**Query Params**: `disease_code` (감염병 코드)

**Response 200**
```json
{
  "disease_code": "DEN",
  "disease_name": "뎅기열",
  "target_countries": ["태국", "베트남"],
  "risk_group": "여행자",
  "monitoring_period": "14일"
}
```

---

#### `GET /api/quarantine/search`
> 자유 텍스트로 국가명 또는 감염병명 자동 감지 후 검색

**Query Params**: `query` (자유 텍스트)

**Response 200**
```json
{
  "matched_type": "country",
  "result": { "country": "태국", "diseases": [...] }
}
```

---

### 5-10. 예방접종 (Vaccine)

> 공공데이터포털 예방접종 API 연동. 24시간 캐시 적용.

#### `GET /api/vaccine/search`
**Query Params**: `query` (병명)

**Response 200**
```json
{
  "vcn_cd": "INF",
  "title": "인플루엔자",
  "summary": "계절성 인플루엔자 예방접종",
  "schedule": "매년 10~11월",
  "target": "전 국민 (고위험군 우선)",
  "side_effects": "주사 부위 통증, 발열",
  "cached": true
}
```

---

### 5-11. 상담 내역 (History)

#### `GET /api/history`
> 본인 상담 목록 (페이지네이션 + 필터)

**Query Params**: `start_date`, `end_date`, `disease` (선택), `page`, `page_size`

**Response 200**
```json
{
  "total": 85,
  "page": 1,
  "items": [
    {
      "call_id": 101,
      "disease_name": "코로나19",
      "category": "감염병",
      "is_resolved": true,
      "satisfaction": 5,
      "duration_sec": 320,
      "created_at": "2026-06-08T10:30:00"
    }
  ]
}
```

---

#### `GET /api/history/summary`
> 본인 전체 상담 요약 통계

**Response 200**
```json
{
  "total": 85,
  "today": 12,
  "resolved": 70,
  "transferred": 8,
  "resolution_rate": 0.82,
  "avg_duration_sec": 315
}
```

---

#### `GET /api/history/{call_id}`
> 특정 상담 상세 조회

**Response 200**
```json
{
  "call_id": 101,
  "title": "코로나19 격리 기간 문의",
  "transcript": "[09:30:15] 고객: ...",
  "customer_type": "citizen",
  "category": "감염병",
  "category_major": "코로나19",
  "category_mid": "격리",
  "disease_name": "코로나19",
  "qa_summary": [{ "q": "격리 기간은?", "a": "5일입니다." }],
  "ai_response_summary": "...",
  "is_resolved": true,
  "agent_used_ai": "yes",
  "satisfaction": 5,
  "agent_memo": "",
  "duration_sec": 320,
  "created_at": "2026-06-08T10:30:00"
}
```

---

## 6. WebSocket 이벤트 명세

### 연결

```
WS /ws/stt/{call_id}?token={access_token}&mode={single|dual}
```

- `call_id`: `POST /api/calls` 응답의 `call_id`
- `token`: JWT access_token (쿼리 파라미터)
- `mode`: `single` (diarize 기반 화자 분리) | `dual` (듀얼 채널)
- Binary frame: PCM 16kHz mono 16-bit 오디오 청크

---

### Server → Client 이벤트 (push)

| type | 트리거 | 연관 UI |
|------|--------|---------|
| `conversation_update` | Deepgram STT + 정규화 완료 | 우측 대화 내역 |
| `ai_update` | STEP 1 시작 / STEP 3 완료 | 좌측 AI 안내 카드 |
| `similar_cases` | 2-B 완료 | 좌측 유사사례 카드 |
| `transfer_suggestion` | 2-C 완료 | 좌측 이관 참고 카드 |

---

#### `conversation_update`
```json
{
  "type": "conversation_update",
  "speaker": "고객",
  "text": "코로나19 격리 기간이 어떻게 되나요?",
  "timestamp": "2026-05-05T10:31:05"
}
```
> `speaker`: `"고객"` | `"상담사"`

---

#### `ai_update` — 4가지 status

```json
{ "type": "ai_update", "status": "loading" }

{
  "type": "ai_update",
  "status": "success",
  "query": "코로나19 격리 기간",
  "disease_name": "코로나19",
  "answer": "코로나19 확진자의 격리 기간은 5일입니다.",
  "sources": [
    { "chunk_id": 42, "document_title": "2025년도 코로나19 관리지침", "section_title": "격리 기간 및 기준", "data_id": "DATA-001", "chunk_text": "확진자는 증상 발생일로부터 5일간 격리..." }
  ]
}

{ "type": "ai_update", "status": "oos", "oos_type": "unrelated", "oos_reason": "보험 청구 관련 문의로 1339 업무 범위 외입니다." }

{ "type": "ai_update", "status": "no_result", "query": "희귀 기생충 감염" }

{ "type": "ai_update", "status": "error" }
```

---

#### `similar_cases`
```json
{
  "type": "similar_cases",
  "data": [{ "acw_id": 15, "title": "코로나19 확진 후 격리 절차 문의", "similarity": 0.923, "qa_summary": [{ "q": "격리 기간은?", "a": "5일 격리입니다." }] }]
}
```

---

#### `transfer_suggestion`
```json
{
  "type": "transfer_suggestion",
  "data": [{ "org_name": "질병관리청", "dept_name": "코로나19대응팀", "phone": "1339", "description_summary": "코로나19 확진자 격리 및 치료 지원 담당", "similarity": 0.871 }]
}
```

---

## 7. FastAPI 파일 구조

```
backend/app/
│
├── main.py                     # FastAPI 앱, 라우터 등록, CORS
│
├── core/
│   ├── config.py               # 환경변수 (.env) 로드
│   ├── database.py             # asyncpg 연결 풀
│   ├── security.py             # JWT 발급/검증, bcrypt
│   └── dependencies.py         # get_current_agent() 인증 의존성
│
├── routers/
│   ├── auth.py                 # POST /api/auth/login, /logout
│   ├── agents.py               # POST /api/agents, GET /check-name, /me
│   ├── calls.py                # POST /api/calls, PATCH /{id}/end, GET /{id}
│   ├── acw.py                  # GET/POST/PUT /api/acw/{id}
│   ├── dashboard.py            # GET /api/dashboard/my/**, /all/**
│   ├── disease_stats.py        # GET /api/disease-stats/** (공공데이터 통계)
│   ├── categories.py           # GET /api/categories
│   ├── notice.py               # GET/POST/DELETE /api/notice/**
│   ├── quarantine.py           # GET /api/quarantine/** (검역관리지역)
│   ├── vaccine.py              # GET /api/vaccine/search
│   ├── history.py              # GET /api/history/**
│   └── stt.py                  # WS /ws/stt/{call_id} (Deepgram Nova-3)
│
├── services/
│   ├── auth_service.py
│   ├── agent_service.py
│   ├── call_service.py
│   ├── acw_service.py
│   ├── dashboard_service.py
│   │
│   └── pipeline/
│       ├── session.py          # 통화 세션 (conversation_history, ai_guidance 캐시)
│       ├── voice.py            # VAD + Deepgram Nova-3 STT (single/dual)
│       ├── step1_llm.py        # STEP 1: ready/is_oos/disease_name/query
│       ├── step2_search.py     # STEP 2: 2-A/2-B/2-C 병렬 벡터 검색
│       ├── step3_llm.py        # STEP 3: AI 안내 생성
│       └── guidance_cache.py   # ai_guidance 캐시 구성/조회
│
├── schemas/
│   ├── auth.py
│   ├── agents.py
│   ├── calls.py
│   ├── acw.py
│   ├── dashboard.py
│   ├── notice.py
│   ├── history.py
│   └── external.py             # quarantine, vaccine 응답 스키마
│
└── models/
    ├── agent.py
    ├── call.py
    └── acw_card.py
```

---

## 8. 공통 규칙

### 인증

`/api/auth/login`, `/api/agents` (POST), `/api/agents/check-name` 제외
모든 API에 JWT Bearer Token 필수.

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

토큰 만료 → `401 { "detail": "토큰이 만료되었습니다." }`

---

### 에러 코드

| HTTP | 상황 |
|------|------|
| 400 | 요청 형식 오류 / 필수 필드 누락 |
| 401 | 인증 실패 / 토큰 만료 |
| 403 | 권한 없음 |
| 404 | 리소스 없음 |
| 409 | 중복 / 통화 중 로그아웃 |
| 422 | Pydantic 유효성 검사 실패 |
| 500 | 서버 오류 / LLM 호출 실패 |

**에러 응답 형식**
```json
{ "detail": "에러 메시지" }
```

---

### 환경변수 (.env)

```env
# DB
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/kdca_db

# OpenAI
OPENAI_API_KEY=sk-...

# JWT
JWT_SECRET_KEY=your-secret-key-here
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=480

# Deepgram (STT)
DEEPGRAM_API_KEY=...

# 공공데이터포털 (검역·예방접종·감염병 통계)
PUBLIC_DATA_API_KEY=...
```

---

*API 설계서 v2.0 — 기능명세서 v4.0 · 화면설계서 v2.0 · DB 설계서 v2.0 기반*

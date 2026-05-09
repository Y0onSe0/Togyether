# API 설계서 v1.2
## 질병관리청 1339 콜센터 AI 지원 시스템

> 참조: 기능명세서 v3.0 · 화면설계서 v1.0 · DB 설계서 v2.0
> 작성일: 2026-05-05
> v1.1 수정: SCR 번호 전면 재정렬 (SCR-002=계정생성, SCR-003=상담메인, SCR-005=대시보드)
> v1.2 수정: agents.username 분리 반영 (로그인 ID), ai_guidance에 oos_type 필드 추가, category 예시 갱신 (접수처리/범위외)

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
| DB | PostgreSQL 16 + pgvector |
| LLM | gpt-4o-mini (STEP 1 · STEP 3 · ACW LLM) |
| 임베딩 | text-embedding-3-small (1536d) |

### 화면 목록 (화면설계서 v1.0 기준)

| 화면 ID | 화면명 | 접근 경로 |
|---------|--------|----------|
| SCR-001 | 로그인 | 진입점 |
| SCR-002 | 계정 생성 | SCR-001 → 계정 생성 링크 |
| SCR-003 | 상담사 메인 (대기 중 / 상담 중) | 로그인 성공 후 |
| SCR-004 | ACW 카드 작성 | 통화 종료 후 자동 전환 |
| SCR-005 | 대시보드 | LNB 메뉴 |

### 화면 전환 흐름

```
[SCR-001 로그인]
    │ 성공
    ▼
[SCR-003 대기 중]  ◄──────────────────────────────┐
    │ 상담 시작 버튼 (상태 전환, 화면 이동 없음)     │ ACW 저장 완료
    ▼                                              │
[SCR-003 상담 중]                                  │
    │ 통화 종료 (화면 이동)                         │
    ▼                                              │
[SCR-004 ACW 카드 작성] ────────────────────────────┘

[SCR-003/004/005] → GNB 상담사명 ▼ 팝오버 → 로그아웃 → [SCR-001]
[SCR-003/004]    → LNB → [SCR-005 대시보드]
[SCR-001]        → 계정 생성 링크 → [SCR-002] → 완료 → [SCR-001]
```

### 엔드포인트 목록 요약

| 분류 | Method | Path | 기능명세 ID | 화면 |
|------|--------|------|------------|------|
| **인증** | POST | `/api/auth/login` | UA-AUTH-001 | SCR-001 |
| | POST | `/api/auth/logout` | UA-AUTH-002 | SCR-003/004/005 팝오버 |
| **계정** | POST | `/api/agents` | UA-ACCT-001 | SCR-002 |
| | GET | `/api/agents/check-name` | UA-ACCT-001 | SCR-002 (실시간 중복확인) |
| | GET | `/api/agents/me` | UA-PROF-001 | SCR-003/004/005 GNB |
| **통화** | POST | `/api/calls` | — | SCR-003 (상담 시작) |
| | PATCH | `/api/calls/{call_id}/end` | ACW-001 | SCR-003 (통화 종료) |
| | GET | `/api/calls/{call_id}` | — | SCR-003 |
| **WebSocket** | WS | `/ws/call/{call_id}` | RTL-VOICE/LLM/SRCH/UI | SCR-003 상담 중 |
| **ACW** | GET | `/api/acw/{call_id}/init` | ACW-001·002 | SCR-004 |
| | POST | `/api/acw/{call_id}/generate` | ACW-002 | SCR-004 |
| | PUT | `/api/acw/{call_id}` | ACW-003·004 | SCR-004 |
| | GET | `/api/acw/{call_id}` | — | SCR-004 |
| **대시보드** | GET | `/api/dashboard/my/today` | DASH-MY-001 | SCR-005 내 통계 탭 |
| | GET | `/api/dashboard/my/keywords` | DASH-MY-002 | SCR-005 내 통계 탭 |
| | GET | `/api/dashboard/my/summary` | DASH-MY-003 | SCR-005 내 통계 탭 |
| | GET | `/api/dashboard/my/weekly-trend` | DASH-MY-004 | SCR-005 내 통계 탭 |
| | GET | `/api/dashboard/all/summary` | DASH-ALL-001 | SCR-005 전체 통계 탭 |
| | GET | `/api/dashboard/all/disease-trend` | DASH-ALL-002 | SCR-005 전체 통계 탭 |
| | GET | `/api/dashboard/all/category-trend` | DASH-ALL-003 | SCR-005 전체 통계 탭 |
| **카테고리** | GET | `/api/categories` | — | SCR-004 드롭다운 |

---

## 2. 전체 아키텍처

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          Frontend  (React + Tailwind)                    │
│                                                                          │
│  SCR-001   SCR-002       SCR-003              SCR-004       SCR-005     │
│  [로그인] [계정생성]  [상담사 메인]          [ACW 작성]   [대시보드]   │
│                      [대기↔상담 중]                                     │
└────┬────────┬────────────┬──────────────────────┬────────────┬──────────┘
     │        │            │                      │            │
     │ HTTP   │ HTTP       │ HTTP + WS            │ HTTP       │ HTTP
     ▼        ▼            ▼                      ▼            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        FastAPI  (app/main.py)                            │
│                                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐  │
│  │  /auth   │ │ /agents  │ │  /calls  │ │  /acw    │ │ /dashboard  │  │
│  │          │ │          │ │  /ws     │ │/categories│ │             │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬──────┘  │
│       │            │             │             │              │          │
│  ┌────┴────────────┴─────────────┴─────────────┴──────────────┴───────┐ │
│  │                          Service Layer                               │ │
│  │                                                                      │ │
│  │  AuthService  AgentService  CallService  ACWService  DashService    │ │
│  │                                                                      │ │
│  │                             Pipeline (RTL)                           │ │
│  │                    ┌─────────────────────────────┐                  │ │
│  │                    │ STEP 1: LLM 통합 판정        │                  │ │
│  │                    │ STEP 2A: knowledge 벡터 검색 │                  │ │
│  │                    │ STEP 2B: acw_cards 유사사례  │  (병렬)          │ │
│  │                    │ STEP 2C: transfer 이관기관   │                  │ │
│  │                    │ STEP 3: AI 안내 생성         │                  │ │
│  │                    └─────────────────────────────┘                  │ │
│  └────────────────────────────────┬─────────────────────────────────────┘ │
└───────────────────────────────────┼──────────────────────────────────────┘
                                    │
               ┌────────────────────┴───────────────────┐
               │                                        │
    ┌──────────┴──────────┐                 ┌───────────┴────────────┐
    │     OpenAI API      │                 │    PostgreSQL 16        │
    │  gpt-4o-mini        │                 │    + pgvector          │
    │  Whisper STT        │                 │                        │
    │  text-embedding-3s  │                 │  agents                │
    └─────────────────────┘                 │  calls                 │
                                            │  acw_cards             │
    ┌─────────────────────┐                 │  knowledge_chunks      │
    │   pyannote          │                 │  transfer_agencies     │
    │   (화자 분리)        │                 │  category_master       │
    └─────────────────────┘                 └────────────────────────┘
```

---

## 3. 화면 ↔ API ↔ DB 연결 다이어그램

### SCR-001 | 로그인

```
[SCR-001 로그인 화면]
│  컴포넌트: 아이디 Input + 비밀번호 Input + 로그인 Button
│  + 오류 메시지 Text (인증 실패 시 표시)
│  + "계정이 없으신가요? 계정 생성" Link → SCR-002 이동
│
└──► POST /api/auth/login
         Body: { username, password }
         │
         │  Service: agents 테이블 조회 → bcrypt 검증 → JWT 발급
         │  DB: SELECT agent_id, username, name, password_hash
         │       FROM agents WHERE username = $1
         │
         ├── 성공 200 → { access_token, agent: {agent_id, username, name} }
         │            → navigate: SCR-003 (대기 중 상태)
         └── 실패 401 → { detail: "아이디 또는 비밀번호가 올바르지 않습니다." }
                      → 오류 메시지 표시
```

---

### SCR-002 | 계정 생성

```
[SCR-002 계정 생성 화면]
│  컴포넌트: 아이디 Input(중복확인) + 이름 Input
│           + 비밀번호 Input + 비밀번호 확인 Input
│           + 계정 생성 Button + 오류 메시지
│           + "← 로그인으로" Link → SCR-001
│
├── 아이디 Input onChange (디바운스)
│   └──► GET /api/agents/check-name?username={아이디}
│            DB: SELECT COUNT(*) FROM agents WHERE username = $1
│            → { available: true }  → 사용 가능 표시 (green)
│            → { available: false } → 중복 오류 표시 (red)
│
└── [계정 생성] 버튼 클릭
    └──► POST /api/agents
             Body: { username, name, password, password_confirm }
             │       (username: 로그인 아이디 / name: 상담사 표시 이름)
             │
             │  Validation: password == password_confirm
             │  Service: bcrypt(password) → INSERT
             │  DB: INSERT INTO agents (username, name, password_hash)
             │       VALUES ($1, $2, bcrypt($3))
             │       RETURNING agent_id, username, name, created_at
             │
             ├── 성공 201 → { agent_id, username, name, created_at }
             │            → navigate: SCR-001
             └── 실패 409 → { detail: "이미 사용 중인 아이디입니다." }
```

---

### SCR-003 | 상담사 메인 — 대기 중 상태

```
[SCR-003 대기 중 화면]
│  레이아웃: GNB + LNB + 메인 영역
│
├── 화면 마운트 시
│   └──► GET /api/agents/me                     ← UA-PROF-001
│            Header: Authorization: Bearer {token}
│            DB: SELECT agent_id, username, name, created_at
│                 FROM agents WHERE agent_id = $1
│            → { agent_id, username, name }
│            → GNB 상담사명(name) 표시
│
├── GNB 상담사명 ▼ 팝오버
│   └── "로그아웃" 클릭
│       └──► POST /api/auth/logout
│                Service: 토큰 블랙리스트 처리
│                → navigate: SCR-001
│
├── LNB [대시보드] 링크
│   └── → navigate: SCR-005
│
└── [상담 시작] 버튼 클릭
    ├──► POST /api/calls
    │        Header: Authorization: Bearer {token}
    │        DB: INSERT INTO calls (agent_id, status, started_at)
    │             VALUES ($1, 'active', NOW())
    │        → { call_id, agent_id, status:'active', started_at }
    │
    └── WS connect: /ws/call/{call_id}?token={access_token}
        → 상담 중 상태로 전환 (화면 이동 없음)
```

---

### SCR-003 | 상담사 메인 — 상담 중 상태

```
[SCR-003 상담 중 화면]
│  레이아웃: LNB(7%) + 좌측 AI 카드(43%) + 우측 대화 내역(50%)
│
└──► WS  /ws/call/{call_id}?token={access_token}
     │
     │  ─── Client → Server ───────────────────────────────────────────
     │    binary frame: PCM 오디오 청크 (16kHz mono 16-bit)
     │
     │  ─── Server → Client push events ──────────────────────────────
     │
     │  ① {type: "conversation_update", speaker, text, timestamp}
     │       → 우측 대화 내역 실시간 append
     │       → 고객 발화: 좌측 회색 말풍선 (👤)
     │       → 상담사 발화: 우측 파란 말풍선 (🎧)
     │       → 메모리 conversation_history append
     │       → DB 저장: 통화 종료 시 1회 (calls.conversation_history)
     │
     │  ② {type: "ai_update", status: "loading"}
     │       → AI 안내 카드: ⏳ 분석 중
     │
     │  ② {type: "ai_update", status: "success", query, disease_name,
     │       answer, sources[{chunk_id, document_title, section_title,
     │                        data_id, chunk_text}]}
     │       → 좌측 AI 안내 카드: 태그 + 문의 + 답변 + 출처 캐러셀(‹1/3›)
     │       → [바로가기 →] 클릭 → 청크 전문 모달 오픈
     │       → 서버 세션: ai_guidance 캐시 저장
     │
     │  ② {type: "ai_update", status: "oos", oos_type, oos_reason}
     │       → AI 안내 카드: ⚠️ oos_reason 1줄 표시
     │
     │  ② {type: "ai_update", status: "no_result", query}
     │       → AI 안내 카드: "관련 정보를 찾을 수 없습니다."
     │
     │  ② {type: "ai_update", status: "error"}
     │       → AI 안내 카드: "AI 분석 중 오류가 발생했습니다."
     │
     │  ③ {type: "similar_cases", data: [{acw_id, title, similarity,
     │       qa_summary}]}
     │       → 좌측 유사사례 카드 캐러셀(▶◀ 1/3)
     │       → 카드 클릭: Accordion 펼침 (Q 전문 + 구분선 + A 전문)
     │       DB: acw_cards.q_embedding 벡터 검색 (cosine ≥ 0.70, Top-3)
     │
     │  ④ {type: "transfer_suggestion", data: [{org_name, dept_name,
     │       phone, description_summary, similarity}]}
     │       → 좌측 이관 참고 카드
     │       DB: transfer_agencies.description_embedding 벡터 검색
     │
     └── [통화 종료] 버튼 클릭
         ├──► PATCH /api/calls/{call_id}/end
         │        DB: UPDATE calls
         │             SET status='acw', ended_at=NOW(),
         │                 duration_sec=EXTRACT(EPOCH FROM(NOW()-started_at))::INT,
         │                 conversation_history=$jsonb
         │             WHERE call_id=$1
         │        → { call_id, status:'acw', ended_at, duration_sec }
         │
         └── WS disconnect
             → navigate: SCR-004
```

---

### SCR-004 | ACW 카드 작성

```
[SCR-004 ACW 화면]
│  레이아웃: 상단 헤더(타이머·임시저장·완료)
│           + 좌측 상담 전문 (스크롤)
│           + 우측 Section 1~7
│
├── 화면 마운트 시 (자동 순차 실행)
│
│   Step A ──► GET /api/acw/{call_id}/init                  ← ACW-001
│                  Service:
│                    ① conversation_history JSONB
│                       → "[HH:MM:SS] 고객/상담사: ..." TEXT 변환
│                       → 실패 시 원문 저장
│                    ② acw_started_at = NOW() 기록
│                    ③ 세션 캐시에서 ai_guidance 조회
│                  DB: INSERT INTO acw_cards
│                       (call_id, agent_id, source, transcript, acw_started_at)
│                       VALUES ($1, $2, 'system', $transcript, NOW())
│                       ON CONFLICT (call_id) DO UPDATE ...
│                  → { acw_id, transcript, ai_guidance, acw_started_at }
│                  → 좌측 상담 전문 영역 표시
│                     (고객: 배경 #F3F4F6 좌측 / 상담사: 배경 #EFF6FF 우측)
│                  → Section 4 AI 안내 읽기 전용 표시:
│                     ai_guidance.answer → AI 생성 답변
│                     ai_guidance.sources[] → 참고 문서 ①②③
│
│   Step B ──► POST /api/acw/{call_id}/generate              ← ACW-002
│                  Input: transcript + ai_guidance (캐시)
│                  Service: gpt-4o-mini JSON mode 1회 호출
│                  → {
│                       title,                     → Section 2 상담 제목
│                       customer_type,             → Section 2 고객 유형 Radio
│                       customer_type_custom,      → Section 2 기타 입력 활성화
│                       category,                  → Section 2 카테고리 Dropdown
│                       category_major,            → Section 2 대분류
│                       category_mid,              → Section 2 중분류
│                       category_mid_list,         → Section 2 중분류 Multi-select
│                       disease_name,              → Section 2 질병명
│                       is_transferred,            → Section 2 이관 여부 Radio
│                       transfer_target,           → Section 2 이관 대상 활성화
│                       qa_summary,                → Section 5 Q/A Textarea
│                       ai_response_summary,       → Section 3 AI 상담 요약 (읽기 전용)
│                       keywords                   → 저장 시 사용
│                     }
│
│   Step C ──► GET /api/categories
│                  DB: SELECT category, major, mid
│                       FROM category_master ORDER BY category, major, mid
│                  → { categories: [{category, major, mid}] }
│                  → Section 2 카테고리·대분류·중분류 Dropdown 데이터
│
├── 상담사 검토 및 수정 (ACW-003)
│   ├── Section 2: 제목·고객유형·카테고리·질병명·이관 수정 가능
│   ├── Section 4: ai_guidance.answer·sources[] 읽기 전용 (수정 불가)
│   ├── Section 5: Q/A Textarea 수정 가능
│   └── Section 6: 해결 여부(필수), AI 활용 여부(필수), 만족도(선택)
│       Section 7: 메모 (선택)
│
├── [임시저장] 버튼 → PUT /api/acw/{call_id} (필수값 미검증)
│
└── [완료] 버튼 클릭 (ACW-003·004)
    │   필수 검증: is_resolved / agent_used_ai / category_mid 1개 이상
    │              category="범위외" 시 category_mid_custom 필수
    │   → 실패: 해당 필드 오류 표시, 저장 차단
    │
    └──► PUT /api/acw/{call_id}
             Body: {
               [LLM 생성]   title, customer_type, customer_type_custom,
                             category, category_major, category_mid,
                             category_mid_list, category_mid_custom,
                             disease_name, qa_summary, ai_response_summary,
                             is_transferred, transfer_target, keywords
               [캐시 직접]  ai_guidance { query, disease_name, is_oos,
                             oos_type, oos_reason, answer, sources[] }
               [상담사 입력] is_resolved, agent_used_ai, satisfaction, agent_memo
             }
             │
             │  Service:
             │    ① acw_cards 전체 UPDATE
             │    ② qa_summary[0].q → text-embedding-3-small → q_embedding 저장
             │       (실패 시 NULL, 카드 저장 정상 처리)
             │    ③ acw_ended_at=NOW(), acw_duration_sec 산출
             │    ④ calls.status = 'ended' UPDATE
             │
             → { acw_id, acw_ended_at, acw_duration_sec }
             → navigate: SCR-003 (대기 중 상태)
```

---

### SCR-005 | 대시보드

```
[SCR-005 대시보드 화면]
│  레이아웃: GNB + LNB + 알림 배너 + 서브 탭 (내 통계 / 전체 통계)
│
├── 화면 마운트 시
│   └──► GET /api/agents/me                               ← UA-PROF-001
│            → GNB 상담사명 표시
│
├── 알림 배너 (하드코딩, DB 미연동)                        ← DASH-NOTI-001
│   → [X] 클릭 시 닫기 (프론트 상태 관리만)
│
├── [내 통계] 탭 클릭 (기본값)
│   │
│   ├──► GET /api/dashboard/my/summary                    ← DASH-MY-003
│   │        DB: acw_cards + calls WHERE agent_id=$1 AND TODAY
│   │        → { total_calls, resolved, unresolved, avg_duration_sec }
│   │        → 총 상담 카드 (상단 large bold + 🔴미해결 🟢해결)
│   │        → 평균 통화시간 카드
│   │
│   ├──► GET /api/dashboard/my/today                      ← DASH-MY-001
│   │        DB: acw_cards WHERE agent_id=$1 AND DATE(created_at)=CURRENT_DATE
│   │        → { total, by_major:[{category_major,count}],
│   │             by_mid:[{category_mid,count}] }
│   │        → 대분류별 Bar Chart
│   │        → 중분류별 Bar Chart
│   │
│   ├──► GET /api/dashboard/my/keywords                   ← DASH-MY-002
│   │        DB: jsonb_array_elements_text(keywords) unnest, TOP 10
│   │        → { keywords:[{keyword,count}] }
│   │        → Top 10 키워드 리스트
│   │
│   └──► GET /api/dashboard/my/weekly-trend               ← DASH-MY-004
│            DB: acw_cards WHERE agent_id=$1 AND WEEK
│                GROUP BY date, disease_name
│            → { data:[{date, disease_name, count}] }
│            → 주간 트렌드 Multi-line Chart
│
└── [전체 통계] 탭 클릭
    │
    ├──► GET /api/dashboard/all/summary                   ← DASH-ALL-001
    │        DB: acw_cards + calls 전체 집계
    │        → { today, this_week, this_month,
    │             hourly:[{hour,count}] }
    │        → 기간별 총 건수 카드 × 3 (오늘/이번주/이번달)
    │        → 시간대별 Bar Chart
    │
    ├──► GET /api/dashboard/all/disease-trend?period=today|week|month
    │        ← DASH-ALL-002
    │        DB: acw_cards GROUP BY date, disease_name
    │             WHERE period 필터
    │        → { period, data:[{date,disease_name,count}] }
    │        → 질병별 추이 Multi-line Chart
    │        → [오늘/1주/1달] 필터 탭 클릭 시 재호출
    │
    └──► GET /api/dashboard/all/category-trend?period=today|week|month
             ← DASH-ALL-003
             DB: acw_cards GROUP BY date, category_mid
             → { period, data:[{date,category_mid,count}] }
             → 중분류 추이 Stacked Bar Chart
             → [오늘/1주/1달] 필터 탭 클릭 시 재호출
```

---

## 4. 실시간 파이프라인 흐름 (WebSocket)

```
클라이언트 (SCR-003)                  서버 Pipeline                    외부 / DB
      │                                      │                            │
      │── WS connect ──────────────────────► │                            │
      │   /ws/call/{call_id}?token=...       │ 인증 검증                  │
      │                                      │ 세션 초기화                │
      │                                      │ (conversation_history,     │
      │                                      │  ai_guidance 캐시)         │
      │── binary(PCM chunk) ───────────────► │                            │
      │                                      │ VAD 발화 감지              │
      │                                      │ (RTL-VOICE-001)            │
      │                                      │                            │
      │                                      │ Whisper STT ──────────────►│ OpenAI Whisper
      │                                      │◄── 발화 텍스트 ────────────│
      │                                      │                            │
      │                                      │ pyannote 화자 분리         │
      │                                      │ (RTL-VOICE-003)            │
      │                                      │ conversation_history append │
      │                                      │                            │
      │◄── conversation_update ─────────────│                            │
      │    {speaker, text, timestamp}        │                            │
      │                                      │                            │
      │◄── ai_update {status:"loading"} ────│ STEP 1 시작                │
      │                                      │                            │
      │                                      │ STEP 1 LLM ───────────────►│ gpt-4o-mini
      │                                      │ (RTL-LLM-001)              │ JSON mode
      │                                      │ input: conversation_history│
      │                                      │◄── {ready, is_oos,        │
      │                                      │     oos_type, oos_reason,  │
      │                                      │     disease_name, query}   │
      │                                      │                            │
      │                     ready=false? ────┤ 다음 발화 대기             │
      │                                      │                            │
      │                                      │ SRCH-001: 쿼리 임베딩 ────►│ text-emb-3s
      │                                      │◄── query_vector (1536d) ───│
      │                                      │                            │
      │                                      │ ┌─── 병렬 실행 ───────────┐│
      │                                      │ │                         ││
      │                                      │ │ 2-A: knowledge_chunks   ││►pgvector
      │                                      │ │ (is_oos=false 시만)     ││ cosine≥0.70
      │                                      │ │ disease_name 프리필터   ││ Top-3
      │                                      │ │                         ││
      │                                      │ │ 2-B: acw_cards          ││►pgvector
      │                                      │ │ q_embedding 검색        ││ cosine≥0.70
      │                                      │ │ (항상 실행)             ││ Top-3
      │                                      │ │                         ││
      │                                      │ │ 2-C: transfer_agencies  ││►pgvector
      │                                      │ │ description_emb 검색    ││ cosine≥0.70
      │                                      │ │ (항상 실행)             ││ Top-3
      │                                      │ └─────────────────────────┘│
      │                                      │                            │
      │◄── similar_cases ───────────────────│ 2-B 완료 즉시 push         │
      │◄── transfer_suggestion ─────────────│ 2-C 완료 즉시 push         │
      │                                      │                            │
      │                      is_oos=true? ───┤ ai_guidance 구성 (oos)     │
      │◄── ai_update {status:"oos"} ────────│ {is_oos:true, oos_reason}  │
      │                                      │                            │
      │                    2-A 결과=0? ──────┤ no_result 처리             │
      │◄── ai_update {status:"no_result"} ──│                            │
      │                                      │                            │
      │                                      │ STEP 3: AI 안내 ──────────►│ gpt-4o-mini
      │                                      │ (is_oos=false + 2-A>0)    │
      │                                      │ input: chunks + history    │
      │                                      │◄── answer (1~3문장) ───────│
      │                                      │                            │
      │                                      │ ai_guidance 캐시 구성      │
      │                                      │ {query, disease_name,      │
      │                                      │  is_oos, oos_type,         │
      │                                      │  oos_reason, answer,       │
      │                                      │  sources[]}                │
      │                                      │                            │
      │◄── ai_update {status:"success"} ────│                            │
      │    {query, disease_name, answer,     │                            │
      │     sources[{chunk_id,doc_title,     │                            │
      │     section_title,data_id,           │                            │
      │     chunk_text}]}                    │                            │
      │                                      │                            │
      │── [통화 종료] PATCH /end ───────────►│                            │
      │                                      │ conversation_history → DB ►│ calls UPDATE
      │                                      │ ai_guidance 캐시 유지      │
      │◄── WS disconnect ───────────────────│                            │
```

---

## 5. REST API 상세

### 5-1. 인증 (Auth)

---

#### `POST /api/auth/login`
> UA-AUTH-001 | SCR-001

**Request Body**
```json
{
  "username": "agent01",
  "password": "plaintext123"
}
```

**Response 200**
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "agent": {
    "agent_id": 1,
    "username": "agent01",
    "name": "김상담"
  }
}
```

**Response 401**
```json
{ "detail": "아이디 또는 비밀번호가 올바르지 않습니다." }
```

**DB 연산**
```sql
SELECT agent_id, username, name, password_hash
FROM agents
WHERE username = $1;
-- bcrypt.verify(password, password_hash) → JWT 발급
```

---

#### `POST /api/auth/logout`
> UA-AUTH-002 | GNB 팝오버 (SCR-003/004/005)

**Headers**: `Authorization: Bearer {token}`

**제약사항**: 통화 중(`calls.status = 'active'`) 상태에서 호출 시 `409 Conflict`

**Response 200**
```json
{ "message": "로그아웃 되었습니다." }
```

---

### 5-2. 계정 (Agents)

---

#### `POST /api/agents`
> UA-ACCT-001 | SCR-002 [계정 생성] 버튼

**Request Body**
```json
{
  "username": "agent01",
  "name": "김상담",
  "password": "plaintext123",
  "password_confirm": "plaintext123"
}
```
> `username`: 로그인 아이디 (UNIQUE) / `name`: 상담사 표시 이름

**Response 201**
```json
{
  "agent_id": 11,
  "username": "agent01",
  "name": "김상담",
  "created_at": "2026-05-05T09:00:00"
}
```

**Response 409** (아이디 중복)
```json
{ "detail": "이미 사용 중인 아이디입니다." }
```

**Response 400** (비밀번호 불일치)
```json
{ "detail": "비밀번호가 일치하지 않습니다." }
```

**DB 연산**
```sql
INSERT INTO agents (username, name, password_hash)
VALUES ($1, $2, bcrypt($3))
RETURNING agent_id, username, name, created_at;
```

---

#### `GET /api/agents/check-name`
> UA-ACCT-001 | SCR-002 아이디 실시간 중복 확인 (debounce)

**Query Params**: `username={아이디}`

**Response 200**
```json
{ "available": true }
```
또는
```json
{ "available": false }
```

**DB 연산**
```sql
SELECT COUNT(*) FROM agents WHERE username = $1;
```

---

#### `GET /api/agents/me`
> UA-PROF-001 | GNB (SCR-003/004/005)

**Headers**: `Authorization: Bearer {token}`

**Response 200**
```json
{
  "agent_id": 1,
  "username": "agent01",
  "name": "김상담",
  "created_at": "2026-01-05T09:00:00"
}
```

---

### 5-3. 통화 (Calls)

---

#### `POST /api/calls`
> SCR-003 [상담 시작] 버튼

**Headers**: `Authorization: Bearer {token}`

**Response 201**
```json
{
  "call_id": 101,
  "agent_id": 1,
  "status": "active",
  "started_at": "2026-05-05T10:30:00"
}
```

**DB 연산**
```sql
INSERT INTO calls (agent_id, status, started_at)
VALUES ($1, 'active', NOW())
RETURNING call_id, agent_id, status, started_at;
```

---

#### `PATCH /api/calls/{call_id}/end`
> ACW-001 | SCR-003 [통화 종료] 버튼

**Headers**: `Authorization: Bearer {token}`

**동작 순서**
1. `calls.status = 'acw'` 업데이트
2. `ended_at = NOW()`, `duration_sec` 산출
3. 서버 메모리 `conversation_history` → DB 저장

**Response 200**
```json
{
  "call_id": 101,
  "status": "acw",
  "ended_at": "2026-05-05T10:55:00",
  "duration_sec": 1500
}
```

**DB 연산**
```sql
UPDATE calls
SET status             = 'acw',
    ended_at           = NOW(),
    duration_sec       = EXTRACT(EPOCH FROM (NOW() - started_at))::INT,
    conversation_history = $jsonb
WHERE call_id = $1
RETURNING call_id, status, ended_at, duration_sec;
```

---

#### `GET /api/calls/{call_id}`
> SCR-003 화면 마운트

**Response 200**
```json
{
  "call_id": 101,
  "agent_id": 1,
  "status": "active",
  "started_at": "2026-05-05T10:30:00",
  "conversation_history": []
}
```

---

### 5-4. ACW 후처리

---

#### `GET /api/acw/{call_id}/init`
> ACW-001 | SCR-004 마운트 시 (Step A)

**Headers**: `Authorization: Bearer {token}`

**동작**
1. `calls.conversation_history` JSONB → TEXT 변환 (`[HH:MM:SS] 고객/상담사: ...`)
2. `acw_cards` shell 레코드 INSERT (or UPDATE)
3. 서버 세션에서 `ai_guidance` 캐시 조회

**Response 200**
```json
{
  "acw_id": 201,
  "transcript": "[09:30:15] 고객: 코로나19 격리 기간이 어떻게 되나요?\n[09:30:22] 상담사: 네, 안내해 드리겠습니다...",
  "ai_guidance": {
    "query": "코로나19 격리 기간",
    "disease_name": "코로나19",
    "is_oos": false,
    "oos_type": null,
    "oos_reason": null,
    "answer": "코로나19 확진자의 격리 기간은 5일입니다.",
    "sources": [
      {
        "chunk_id": 42,
        "document_title": "2025년도 코로나19 관리지침",
        "section_title": "격리 기간 및 기준",
        "data_id": "DATA-001"
      }
    ]
  },
  "acw_started_at": "2026-05-05T10:55:05"
}
```

**DB 연산**
```sql
INSERT INTO acw_cards (call_id, agent_id, source, transcript, acw_started_at)
VALUES ($1, $2, 'system', $transcript_text, NOW())
ON CONFLICT (call_id) DO UPDATE
  SET transcript    = EXCLUDED.transcript,
      acw_started_at = EXCLUDED.acw_started_at
RETURNING acw_id;
```

---

#### `POST /api/acw/{call_id}/generate`
> ACW-002 | SCR-004 마운트 시 (Step B, init 완료 후 자동 실행)

**Headers**: `Authorization: Bearer {token}`

**동작**: `transcript` + `ai_guidance` 캐시 → gpt-4o-mini JSON mode 1회 호출

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
  "qa_summary": [
    { "q": "코로나19 격리 기간이 어떻게 되나요?", "a": "확진자 격리 기간은 5일입니다." }
  ],
  "ai_response_summary": "고객은 코로나19 격리 기간에 대해 문의하였습니다. 상담사는 AI 안내를 참조하여 확진자 격리 기간이 5일임을 안내하였습니다. 고객은 안내 내용을 이해하고 상담이 종료되었습니다.",
  "is_transferred": false,
  "transfer_target": null,
  "keywords": ["코로나19", "격리", "격리기간", "확진자", "5일"]
}
```

> ※ `disease_name`은 `ai_guidance.disease_name` 직접 복사 (LLM 재추출 없음)
> ※ `ai_guidance.answer` · `sources[]`는 LLM 미처리 — 캐시 원본 그대로 Section 4 표시

---

#### `PUT /api/acw/{call_id}`
> ACW-003 · ACW-004 | SCR-004 [완료] 또는 [임시저장] 버튼

**Headers**: `Authorization: Bearer {token}`

**Request Body**
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
  "qa_summary": [{ "q": "격리 기간은?", "a": "5일입니다." }],
  "ai_response_summary": "...",
  "is_transferred": false,
  "transfer_target": null,
  "keywords": ["코로나19", "격리"],
  "ai_guidance": {
    "query": "코로나19 격리 기간",
    "disease_name": "코로나19",
    "is_oos": false,
    "oos_type": null,
    "oos_reason": null,
    "answer": "코로나19 확진자의 격리 기간은 5일입니다.",
    "sources": [{ "chunk_id": 42, "document_title": "...", "section_title": "...", "data_id": "DATA-001" }]
  },
  "is_resolved": true,
  "agent_used_ai": "yes",
  "satisfaction": 5,
  "agent_memo": "추가 자료 요청함"
}
```

**[완료] 버튼 필수 검증**

| 필드 | 조건 |
|------|------|
| `is_resolved` | 필수 |
| `agent_used_ai` | 필수 (`yes` / `partial` / `no`) |
| `category_mid` | 1개 이상 |
| `category_mid_custom` | `category="범위외"` 시 필수 |

**동작**
1. `acw_cards` 전체 UPDATE
2. `qa_summary[0].q` → text-embedding-3-small → `q_embedding` (실패 시 NULL)
3. `acw_ended_at = NOW()`, `acw_duration_sec` 산출
4. `calls.status = 'ended'` UPDATE

**Response 200**
```json
{
  "acw_id": 201,
  "call_id": 101,
  "acw_ended_at": "2026-05-05T11:10:00",
  "acw_duration_sec": 900
}
```

---

#### `GET /api/acw/{call_id}`
> SCR-004 ACW 카드 재조회

**Response 200**: `acw_cards` 전체 레코드

---

### 5-5. 대시보드 (Dashboard)

모든 `/api/dashboard/my/*` 엔드포인트는 **본인(`agent_id`) 데이터만** 집계.

---

#### `GET /api/dashboard/my/summary`
> DASH-MY-003 | SCR-005 내 통계 탭 — 총 상담 카드 · 평균 통화시간 카드

**Response 200**
```json
{
  "total_calls": 12,
  "resolved": 9,
  "unresolved": 3,
  "avg_duration_sec": 320
}
```

**DB 연산**
```sql
SELECT
  COUNT(*)                                                   AS total_calls,
  COUNT(*) FILTER (WHERE is_resolved = true)                 AS resolved,
  COUNT(*) FILTER (WHERE is_resolved = false)                AS unresolved,
  AVG(c.duration_sec)::INT                                   AS avg_duration_sec
FROM acw_cards a
JOIN calls c USING (call_id)
WHERE a.agent_id = $1
  AND DATE(a.created_at) = CURRENT_DATE;
```

---

#### `GET /api/dashboard/my/today`
> DASH-MY-001 | SCR-005 내 통계 탭 — 대분류/중분류 Bar Chart

**Response 200**
```json
{
  "total": 12,
  "by_major": [
    { "category_major": "코로나19", "count": 5 },
    { "category_major": "인플루엔자", "count": 3 }
  ],
  "by_mid": [
    { "category_mid": "격리", "count": 4 },
    { "category_mid": "확진", "count": 3 }
  ]
}
```

---

#### `GET /api/dashboard/my/keywords`
> DASH-MY-002 | SCR-005 내 통계 탭 — Top 10 키워드

**Response 200**
```json
{
  "keywords": [
    { "keyword": "코로나19", "count": 8 },
    { "keyword": "격리", "count": 6 }
  ]
}
```

**DB 연산**
```sql
SELECT kw AS keyword, COUNT(*) AS count
FROM acw_cards,
     jsonb_array_elements_text(keywords) AS kw
WHERE agent_id = $1
  AND DATE(created_at) = CURRENT_DATE
GROUP BY kw
ORDER BY count DESC
LIMIT 10;
```

---

#### `GET /api/dashboard/my/weekly-trend`
> DASH-MY-004 | SCR-005 내 통계 탭 — 주간 트렌드 Multi-line Chart

**Response 200**
```json
{
  "data": [
    { "date": "2026-04-29", "disease_name": "코로나19", "count": 3 },
    { "date": "2026-04-29", "disease_name": "인플루엔자", "count": 1 },
    { "date": "2026-04-30", "disease_name": "코로나19", "count": 5 }
  ]
}
```

**DB 연산**
```sql
SELECT DATE(created_at) AS date, disease_name, COUNT(*) AS count
FROM acw_cards
WHERE agent_id = $1
  AND created_at >= DATE_TRUNC('week', CURRENT_DATE)
  AND disease_name IS NOT NULL
GROUP BY DATE(created_at), disease_name
ORDER BY date, count DESC;
```

---

#### `GET /api/dashboard/all/summary`
> DASH-ALL-001 | SCR-005 전체 통계 탭 — 기간별 총 건수 카드 · 시간대별 Bar Chart

**Response 200**
```json
{
  "today": 45,
  "this_week": 312,
  "this_month": 1203,
  "hourly": [
    { "hour": 9,  "count": 12 },
    { "hour": 10, "count": 18 },
    { "hour": 11, "count": 22 }
  ]
}
```

---

#### `GET /api/dashboard/all/disease-trend`
> DASH-ALL-002 | SCR-005 전체 통계 탭 — 질병별 추이 Multi-line Chart

**Query Params**: `period` = `today` | `week` | `month`

**Response 200**
```json
{
  "period": "week",
  "data": [
    { "date": "2026-04-29", "disease_name": "코로나19", "count": 15 },
    { "date": "2026-04-29", "disease_name": "결핵",    "count": 8 }
  ]
}
```

**기간 필터 SQL 조건**

| period | WHERE 조건 |
|--------|-----------|
| today | `DATE(created_at) = CURRENT_DATE` |
| week | `created_at >= DATE_TRUNC('week', CURRENT_DATE)` |
| month | `created_at >= DATE_TRUNC('month', CURRENT_DATE)` |

---

#### `GET /api/dashboard/all/category-trend`
> DASH-ALL-003 | SCR-005 전체 통계 탭 — 중분류 추이 Stacked Bar Chart

**Query Params**: `period` = `today` | `week` | `month`

**Response 200**
```json
{
  "period": "week",
  "data": [
    { "date": "2026-04-29", "category_mid": "격리",    "count": 10 },
    { "date": "2026-04-29", "category_mid": "예방접종", "count": 7 }
  ]
}
```

---

### 5-6. 카테고리 마스터

#### `GET /api/categories`
> SCR-004 카테고리·대분류·중분류 Dropdown 데이터

**Response 200**
```json
{
  "categories": [
    { "category": "감염병",   "major": "코로나19",           "mid": "격리" },
    { "category": "감염병",   "major": "코로나19",           "mid": "확진" },
    { "category": "감염병",   "major": "예방접종",           "mid": "접종 대상" },
    { "category": "접수처리", "major": "감염병 신고 시스템", "mid": "신고 절차" },
    { "category": "접수처리", "major": "이관",               "mid": "보건소 이관" },
    { "category": "범위외",   "major": "기타 문의",          "mid": "일반 문의" }
  ]
}
```

**DB 연산**
```sql
SELECT category, major, mid
FROM category_master
ORDER BY category, major, mid;
```

---

## 6. WebSocket 이벤트 명세

### 연결

```
WS /ws/call/{call_id}?token={access_token}
```

- `call_id`: `POST /api/calls` 응답의 `call_id`
- `token`: JWT access_token (쿼리 파라미터)
- Binary frame: PCM 16kHz mono 16-bit 오디오 청크

---

### Server → Client 이벤트 (push)

| type | 트리거 | 연관 UI |
|------|--------|---------|
| `conversation_update` | 화자 분리 완료 (RTL-VOICE-003) | 우측 대화 내역 |
| `ai_update` | STEP 1 시작 / STEP 3 완료 (RTL-LLM) | 좌측 AI 안내 카드 |
| `similar_cases` | 2-B 완료 (RTL-SRCH-003) | 좌측 유사사례 카드 |
| `transfer_suggestion` | 2-C 완료 (RTL-SRCH-004) | 좌측 이관 참고 카드 |

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
// loading (STEP 1 시작 즉시)
{ "type": "ai_update", "status": "loading" }

// success (STEP 3 완료)
{
  "type": "ai_update",
  "status": "success",
  "query": "코로나19 격리 기간",
  "disease_name": "코로나19",
  "answer": "코로나19 확진자의 격리 기간은 5일입니다.",
  "sources": [
    {
      "chunk_id": 42,
      "document_title": "2025년도 코로나19 관리지침",
      "section_title": "격리 기간 및 기준",
      "data_id": "DATA-001",
      "chunk_text": "확진자는 증상 발생일로부터 5일간 격리..."
    }
  ]
}

// oos (STEP 1에서 is_oos=true 판정)
{
  "type": "ai_update",
  "status": "oos",
  "oos_type": "unrelated",
  "oos_reason": "보험 청구 관련 문의로 1339 업무 범위 외입니다."
}

// no_result (2-A 결과 0건)
{ "type": "ai_update", "status": "no_result", "query": "희귀 기생충 감염" }

// error (LLM 호출 실패)
{ "type": "ai_update", "status": "error" }
```

> `oos_type`: `"unrelated"` | `"action_required"`

---

#### `similar_cases`
```json
{
  "type": "similar_cases",
  "data": [
    {
      "acw_id": 15,
      "title": "코로나19 확진 후 격리 절차 문의",
      "similarity": 0.923,
      "qa_summary": [
        { "q": "격리 기간이 어떻게 되나요?", "a": "확진자는 5일 격리입니다." }
      ]
    }
  ]
}
```

---

#### `transfer_suggestion`
```json
{
  "type": "transfer_suggestion",
  "data": [
    {
      "org_name": "질병관리청",
      "dept_name": "코로나19대응팀",
      "phone": "1339",
      "description_summary": "코로나19 확진자 격리 및 치료 지원 담당",
      "similarity": 0.871
    }
  ]
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
│   ├── agents.py               # POST /api/agents
│   │                           # GET  /api/agents/check-name
│   │                           # GET  /api/agents/me
│   ├── calls.py                # POST /api/calls
│   │                           # PATCH /api/calls/{id}/end
│   │                           # GET   /api/calls/{id}
│   ├── acw.py                  # GET  /api/acw/{id}/init
│   │                           # POST /api/acw/{id}/generate
│   │                           # PUT  /api/acw/{id}
│   │                           # GET  /api/acw/{id}
│   ├── dashboard.py            # GET /api/dashboard/my/**
│   │                           # GET /api/dashboard/all/**
│   ├── categories.py           # GET /api/categories
│   └── ws.py                   # WS /ws/call/{call_id}
│
├── services/
│   ├── auth_service.py         # 로그인 검증, 토큰 블랙리스트
│   ├── agent_service.py        # 계정 생성, 중복 확인, 프로필 조회
│   ├── call_service.py         # 통화 생성/종료
│   ├── acw_service.py          # transcript 변환, ACW LLM, 저장
│   ├── dashboard_service.py    # 집계 쿼리 (my/all)
│   │
│   └── pipeline/               # RTL 실시간 파이프라인
│       ├── __init__.py
│       ├── session.py          # 통화 세션 (conversation_history, ai_guidance 캐시)
│       ├── voice.py            # VAD + Whisper STT + pyannote
│       ├── step1_llm.py        # STEP 1: ready/is_oos/disease_name/query
│       ├── step2_search.py     # STEP 2: 2-A/2-B/2-C 병렬 벡터 검색
│       ├── step3_llm.py        # STEP 3: AI 안내 생성
│       └── guidance_cache.py   # ai_guidance 캐시 구성/조회
│
├── schemas/                    # Pydantic 요청/응답 모델
│   ├── auth.py                 # LoginRequest, LoginResponse
│   ├── agents.py               # AgentCreate, AgentResponse
│   ├── calls.py                # CallResponse, CallEndResponse
│   ├── acw.py                  # AcwInitResponse, AcwGenerateResponse, AcwSaveRequest
│   └── dashboard.py            # 각 집계 응답 스키마
│
└── models/                     # DB row 매핑
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

| HTTP | 상황 | 예시 |
|------|------|------|
| 400 | 요청 형식 오류 / 필수 필드 누락 / 비밀번호 불일치 | SCR-002 |
| 401 | 인증 실패 / 토큰 만료 | SCR-001 로그인 실패 |
| 403 | 권한 없음 (타인 데이터 접근) | — |
| 404 | 리소스 없음 (call_id, acw_id 불일치) | — |
| 409 | 중복 (아이디 중복, 통화 중 로그아웃) | SCR-002, SCR-003 |
| 422 | Pydantic 유효성 검사 실패 | — |
| 500 | 서버 오류 / LLM 호출 실패 | — |

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

# pyannote (화자 분리)
HUGGINGFACE_TOKEN=hf-...
```

---

*API 설계서 v1.2 — 기능명세서 v3.0 · 화면설계서 v1.0 · DB 설계서 v2.0 기반*

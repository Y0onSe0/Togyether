# 테스트 명세서 v1.0
## 질병관리청 1339 콜센터 AI 지원 시스템

> 작성일: 2026-06-10

---

## 1. 테스트 범위 및 분류

| 분류 | 대상 | 방법 |
| --- | --- | --- |
| API 테스트 | REST API 엔드포인트 | 요청/응답 검증 |
| 인증 테스트 | JWT 토큰, 로그인/로그아웃 | 경계값 테스트 |
| RAG 파이프라인 테스트 | STEP 1~3, 벡터 검색 | 시나리오 기반 |
| WebSocket 테스트 | 실시간 STT 파이프라인 | 연결/이벤트 검증 |
| ACW 테스트 | 후처리 카드 생성·저장 | 플로우 검증 |
| 화면 기능 테스트 | 주요 화면 UI 플로우 | 수동 테스트 |
| 외부 API 테스트 | 검역·예방접종·감염병 통계 | 응답 구조 검증 |

---

## 2. 인증 (UA)

### TC-UA-001 | 정상 로그인

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UA-001 |
| **요구사항** | UA-AUTH-001 |
| **전제 조건** | agent01 계정 존재 (비밀번호: kdca1234!) |
| **입력** | `POST /api/auth/login` `{ "username": "agent01", "password": "kdca1234!" }` |
| **기대 결과** | HTTP 200, `access_token` 반환, `agent.username = "agent01"` |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-UA-002 | 잘못된 비밀번호 로그인

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UA-002 |
| **요구사항** | UA-AUTH-001 |
| **입력** | `POST /api/auth/login` `{ "username": "agent01", "password": "wrong" }` |
| **기대 결과** | HTTP 401, `{ "detail": "아이디 또는 비밀번호가 올바르지 않습니다." }` |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-UA-003 | 존재하지 않는 아이디 로그인

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UA-003 |
| **요구사항** | UA-AUTH-001 |
| **입력** | `POST /api/auth/login` `{ "username": "notexist", "password": "kdca1234!" }` |
| **기대 결과** | HTTP 401 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-UA-004 | 로그아웃

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UA-004 |
| **요구사항** | UA-AUTH-002 |
| **전제 조건** | 유효한 JWT 토큰 보유 |
| **입력** | `POST /api/auth/logout` `Authorization: Bearer {token}` |
| **기대 결과** | HTTP 200, `{ "message": "로그아웃 되었습니다." }` |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-UA-005 | 만료된 토큰으로 API 호출

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UA-005 |
| **요구사항** | UA-AUTH-001 |
| **입력** | `GET /api/agents/me` `Authorization: Bearer {만료된 토큰}` |
| **기대 결과** | HTTP 401, `{ "detail": "토큰이 만료되었습니다." }` |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-UA-006 | 계정 생성 — 정상

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UA-006 |
| **요구사항** | UA-ACCT-001 |
| **입력** | `POST /api/agents` `{ "username": "testuser", "name": "테스트", "password": "pass1234", "password_confirm": "pass1234" }` |
| **기대 결과** | HTTP 201, `agent_id` 반환 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-UA-007 | 계정 생성 — 아이디 중복

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UA-007 |
| **요구사항** | UA-ACCT-001 |
| **입력** | 이미 존재하는 username으로 POST |
| **기대 결과** | HTTP 409, `{ "detail": "이미 사용 중인 아이디입니다." }` |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-UA-008 | 계정 생성 — 비밀번호 불일치

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UA-008 |
| **요구사항** | UA-ACCT-001 |
| **입력** | `password="pass1234"`, `password_confirm="pass5678"` |
| **기대 결과** | HTTP 400 |
| **결과** | ☐ Pass ☐ Fail |

---

## 3. 통화 (Calls)

### TC-CALL-001 | 상담 시작

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-CALL-001 |
| **전제 조건** | 유효한 JWT 토큰 |
| **입력** | `POST /api/calls` |
| **기대 결과** | HTTP 201, `{ call_id, status: "active", started_at }` |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-CALL-002 | 통화 종료

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-CALL-002 |
| **전제 조건** | status='active'인 통화 존재 |
| **입력** | `PATCH /api/calls/{call_id}/end` |
| **기대 결과** | HTTP 200, `{ status: "acw", ended_at, duration_sec }` |
| **결과** | ☐ Pass ☐ Fail |

---

## 4. ACW 후처리

### TC-ACW-001 | ACW 초기화 (transcript 변환)

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-ACW-001 |
| **요구사항** | ACW-001 |
| **전제 조건** | status='acw'인 통화, conversation_history에 발화 데이터 존재 |
| **입력** | `GET /api/acw/{call_id}/init` |
| **기대 결과** | HTTP 200, `transcript`가 `"[HH:MM:SS] 고객/상담사: ..."` 포맷으로 변환됨, `ai_guidance` 포함 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-ACW-002 | ACW LLM 자동 생성

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-ACW-002 |
| **요구사항** | ACW-002 |
| **전제 조건** | TC-ACW-001 완료, transcript 존재 |
| **입력** | `POST /api/acw/{call_id}/generate` |
| **기대 결과** | HTTP 200, `title`, `customer_type`, `category`, `disease_name`, `qa_summary`, `keywords` 모두 non-null 반환 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-ACW-003 | ACW 완료 저장 — 필수값 누락

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-ACW-003 |
| **요구사항** | ACW-004 |
| **입력** | `PUT /api/acw/{call_id}` `is_resolved` 필드 미포함 |
| **기대 결과** | HTTP 422 또는 400 (필수값 누락 에러) |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-ACW-004 | ACW 완료 저장 — 정상

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-ACW-004 |
| **요구사항** | ACW-004 |
| **전제 조건** | TC-ACW-002 완료 |
| **입력** | `PUT /api/acw/{call_id}` 모든 필수값 포함 (`is_resolved`, `agent_used_ai`, `category_mid` 1개 이상) |
| **기대 결과** | HTTP 200, `acw_ended_at` 반환, `calls.status='ended'`로 변경, `q_embedding` 저장 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-ACW-005 | ACW 임시저장

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-ACW-005 |
| **요구사항** | ACW-004 |
| **입력** | `PUT /api/acw/{call_id}` 필수값 미포함 상태로 임시저장 |
| **기대 결과** | HTTP 200 (임시저장은 필수값 검증 없음) |
| **결과** | ☐ Pass ☐ Fail |

---

## 5. RAG 파이프라인

### TC-RAG-001 | 감염병 관련 쿼리 — Hybrid RAG 정상 검색

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-RAG-001 |
| **요구사항** | RTL-LLM-001, RTL-SRCH-002 |
| **시나리오** | 고객 발화: "코로나19 격리 기간이 어떻게 되나요?" |
| **기대 결과** | `ready=true`, `is_oos=false`, `disease_name="코로나19"`, `query` non-null, Hybrid RAG(Dense+BM25+RRF+Cross-Encoder) 2-A 검색 결과 1건 이상, `ai_update(status:success)` push |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-RAG-002 | 업무 범위 외 쿼리 (unrelated)

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-RAG-002 |
| **요구사항** | RTL-LLM-001, RTL-UI-001 |
| **시나리오** | 고객 발화: "오늘 날씨가 어떤가요?" |
| **기대 결과** | `is_oos=true`, `oos_type="unrelated"`, `oos_reason` non-null, `ai_update(status:oos)` push |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-RAG-003 | 업무 범위 외 쿼리 (action_required)

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-RAG-003 |
| **요구사항** | RTL-LLM-001 |
| **시나리오** | 고객 발화: "감염병 신고 시스템 권한 신청하고 싶어요" |
| **기대 결과** | `is_oos=true`, `oos_type="action_required"`, `ai_update(status:oos)` push |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-RAG-004 | 지식 없는 쿼리 (no_result)

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-RAG-004 |
| **요구사항** | RTL-SRCH-002 |
| **시나리오** | knowledge_chunks에 없는 희귀 질병 문의 |
| **기대 결과** | `is_oos=false`, Hybrid RAG 2-A 검색 결과 0건 (Dense·BM25·RRF 모두 미매핑), `ai_update(status:no_result)` push |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-RAG-005 | 유사사례 검색 (2-B) — 비활성화 확인

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-RAG-005 |
| **요구사항** | RTL-SRCH-003 |
| **시나리오** | 코로나19 관련 발화 |
| **기대 결과** | `similar_cases` 이벤트 미발생 (현재 ws.py에서 비활성화됨) |
| **비고** | 2-B는 현재 asyncio.sleep(0)으로 스킵 처리. 향후 활성화 시 유사도 ≥ 0.70 검증 필요 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-RAG-006 | 이관기관 검색 (2-C) — 키워드 매핑

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-RAG-006 |
| **요구사항** | RTL-SRCH-004 |
| **시나리오** | 고객 발화: "119 불러야 하나요?" (응급 키워드) |
| **기대 결과** | `transfer_suggestion` push, TRANSFER_KEYWORD_MAP에서 즉시 응급(119) 기관 반환 (임베딩 검색 없이) |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-RAG-007 | 이관기관 검색 (2-C) — 임베딩 폴백

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-RAG-007 |
| **요구사항** | RTL-SRCH-004 |
| **시나리오** | 키워드 매핑에 없는 이관 문의 |
| **기대 결과** | `transfer_suggestion` push, description_embedding 코사인 유사도 기반 Top-3 반환 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-RAG-008 | OOS에서도 2-C 실행 확인

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-RAG-008 |
| **요구사항** | RTL-SRCH-004 |
| **시나리오** | is_oos=true 상황에서 이관기관 결과가 있는 발화 |
| **기대 결과** | OOS임에도 `transfer_suggestion` push 발생 |
| **결과** | ☐ Pass ☐ Fail |

---

## 6. WebSocket

### TC-WS-001 | WebSocket 연결

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-WS-001 |
| **입력** | STT: `ws://localhost:8000/ws/stt/{call_id}?token={valid_token}&mode=single`<br>AI 파이프라인: `ws://localhost:8000/ws/call/{call_id}?token={valid_token}` |
| **기대 결과** | 연결 성공 (101 Switching Protocols) |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-WS-002 | 인증 없이 WebSocket 연결 시도

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-WS-002 |
| **입력** | `ws://localhost:8000/ws/stt/{call_id}` (token 없음) |
| **기대 결과** | 연결 거부 또는 즉시 disconnect |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-WS-003 | conversation_update 이벤트 수신

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-WS-003 |
| **요구사항** | RTL-VOICE-003 |
| **입력** | PCM 오디오 binary frame 전송 |
| **기대 결과** | `{ "type": "conversation_update", "speaker", "text", "timestamp" }` 수신 |
| **결과** | ☐ Pass ☐ Fail |

---

## 7. 대시보드

### TC-DASH-001 | 내 통계 — 오늘 상담 현황

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-DASH-001 |
| **요구사항** | DASH-MY-003 |
| **입력** | `GET /api/dashboard/my/summary` |
| **기대 결과** | HTTP 200, `{ total_calls, resolved, unresolved, avg_duration_sec }` |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-DASH-002 | 전체 통계 — 기간 필터

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-DASH-002 |
| **요구사항** | DASH-ALL-002 |
| **입력** | `GET /api/dashboard/all/disease-trend?period=week` |
| **기대 결과** | HTTP 200, `{ period: "week", data: [...] }` |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-DASH-003 | 감염병 조기경보

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-DASH-003 |
| **요구사항** | DASH-ALL-004 |
| **입력** | `GET /api/disease-stats/weekly-alert` |
| **기대 결과** | HTTP 200, `data` 배열 반환 (최대 4건), 각 항목에 `change_rate` 포함 |
| **결과** | ☐ Pass ☐ Fail |

---

## 8. 공지사항 (Notice)

### TC-NOTI-001 | 배너 조회

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-NOTI-001 |
| **요구사항** | NOTI-001 |
| **입력** | `GET /api/notice/banner` |
| **기대 결과** | HTTP 200, `{ banner_id, message, created_at }` 또는 배너 없으면 null/404 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-NOTI-002 | 배너 등록 및 삭제

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-NOTI-002 |
| **요구사항** | NOTI-001 |
| **입력** | `POST /api/notice/banner { "message": "테스트 배너" }` → `DELETE /api/notice/banner/{banner_id}` |
| **기대 결과** | POST: HTTP 201, DELETE: HTTP 200 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-NOTI-003 | 콜센터 당일 통계

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-NOTI-003 |
| **요구사항** | NOTI-002 |
| **입력** | `GET /api/notice/stats` |
| **기대 결과** | HTTP 200, `{ total_calls, active_calls, avg_duration_sec, resolution_rate }` |
| **결과** | ☐ Pass ☐ Fail |

---

## 9. 외부 API 연동

### TC-EXTN-001 | 검역관리지역 — 국가 검색

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-EXTN-001 |
| **요구사항** | EXTN-001 |
| **입력** | `GET /api/quarantine/country?country=태국` |
| **기대 결과** | HTTP 200, `diseases` 배열 반환 (또는 결과 없음 처리) |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-EXTN-002 | 검역 자유 텍스트 검색

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-EXTN-002 |
| **요구사항** | EXTN-001 |
| **입력** | `GET /api/quarantine/search?query=태국 뎅기열` |
| **기대 결과** | HTTP 200, `matched_type` 및 결과 반환 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-EXTN-003 | 예방접종 정보 검색

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-EXTN-003 |
| **요구사항** | EXTN-002 |
| **입력** | `GET /api/vaccine/search?query=인플루엔자` |
| **기대 결과** | HTTP 200, `{ title, schedule, target, side_effects }` 포함 |
| **결과** | ☐ Pass ☐ Fail |

---

## 10. 상담 내역 (History)

### TC-HIST-001 | 상담 목록 조회

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-HIST-001 |
| **요구사항** | HIST-001 |
| **입력** | `GET /api/history?page=1` |
| **기대 결과** | HTTP 200, `{ total, page, items: [...] }` |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-HIST-002 | 날짜 필터 검색

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-HIST-002 |
| **요구사항** | HIST-001 |
| **입력** | `GET /api/history?start_date=2026-06-01&end_date=2026-06-10` |
| **기대 결과** | HTTP 200, 해당 날짜 범위 내 상담만 반환 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-HIST-003 | 상담 상세 조회

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-HIST-003 |
| **요구사항** | HIST-003 |
| **입력** | `GET /api/history/{call_id}` |
| **기대 결과** | HTTP 200, `transcript`, `ai_guidance`, `qa_summary` 포함 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-HIST-004 | 타인 상담 조회 차단

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-HIST-004 |
| **요구사항** | HIST-003 |
| **입력** | agent01 토큰으로 agent02 소유 call_id 조회 |
| **기대 결과** | HTTP 403 또는 404 |
| **결과** | ☐ Pass ☐ Fail |

---

## 11. 화면 기능 테스트 (수동)

### TC-UI-001 | 로그인 후 공지사항 화면 진입

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UI-001 |
| **시나리오** | 브라우저에서 로그인 완료 |
| **기대 결과** | SCR-006 공지사항 화면으로 자동 이동, 콜센터 통계 카드 + 보도자료 목록 표시 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-UI-002 | 상담 시작 → 종료 → ACW 플로우

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UI-002 |
| **시나리오** | SCR-003 대기 중 → [상담 시작] → 발화 → [통화 종료] → SCR-004 자동 전환 → [완료] → SCR-003 대기 중 복귀 |
| **기대 결과** | 각 화면 전환 정상 동작, ACW 카드 자동 생성 및 저장 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-UI-003 | AI 안내 카드 — success 상태

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UI-003 |
| **시나리오** | 감염병 관련 발화 후 AI 안내 수신 |
| **기대 결과** | 태그(#병명 #카테고리) + 문의 텍스트 + AI 답변 + 출처 캐러셀(‹ 1/3 ›) 표시 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-UI-004 | AI 안내 카드 — oos 상태

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UI-004 |
| **시나리오** | 업무 범위 외 발화 |
| **기대 결과** | ⚠️ oos_reason 표시, 출처/RAG 답변 미표시 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-UI-005 | 대시보드 — 내 통계/전체 통계 탭 전환

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UI-005 |
| **시나리오** | SCR-005에서 탭 클릭 |
| **기대 결과** | 탭 전환 시 해당 데이터 API 재호출 및 차트 갱신 |
| **결과** | ☐ Pass ☐ Fail |

---

### TC-UI-006 | 상담 내역 필터 검색

| 항목 | 내용 |
| --- | --- |
| **테스트 ID** | TC-UI-006 |
| **시나리오** | SCR-007에서 날짜 범위 입력 후 검색 |
| **기대 결과** | 필터에 맞는 상담 목록만 표시, 페이지네이션 동작 |
| **결과** | ☐ Pass ☐ Fail |

---

## 12. 테스트 결과 요약

| 분류 | 총 케이스 | Pass | Fail | 미실시 |
| --- | --- | --- | --- | --- |
| 인증 (UA) | 8 | | | |
| 통화 (Calls) | 2 | | | |
| ACW | 5 | | | |
| RAG 파이프라인 | 7 | | | |
| WebSocket | 3 | | | |
| 대시보드 | 3 | | | |
| 공지사항 | 3 | | | |
| 외부 API | 3 | | | |
| 상담 내역 | 4 | | | |
| 화면 기능 (수동) | 6 | | | |
| **합계** | **44** | | | |

---

*테스트 명세서 v1.0 — 2026-06-10*

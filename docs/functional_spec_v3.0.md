# 기능명세서 v3.0
## 질병관리청 1339 콜센터 AI 지원 시스템

> 최종 수정: 2026-05-06

---

## 1. 요구사항 ID 체계

```
UA  = 사용자 및 인증 (User & Authentication)
    UA-ACCT = 계정관리
    UA-AUTH = 인증
    UA-PROF = 프로필

RTL = 실시간 파이프라인 (Real-Time)
    RTL-VOICE = 음성 처리
    RTL-LLM   = LLM 처리
    RTL-SRCH  = 검색
    RTL-UI    = Agent Assist 화면

ACW = 후처리 (After Call Work)

DASH = 대시보드
    DASH-MY   = 상담사 개인 통계
    DASH-ALL  = 1339 전체 통계
    DASH-NOTI = 알림
```

---

## 2. 요구사항 1: 사용자 및 인증 (UA)

### UA-ACCT / UA-AUTH / UA-PROF

| 중분류 | 세부기능 | ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 계정관리 | 계정 생성 | UA-ACCT-001 | 상담사 계정 생성 | 1. 신규 상담사 계정을 생성한다.<br>2. 입력 항목: 아이디(username), 이름(name), 비밀번호 | - username 중복 불가<br>- 인증 실패 시 오류 메시지 표시 | `username` `name` `password` | `agents` 레코드 저장<br>`{agent_id, username, name, created_at}` | 상 |
| 인증 | 로그인 | UA-AUTH-001 | 로그인 | 1. 아이디/비밀번호로 로그인한다.<br>2. 인증 실패 시 오류 메시지 표시.<br>3. 성공 시 메인 화면 이동 | — | `username` `password` | 성공: `{access_token, agent_id, name, username}`<br>실패: 에러 메시지 | 상 |
| 인증 | 로그아웃 | UA-AUTH-002 | 로그아웃 | 1. 로그아웃 버튼 클릭 시 세션 종료.<br>2. 로그인 화면으로 이동 | - 통화 중 로그아웃 불가 | `access_token` (헤더) | 토큰 무효화, 로그인 화면 리다이렉트 | 상 |
| 프로필 | 프로필 조회 | UA-PROF-001 | 프로필 조회 | 1. 로그인한 상담사의 이름을 표시한다. | - 본인 정보만 조회 | `agent_id` (세션) | `{name, username}` | 하 |

---

## 3. 요구사항 2: 실시간 파이프라인 (RTL)

### RTL-VOICE (음성 처리)

| 중분류 | 세부기능 | ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 음성 처리 | 발화 감지 | RTL-VOICE-001 | VAD 발화 감지 | 1. 실시간 통화 음성에서 묵음 구간을 감지하여 발화 단위로 분리한다.<br>2. 발화가 감지되면 STT 처리 단계로 전달한다. | - 묵음 감지 임계값은 테스트 후 조정 | 실시간 음성 스트림 | audio chunk | 상 |
| | STT 변환 | RTL-VOICE-002 | Whisper STT 변환 | 1. VAD로 분리된 발화 단위 오디오를 텍스트로 변환한다.<br>2. 변환된 텍스트는 화자 분리 단계로 전달된다. | - OpenAI Whisper 사용 | audio chunk | 발화 텍스트 | 상 |
| | 화자 분리 | RTL-VOICE-003 | pyannote 화자 분리 | 1. STT 변환 결과에 고객/상담사 레이블을 부여한다.<br>2. 분리된 발화는 `conversation_history`에 전체 누적 append된다.<br>3. append된 발화를 WebSocket으로 프론트엔드에 실시간 push하여 SCR-003 대화 내역에 표시한다. | - pyannote 모델 사용<br>- `conversation_history` 슬라이딩 윈도우 없이 전체 누적<br>- WebSocket push 타입: `conversation_update`<br>- conversation_history는 서버 메모리에서 관리, 통화 종료 시 calls 테이블에 1회 저장 | 발화 텍스트 (RTL-VOICE-002 결과) | `{speaker, text}` → `conversation_history` append<br>WebSocket push: `{type: "conversation_update", speaker, text, timestamp}` | 상 |

---

### RTL-LLM (LLM 처리)

| 중분류 | 세부기능 | ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LLM처리 | STEP 1 통합 판정 | RTL-LLM-001 | READY·OOS·질병명 통합 판정 | 1. 고객 발화마다 gpt-4o-mini를 호출하여 아래 항목을 **단일 호출**로 판정한다.<br>2. `ready=false`: 질문 의도 파악 불충분 → 검색 미실행, 다음 발화 대기<br>3. `ready=true`: 이하 항목 반환<br>&nbsp;&nbsp;&nbsp;- `is_oos`: 업무 범위 외 여부<br>&nbsp;&nbsp;&nbsp;- `oos_type`: 범위외 유형 (`unrelated` \| `action_required` \| null)<br>&nbsp;&nbsp;&nbsp;- `oos_reason`: 범위 외 사유 1줄 (is_oos=true일 때)<br>&nbsp;&nbsp;&nbsp;- `disease_name`: 감염병명 (식별된 경우, 2-A 프리필터용)<br>&nbsp;&nbsp;&nbsp;- `query`: 검색용 정제 쿼리 | - gpt-4o-mini, JSON mode<br>- ready=false 시 이후 단계 미실행<br>- 타임아웃(>2s) 시 1회 재시도<br>- LLM 1회 호출로 전부 처리<br>- 재시도 실패 시 WebSocket `{type: "ai_update", status: "error"}` push 후 다음 발화 대기 | `conversation_history` 전체 | `{ready, is_oos, oos_type, oos_reason, disease_name, query}`<br><br>**ready=false 시:**<br>`{ready: false, is_oos: null, oos_type: null, oos_reason: null, disease_name: null, query: null}`<br><br>**oos_type 값 정의:**<br>· `unrelated` (범위외): 질병관리청과 무관한 문의 (날씨, 배달 등)<br>· `action_required` (접수처리): 상담사가 내부 시스템으로 직접 처리해야 하는 문의 (권한 승인, 신고 접수 등)<br>· `null`: is_oos=false 또는 ready=false 시<br><br>**category 자동 확정 매핑:**<br>· is_oos=false → category = `'감염병'`<br>· is_oos=true, oos_type=action_required → category = `'접수처리'`<br>· is_oos=true, oos_type=unrelated → category = `'범위외'` | 상 |
| | STEP 3 AI 안내 생성 | RTL-LLM-002 | AI 안내 문장 생성 | 1. `is_oos=false`이고 2-A 검색 결과가 존재할 때만 실행된다.<br>2. knowledge_chunks 검색 결과와 conversation_history를 gpt-4o-mini에 전달하여 안내 문장을 생성한다.<br>3. 참고 자료에 없는 내용 생성을 금지한다 (hallucination 방지).<br>4. 1~3문장 이내로 생성한다. | - gpt-4o-mini 사용<br>- 2-A 결과 없으면 미실행 (no_result 처리)<br>- is_oos=true이면 미실행 | knowledge_chunks 검색 결과 (컨텍스트), conversation_history | `answer` (→ `ai_guidance.answer`로 캐싱) | 상 |
| LLM처리 | ai_guidance 캐시 구성 | RTL-LLM-003 | ai_guidance 캐시 구성 및 저장 | 1. is_oos=false인 경우: STEP 3 완료 후 아래 구조로 ai_guidance를 구성한다.<br>`{query, disease_name, is_oos, oos_type, oos_reason, answer, sources[]}`<br>sources[]: RTL-SRCH-002 결과에서 `{chunk_id, document_title, section_title, data_id}` 추출<br>2. is_oos=true인 경우: STEP 1 완료 후 구성한다.<br>`{query, disease_name=null, is_oos=true, oos_type, oos_reason, answer=null, sources=[]}`<br>3. 구성된 ai_guidance는 통화 세션에 캐싱되어 ACW 단계 입력으로 전달된다. | - is_oos 여부에 따라 구성 시점 상이<br>- sources[]는 chunk_id, document_title, section_title, data_id만 포함 (chunk_text 제외)<br>- 캐시는 통화 종료 시까지 유지 | RTL-LLM-001 결과<br>RTL-LLM-002 결과 (is_oos=false 시)<br>RTL-SRCH-002 결과 (is_oos=false 시) | `ai_guidance {query, disease_name, is_oos, oos_type, oos_reason, answer, sources[]}` | 상 |

**ai_guidance 캐시 구성 시점**

- `is_oos=false`: STEP 3 완료 후 → `{query, disease_name, is_oos, oos_type, oos_reason, answer, sources[]}`
- `is_oos=true`: STEP 1 완료 후 → `{query, disease_name=null, is_oos=true, oos_type, oos_reason, answer=null, sources=[]}`

**업데이트 이력**
- v2 (26.05.03): RTL-LLM-001: routing → `is_oos` + `oos_type` 구조로 변경. disease/system 라우팅 구분 제거 (Option B 통합 검색)
- v2 (26.05.03): RTL-LLM-002: 범위외 안내 문구 생성 → STEP 3 AI 안내 생성으로 재정의
- v2.1 (26.05.04): RTL-LLM-002 아웃풋 `ai_guidance_text` → `answer`
- v2.1 (26.05.04): RTL-LLM-003 신규 추가

---

### RTL-SRCH (검색)

| 중분류 | 세부기능 | ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 검색 | 쿼리 임베딩 | RTL-SRCH-001 | 쿼리 임베딩 생성 | 1. `ready=true`일 때 실행된다.<br>2. STEP 1에서 반환된 정제 쿼리를 text-embedding-3-small로 1536차원 벡터로 변환한다.<br>3. 변환된 벡터는 2-A, 2-B, 2-C 검색에 공통으로 사용된다. | - text-embedding-3-small 사용<br>- is_oos 여부와 무관하게 실행 (2-B, 2-C는 OOS에서도 검색 필요) | `query` (STEP 1 출력) | `query_vector` VECTOR(1536) | 상 |
| | 지식 통합 검색 | RTL-SRCH-002 | knowledge_chunks 통합 벡터 검색 (2-A) | 1. is_oos=false일 때만 실행된다.<br>2. knowledge_chunks 단일 테이블에서 감염병·시스템 지식을 통합 검색한다.<br>3. disease_name이 식별된 경우: 감염병 청크는 disease_name으로 프리필터, 시스템 청크는 항상 포함.<br>4. 코사인 유사도 0.70 이상인 청크만 반환한다.<br>5. 결과 0건 시 no_result 처리 (STEP 3 미실행). | - pgvector 코사인 유사도<br>- 유사도 임계값 ≥ 0.70<br>- Top-3 반환<br>- 감염병/시스템 분리 없이 단일 쿼리<br>- is_oos=true 시 미실행 | `query_vector`<br>`disease_name` (nullable) | Top-3 chunks<br>`[{chunk_id, chunk_text, knowledge_type, disease_name, document_title, section_title, data_id, similarity}]` | 상 |
| | 유사사례 검색 | RTL-SRCH-003 | acw_cards 유사사례 검색 (2-B) | 1. `ready=true`이면 **항상 실행**된다 (is_oos 여부 무관).<br>2. `query_vector`와 `acw_cards.q_embedding` 간 코사인 유사도로 Top-3 유사 사례를 반환한다.<br>3. 유사도 0.70 미만 결과는 반환하지 않는다.<br>4. 결과 0건 시 유사사례 카드 미표시. | - 유사도 임계값 ≥ 0.70<br>- Top-3 반환<br>- OOS 상태에서도 실행 | `query_vector` | Top-3 cases<br>`[{acw_id, title, disease_name, qa_summary, similarity}]` 또는 빈 배열 | 상 |
| | 이관기관 검색 | RTL-SRCH-004 | transfer_agencies 이관기관 검색 (2-C) | 1. `ready=true`이면 **항상 실행**된다 (is_oos 여부 무관).<br>2. `query_vector`와 `transfer_agencies.description_embedding` 간 코사인 유사도로 Top-3 관련 기관을 반환한다.<br>3. 유사도 0.70 미만 결과는 반환하지 않는다.<br>4. 결과 0건 시 이관 참고 카드 미표시. | - 유사도 임계값 ≥ 0.70<br>- Top-3 반환<br>- OOS 상태에서도 실행 | `query_vector` | Top-3 agencies<br>`[{org_name, dept_name, phone, description_summary, similarity}]` 또는 빈 배열 | 상 |

**업데이트 이력**
- v2 (26.05.03): RTL-SRCH-002+003 → 단일 통합 검색으로 병합. RTL-SRCH-004→003, RTL-SRCH-005→004 번호 변경
- v2.1 (26.05.04): RTL-SRCH-002 아웃풋에 `chunk_id`, `document_title`, `section_title`, `data_id` 추가. Top-3 반환 명시

---

### RTL-UI (Agent Assist 화면)

| 중분류 | 세부기능 | ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Agent Assist | AI 안내 카드 | RTL-UI-001 | AI 안내 카드 표시 | 아래 4가지 상태로 표시한다.<br>**① success**: is_oos=false + 2-A 결과 있음 → disease_name 태그 + 문의 텍스트 + AI 안내 문장 + 출처 캐러셀 (‹ 1/3 › 네비게이션, 카드당 문서명·미리보기·원문 보기 버튼)<br>**② oos**: is_oos=true → OOS 유형(범위외/접수처리)과 oos_reason 표시<br>**③ no_result**: is_oos=false + 2-A 결과 없음 → "관련 정보를 찾을 수 없습니다." 표시. 새 발화 처리 시작 시 loading 상태로 초기화.<br>**④ error**: LLM 호출 실패 → "AI 분석 중 오류가 발생했습니다." 표시 | - WebSocket `ai_update` 이벤트 수신<br>- 상태별 UI 분기 렌더링 | `success: {type:"ai_update", status:"success", query, disease_name, answer, sources:[{chunk_id, document_title, section_title, data_id, chunk_text}]}`<br>`oos: {type:"ai_update", status:"oos", oos_type, oos_reason}`<br>`no_result: {type:"ai_update", status:"no_result", query}`<br>`error: {type:"ai_update", status:"error"}` | 상담사 화면 AI 안내 카드 | 상 |
| Agent Assist | 유사사례 카드 | RTL-UI-002 | 유사사례 카드 표시 | 1. 유사사례 카드를 캐러셀 형태로 최대 3건 표시한다.<br>2. 유사도 0.70 이상 결과가 있을 때만 섹션을 표시한다.<br>3. 결과 0건 시 섹션 전체 미표시.<br>4. **AI 상태(success/oos/no_result) 무관하게** 결과 있으면 표시한다.<br>5. 카드 클릭 시 아코디언 방식으로 Q/A 상세 펼침. | - WebSocket `similar_cases` 이벤트 수신<br>- 유사도 임계값 ≥ 0.70<br>- OOS 상태에서도 표시 | `{type:"similar_cases", data:[{acw_id, title, similarity, qa_summary}]}` | 상담사 화면 유사사례 카드 | 상 |
| Agent Assist | 이관 참고 카드 | RTL-UI-003 | 이관 참고 카드 표시 | 1. 이관 참고 카드를 최대 3건 표시한다.<br>2. 유사도 0.70 이상 결과가 있을 때만 섹션을 표시한다.<br>3. 결과 0건 시 섹션 전체 미표시.<br>4. **AI 상태(success/oos/no_result) 무관하게** 결과 있으면 표시한다.<br>5. 각 카드에 기관명, 부서명, 전화번호, 담당업무 요약 표시. | - WebSocket `transfer_suggestion` 이벤트 수신<br>- 유사도 임계값 ≥ 0.70<br>- OOS 상태에서도 표시 | `{type:"transfer_suggestion", data:[{org_name, dept_name, phone, description_summary, similarity}]}` | 상담사 화면 이관 참고 카드 | 상 |
| Agent Assist | 대화 내역 표시 | RTL-UI-004 | 대화 내역 실시간 표시 | 1. 발화가 감지될 때마다 상담사/고객을 구분하여 말풍선 형태로 표시한다.<br>2. 상담사 발화는 우측, 고객 발화는 좌측에 표시한다.<br>3. 발화 시각(HH:MM:SS)을 함께 표시한다. | - WebSocket `conversation_update` 이벤트 수신 | `{type:"conversation_update", speaker, text, timestamp}` | SCR-003 대화 내역 패널 실시간 업데이트 | 상 |

**업데이트 이력**
- v2 (26.05.03): RTL-UI-001: routing 기반 분기 → 3-state(success/oos/no_result) 분기로 변경
- v2 (26.05.03): RTL-UI-002: in_scope 시에만 표시 → AI 상태 무관, 임계값 기반 조건부 표시로 변경
- v2 (26.05.03): RTL-UI-003: OOS 시에도 표시, `description_summary` 표시 추가
- v3.0 (26.05.06): RTL-UI-004 신규 추가 (대화 내역 실시간 표시)

---

## 4. 요구사항 3: 후처리 (ACW)

| 요구사항 ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- |
| ACW-001 | ACW 타이머 · transcript 변환 저장 | 1. 통화 종료 시 ACW 타이머 시작, 상담사 화면에 경과 시간 표시, 저장 시 종료 시각 및 소요 시간 산출.<br>2. 통화 종료 즉시 `calls.conversation_history` JSONB를 `"[HH:MM:SS] 상담사/고객: ..."` 형식의 TEXT로 변환하여 `acw_cards.transcript`에 저장한다.<br>3. transcript 저장은 ACW LLM 실행 전 선행 처리된다. | - 통화 종료 이벤트 자동 감지<br>- transcript 변환 실패 시 conversation_history 원문 그대로 저장 | `calls.ended_at`<br>`calls.conversation_history`<br>`calls.started_at` | `acw_started_at`<br>`acw_ended_at`<br>`acw_duration_sec`<br>`acw_cards.transcript` | 상 |
| ACW-002 | ACW 카드 자동 생성 | 1. **ACW-001 완료 후** transcript와 ai_guidance를 함께 gpt-4o-mini에 1회 전달하여 아래 항목을 자동 생성한다.<br>• 제목: transcript 기반 상담 내용 한 줄 요약<br>• 고객 유형: transcript 기반 자동 추천 (일반시민/의료종사자/기타), 기타 선택 시 직접 입력 필드(customer_type_custom) 활성화<br>• 민원 유형: ai_guidance.is_oos + oos_type 기반 카테고리 자동 확정<br>&nbsp;&nbsp;- is_oos=false → `'감염병'`<br>&nbsp;&nbsp;- is_oos=true, oos_type=action_required → `'접수처리'`<br>&nbsp;&nbsp;- is_oos=true, oos_type=unrelated → `'범위외'`<br>&nbsp;&nbsp;, 대분류·중분류는 `ai_guidance.query` 기반 추천, 복수 의도 감지 시 중분류 복수 추천<br>• 질병명: `ai_guidance.disease_name` 직접 복사 (LLM 재추출 불필요)<br>• QA 요약: transcript 기반 질문(Q)과 답변(A) 분리 생성 (한 상담 당 하나의 Q/A 쌍 생성)<br>• AI 상담 요약(ai_response_summary): 단일 서술형 단락 (고객문의→AI·상담사안내→처리결과 순 3~4문장)<br>• 이관 여부: ai_guidance.is_oos 참조 + transcript 기반 이관 대상 감지<br>• 키워드: `ai_guidance.query` + `ai_guidance.answer` 기반 핵심 키워드 추출<br>2. **`ai_guidance.answer` 및 `ai_guidance.sources[]`는 ACW LLM이 생성하지 않으며, 캐시에서 그대로 섹션 4에 표시된다 (읽기 전용).**<br>3. 상담사는 자동 생성된 내용을 검토 후 수정·저장한다. | - 모델: gpt-4o-mini, JSON mode<br>- 카테고리: 감염병 / 접수처리 / 범위외<br>- 대분류: 감염병증상·예방, 생활속감염, 통계·현황, 지원·복지, 기관연결, 상담진행, 행정처리<br>- 중분류: 실제 데이터 기반 47개 항목<br>- 범위외 선택 시 category_mid_custom 직접 입력<br>- disease_name은 LLM 생성 없이 ai_guidance.disease_name 직접 사용<br>- ai_guidance.answer·sources[]는 LLM 미처리, 캐시 원본 그대로 전달 | `acw_cards.transcript` (ACW-001 변환본)<br>`ai_guidance {query, disease_name, answer, is_oos, oos_type, oos_reason, sources[]}` | title / customer_type / customer_type_custom<br>category / category_major / category_mid<br>category_mid_list / category_mid_custom<br>disease_name / qa_summary / ai_response_summary<br>is_transferred / transfer_target / keywords | 상 |
| ACW-003 | 상담사 ACW 카드 입력 | LLM 생성 필드 수정 가능. 상담사가 처리 결과, AI 활용 여부, 만족도, 메모 입력. 민원 유형 수정 시 카테고리→대분류→중분류 드롭다운 연동, 중분류 다중 선택 가능. 범위외 선택 시 직접 입력, 해결/미해결 직접 선택 가능.<br>· `agent_used_ai`: 상담 중 AI 안내 활용 여부 필수 선택 (yes / partial / no)<br>· `satisfaction`: AI 답변 만족도 1~5 선택 (선택 입력) | - 처리 결과(`is_resolved`) 필수 선택<br>- `agent_used_ai` 필수 선택<br>- 중분류 1개 이상 필수<br>- 범위외 시 `category_mid_custom` 필수<br>- 상담사 정보·날짜 자동 입력, 수정 불가<br>- 섹션 4 (AI 처리 내역) 읽기 전용, 상담사 수정 불가 | 상담사 직접 입력값<br>+ ACW-002 생성값 | `agent_id`<br>`is_resolved`<br>`agent_used_ai`<br>`satisfaction`<br>`agent_memo`<br>`category`<br>`category_major`<br>`category_mid`<br>`category_mid_list`<br>`category_mid_custom` | 상 |
| ACW-004 | ACW 카드 저장 및 임베딩 | 1. 저장 버튼 클릭 시 아래 4가지 분류로 통합 저장한다.<br>· [LLM 생성] `title`, `customer_type`, `customer_type_custom`, `category` 계열, `disease_name`, `qa_summary`, `ai_response_summary`, `is_transferred`, `transfer_target`, `keywords`<br>· [캐시 직접] `ai_guidance {query, disease_name, answer, is_oos, oos_type, oos_reason, sources[]}` — LLM 재처리 없이 캐시 원본 그대로 저장<br>· [원본 보존] `transcript` — ACW-001에서 변환된 전문 텍스트<br>· [상담사 입력] `is_resolved`, `agent_used_ai`, `satisfaction`, `agent_memo`<br>2. 저장 후 `qa_summary`의 Q 텍스트를 text-embedding-3-small로 임베딩하여 `q_embedding` 저장.<br>3. 저장 완료 후 ACW 종료 및 대기 상태 전환. | - 필수 필드 미입력 시 저장 불가<br>- 임베딩 실패 시 NULL 저장 (카드 저장은 정상 처리)<br>- 임베딩 대상: Q 텍스트만<br>- ai_guidance는 재생성 없이 캐시 원본 그대로 저장 | ACW-002 생성값<br>+ ACW-003 입력값<br>+ ai_guidance 캐시<br>+ transcript (ACW-001 변환본) | `acw_cards` 레코드 전체 저장<br>(ai_guidance JSONB 포함)<br>`transcript` TEXT 저장<br>`agent_used_ai`, `satisfaction` 저장<br>`q_embedding` (1536d) | 상 |

**업데이트 이력 (v3.0, 26.05.04)**
- ACW-001: transcript 자동 변환 저장 기능 추가
- ACW-002: `ai_response_summary` 정의 변경, 카테고리 `'시스템'` → `'접수처리'` 변경, qa_summary 한 쌍 생성 명시
- ACW-003: `agent_used_ai` 필수 입력 추가, `satisfaction` 정의 명확화, 섹션 4 읽기 전용 명시
- ACW-004: 저장 항목 4분류 명시, `transcript`, `agent_used_ai`, `satisfaction` 아웃풋 추가

---

## 5. 요구사항 4: 대시보드 (DASH)

| 중분류 | 세부기능 | ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 상담사 개인 통계 | 오늘 문의 현황 | DASH-MY-001 | 오늘 문의 현황 | 1. 로그인한 상담사 본인의 오늘 총 문의 건수를 표시한다.<br>2. 대분류별 문의 건수를 bar chart로 표시한다.<br>3. 중분류(질병명)별 문의 건수를 bar chart로 표시한다. | - 본인 데이터(`agent_id`)만 집계 | `agent_id` (세션)<br>`date = CURRENT_DATE` | 총 문의 건수<br>`[{category_major, count}]`<br>`[{category_mid, count}]` | 상 |
| | 많이 나온 질문 | DASH-MY-002 | 오늘 많이 나온 질문 | 1. 오늘 상담에서 추출된 키워드를 집계하여 Top 10을 표시한다.<br>2. 키워드와 빈도수를 함께 표시한다. | - `acw_cards.keywords` JSONB unnest 집계 | `agent_id` (세션)<br>`date = CURRENT_DATE` | Top 10 키워드 배열<br>`[{keyword, count}]` | 상 |
| | 내 상담 현황 | DASH-MY-003 | 내 상담 현황 | 1. 오늘 본인의 총 상담 건수를 표시한다. (미해결/해결 건수 sub 표시)<br>2. 평균 통화 시간(AHT)을 표시한다. | - 오늘(`CURRENT_DATE`) 기준 집계 | `agent_id` (세션)<br>`date = CURRENT_DATE` | `total_calls`<br>`unresolved_count`<br>`resolved_count`<br>`avg_call_duration_sec` | 상 |
| | 이번 주 트렌드 | DASH-MY-004 | 이번 주 트렌드 | 1. 이번 주(`DATE_TRUNC('week')`) 날짜별 × 질병별 문의 건수를 multi-line chart로 표시한다. | - 본인 데이터만 집계 | `agent_id` (세션)<br>`week_start = DATE_TRUNC('week', CURRENT_DATE)` | `[{date, disease_name, count}]` | 상 |
| 1339 전체 통계 | 전체 문의 현황 | DASH-ALL-001 | 전반적인 감염병 문의 현황 | 1. 오늘/이번주/한달 전체 문의 건수를 카드 3개로 표시한다.<br>2. 시간대별 문의 건수 분포를 bar chart로 표시한다. | - 전체 상담사 데이터 집계 | acw_cards 테이블 기반 | `{today, this_week, this_month}`<br>`[{hour, count}]` | 상 |
| | 기간별 병 추이 | DASH-ALL-002 | 기간별 병 추이 그래프 | 1. 기간별 `disease_name`별 문의 건수를 multi-line chart로 표시한다.<br>2. 기간 선택 옵션을 제공한다(오늘/1주/1달). | - 기간 필터 선택 가능 | `period` (오늘\|1주\|1달) | `[{date, disease_name, count}]` | 상 |
| | 기간별 중분류 추이 | DASH-ALL-003 | 기간별 중분류 추이 그래프 | 1. 기간별 `category_mid`별 문의 건수를 stacked bar chart로 표시한다.<br>2. 기간 선택 옵션을 제공한다(오늘/1주/1달). | - 기간 필터 선택 가능 | `period` (오늘\|1주\|1달) | `[{date, category_mid, count}]` | 상 |
| 알림 | 지침 변경 알림 | DASH-NOTI-001 | 지침 변경 알림 표시 | 1. 감염병 지침 변경 알림을 대시보드 상단 배너로 표시한다.<br>2. DB 연동 없이 프론트엔드 하드코딩으로 표시한다.<br>예) "2026.04.15 코로나19 격리 지침 변경" | - DB 미연동, 프론트 하드코딩 | 없음 (하드코딩) | `[{date, message}]` (정적) | 하 |

---

## 6. 우선순위 기준

| 우선순위 | 기준 |
| --- | --- |
| **상** | 핵심 기능 — 없으면 서비스 불가 |
| **중** | 중요 기능 — MVP 이후 포함 |
| **하** | 부가 기능 — 여유 시 구현 |

---

*기능명세서 v3.0 — 2026-05-06*

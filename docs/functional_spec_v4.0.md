# 기능명세서 v4.0
## 질병관리청 1339 콜센터 AI 지원 시스템

> 최종 수정: 2026-06-10
> DB: Supabase (PostgreSQL + pgvector) 배포 환경 반영
> v4.0 주요 변경:
> - RTL-VOICE-002: Whisper STT → Deepgram Nova-3 (single/dual 모드), 의료 도메인 텍스트 정규화 추가
> - DASH-NOTI-001: 프론트 하드코딩 → DB 연동 배너 관리로 변경
> - 신규 요구사항 추가: EXTN(외부 API), NOTI(공지사항), HIST(상담 내역)

---

## 1. 요구사항 ID 체계

```
UA   = 사용자 및 인증 (User & Authentication)
RTL  = 실시간 파이프라인 (Real-Time)
ACW  = 후처리 (After Call Work)
DASH = 대시보드
EXTN = 외부 API 연동 (External API)
NOTI = 공지사항 (Notice)
HIST = 상담 내역 (History)
```

---

## 2. 요구사항 1: 사용자 및 인증 (UA)

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
| 음성 처리 | 발화 감지 | RTL-VOICE-001 | VAD 발화 감지 | 1. 실시간 통화 음성에서 묵음 구간을 감지하여 발화 단위로 분리한다.<br>2. 발화가 감지되면 STT 처리 단계로 전달한다. | - 묵음 감지 임계값은 테스트 후 조정 | 실시간 음성 스트림 (PCM 16kHz) | audio chunk | 상 |
| | STT 변환 | RTL-VOICE-002 | Deepgram Nova-3 STT 변환 | 1. VAD로 분리된 발화 단위 오디오를 Deepgram Nova-3 API로 텍스트 변환한다.<br>2. 운영 모드: `single`(diarize 기반 화자 분리) / `dual`(듀얼 채널 분리)<br>3. 변환된 텍스트는 의료 도메인 정규화(한글 숫자 변환, 오인식 단어 치환) 후 화자 분리 단계로 전달된다. | - **Deepgram Nova-3** 사용 (구 Whisper 대체)<br>- WebSocket 쿼리 파라미터 `mode=single\|dual`로 모드 선택<br>- 스트리밍 방식으로 Deepgram API에 전송 | audio chunk | 발화 텍스트 (정규화 완료) + 화자 레이블 | 상 |
| | 화자 분리 | RTL-VOICE-003 | 화자 분리 및 대화 이력 누적 | 1. STT 결과에 고객/상담사 레이블을 부여한다.<br>2. 분리된 발화는 `conversation_history`에 전체 누적 append된다.<br>3. WebSocket으로 프론트에 실시간 push하여 SCR-003 대화 내역에 표시한다. | - single 모드: diarize 기반 / dual 모드: 채널 분리<br>- `conversation_history` 슬라이딩 윈도우 없이 전체 누적<br>- 통화 종료 시 calls 테이블에 1회 저장 | 발화 텍스트 + 화자 레이블 | `{speaker, text}` → conversation_history append<br>WebSocket push: `{type:"conversation_update", speaker, text, timestamp}` | 상 |

---

### RTL-LLM (LLM 처리)

| 중분류 | 세부기능 | ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LLM처리 | STEP 1 통합 판정 | RTL-LLM-001 | READY·OOS·질병명 통합 판정 | 1. 고객 발화마다 gpt-4.1-mini를 호출하여 단일 호출로 판정한다.<br>2. `ready=false`: 질문 의도 파악 불충분 → 검색 미실행, 다음 발화 대기<br>3. `ready=true` 시 반환:<br>&nbsp;&nbsp;- `is_oos`: 업무 범위 외 여부<br>&nbsp;&nbsp;- `oos_type`: `unrelated`\|`action_required`\|null<br>&nbsp;&nbsp;- `oos_reason`: 범위 외 사유 1줄<br>&nbsp;&nbsp;- `disease_name`: 감염병명 (2-A 프리필터용)<br>&nbsp;&nbsp;- `query`: 검색용 정제 쿼리 | - **gpt-4.1-mini**, JSON mode<br>- 키워드 프리필터 → LLM 폴백 방식<br>- 중복 발화 코사인 유사도 필터링 | `conversation_history` 전체 | `{ready, is_oos, oos_type, oos_reason, disease_name, query}` | 상 |
| | STEP 3 AI 안내 생성 | RTL-LLM-002 | AI 안내 문장 생성 | 1. `is_oos=false`이고 2-A 검색 결과가 존재할 때만 실행된다.<br>2. knowledge_chunks 검색 결과 + conversation_history → gpt-4o-mini로 안내 문장 생성<br>3. 참고 자료에 없는 내용 생성 금지 (hallucination 방지)<br>4. 1~3문장 이내로 생성 | - gpt-4o-mini<br>- 2-A 결과 없으면 미실행 (no_result 처리) | knowledge_chunks 검색 결과, conversation_history | `answer` | 상 |
| | ai_guidance 캐시 | RTL-LLM-003 | ai_guidance 캐시 구성 및 저장 | 1. is_oos=false: STEP 3 완료 후 구성<br>`{query, disease_name, is_oos, oos_type, oos_reason, answer, sources[]}`<br>2. is_oos=true: STEP 1 완료 후 구성<br>`{query, disease_name=null, is_oos=true, oos_type, oos_reason, answer=null, sources=[]}`<br>3. 통화 세션에 캐싱 → ACW 단계 입력으로 전달 | - sources[]는 chunk_id, document_title, section_title, data_id만 포함 (chunk_text 제외) | RTL-LLM-001/002 결과, RTL-SRCH-002 결과 | `ai_guidance {query, disease_name, is_oos, oos_type, oos_reason, answer, sources[]}` | 상 |

---

### RTL-SRCH (검색)

| 중분류 | 세부기능 | ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 검색 | 쿼리 임베딩 | RTL-SRCH-001 | 쿼리 임베딩 생성 | ready=true 시 정제 쿼리를 text-embedding-3-small로 1536차원 벡터 변환. 2-A/C에 공통 사용 | - is_oos 무관하게 실행 | `query` | `query_vector` VECTOR(1536) | 상 |
| | 지식 통합 검색 | RTL-SRCH-002 | knowledge_chunks Hybrid RAG 검색 (2-A) | is_oos=false 시만 실행.<br>① Dense 검색: text-embedding-3-small 임베딩 기반 NumPy 코사인 유사도 (인메모리 캐시)<br>② BM25 검색: rank-bm25 라이브러리 기반 키워드 검색 (인메모리)<br>③ RRF(Reciprocal Rank Fusion): Dense + BM25 결과 병합<br>④ Cross-Encoder Reranking: bongsoo/klue-cross-encoder-v1 (sentence-transformers 설치 시 자동 활성화)<br>disease_name 있으면 감염병 청크 프리필터 적용. system 청크 항상 포함. 최종 Top-3 반환 | - 인메모리 캐시: 서버 기동 후 첫 RAG 요청 시 DB 전체 청크 로드 (lazy load)<br>- Cross-Encoder는 선택적 활성화 | `query_vector`, `query`, `disease_name` | `[{chunk_id, chunk_text, document_title, section_title, data_id, score}]` Top-3 | 상 |
| | 유사사례 검색 | RTL-SRCH-003 | acw_cards 유사사례 검색 (2-B) | **현재 비활성화** (ws.py에서 asyncio.sleep(0)으로 스킵 처리됨) | - 향후 활성화 예정 | `query_vector` | — | 하 |
| | 이관기관 검색 | RTL-SRCH-004 | transfer_agencies 이관기관 검색 (2-C) | ready=true 시 항상 실행.<br>① 키워드 매핑 우선: TRANSFER_KEYWORD_MAP에 등록된 키워드(응급/119, 에이즈, 결핵 등) 즉시 반환<br>② 임베딩 검색 폴백: 키워드 미매핑 시 description_embedding 코사인 유사도 Top-3 | - OOS에서도 실행<br>- 키워드 매핑 히트 시 임베딩 검색 생략 | `query`, `query_vector` | `[{org_name, dept_name, phone, description_summary}]` | 상 |

---

### RTL-UI (Agent Assist 화면)

| 중분류 | 세부기능 | ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Agent Assist | AI 안내 카드 | RTL-UI-001 | AI 안내 카드 표시 | 4가지 상태로 표시<br>① success: 태그+문의+AI 답변+출처 캐러셀<br>② oos: OOS 유형 + oos_reason<br>③ no_result: "관련 정보를 찾을 수 없습니다."<br>④ error: "AI 분석 중 오류가 발생했습니다." | - WebSocket `ai_update` 수신 | ai_update 이벤트 | AI 안내 카드 UI | 상 |
| | 유사사례 카드 | RTL-UI-002 | 유사사례 카드 표시 | 유사도 ≥0.40 결과 있을 때 캐러셀로 최대 5건 표시. **현재 2-B 비활성화로 미표시**. 향후 활성화 시 카드 클릭 Q/A 아코디언 펼침 | - similar_cases 이벤트 수신 | 유사사례 카드 | 하 |
| | 이관 참고 카드 | RTL-UI-003 | 이관 참고 카드 표시 | 유사도 ≥0.60 결과 있을 때 최대 5건 표시. AI 상태 무관. 기관명·부서명·전화번호·설명 표시 | - transfer_suggestion 이벤트 수신 | 이관 참고 카드 | 상 |
| | 대화 내역 표시 | RTL-UI-004 | 대화 내역 실시간 표시 | 발화 감지 시 상담사/고객 구분하여 말풍선 표시. 상담사 우측, 고객 좌측. 발화 시각(HH:MM:SS) 표시 | - conversation_update 이벤트 수신 | conversation_update 이벤트 | SCR-003 대화 내역 패널 | 상 |

---

## 4. 요구사항 3: 후처리 (ACW)

| 요구사항 ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- |
| ACW-001 | ACW 타이머 · transcript 변환 저장 | 1. 통화 종료 시 ACW 타이머 시작, 경과 시간 표시, 저장 시 소요 시간 산출.<br>2. calls.conversation_history JSONB → "[HH:MM:SS] 상담사/고객: ..." TEXT 변환 → acw_cards.transcript 저장<br>3. transcript 저장은 ACW LLM 실행 전 선행 처리 | - 변환 실패 시 원문 저장 | calls.ended_at / conversation_history / started_at | acw_started_at / transcript | 상 |
| ACW-002 | ACW 카드 자동 생성 | transcript + ai_guidance → gpt-4o-mini 1회 호출<br>· 제목 / 고객 유형 / 민원 유형 / 대분류·중분류 / 질병명 / QA요약 / AI상담요약 / 이관여부 / 키워드 자동 생성<br>· disease_name: ai_guidance.disease_name 직접 복사 (LLM 재추출 없음)<br>· ai_guidance.answer·sources[]: 캐시 그대로 Section 4 표시 (LLM 미처리) | - gpt-4o-mini, JSON mode<br>- 카테고리: 감염병/접수처리/범위외 | transcript, ai_guidance 캐시 | title / customer_type / category 계열 / disease_name / qa_summary / ai_response_summary / is_transferred / keywords | 상 |
| ACW-003 | 상담사 ACW 카드 입력 | LLM 생성 필드 수정 가능. 처리 결과·AI 활용 여부·만족도·메모 입력.<br>· agent_used_ai: yes/partial/no 필수<br>· satisfaction: 1~5 선택<br>· 섹션 4 (AI 처리 내역) 읽기 전용 | - is_resolved 필수<br>- agent_used_ai 필수<br>- 중분류 1개 이상 필수 | 상담사 직접 입력값 | is_resolved / agent_used_ai / satisfaction / agent_memo / 카테고리 계열 | 상 |
| ACW-004 | ACW 카드 저장 및 임베딩 | 완료 버튼 클릭 시 전체 저장.<br>저장 후 qa_summary Q 텍스트 → text-embedding-3-small → q_embedding 저장.<br>저장 완료 후 ACW 종료 및 대기 상태 전환 | - 임베딩 실패 시 NULL (카드 저장은 정상)<br>- ai_guidance 재생성 없이 캐시 원본 저장 | ACW-002 생성값 + ACW-003 입력값 + ai_guidance 캐시 + transcript | acw_cards 전체 저장 + q_embedding | 상 |

---

## 5. 요구사항 4: 대시보드 (DASH)

| 중분류 | 세부기능 | ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 상담사 개인 통계 | 오늘 문의 현황 | DASH-MY-001 | 오늘 문의 현황 | 본인의 오늘 총 문의 건수, 대분류별/중분류별 Bar Chart | - 본인 데이터만 | agent_id, CURRENT_DATE | 총 건수, [{category_major,count}], [{category_mid,count}] | 상 |
| | 많이 나온 질문 | DASH-MY-002 | 오늘 많이 나온 질문 | keywords JSONB unnest 집계 Top 10 | - 본인 데이터만 | agent_id, CURRENT_DATE | [{keyword, count}] Top 10 | 상 |
| | 내 상담 현황 | DASH-MY-003 | 내 상담 현황 | 오늘 총 상담 건수(해결/미해결), 평균 통화 시간(AHT) | - CURRENT_DATE 기준 | agent_id, CURRENT_DATE | total_calls / resolved / unresolved / avg_duration_sec | 상 |
| | 이번 주 트렌드 | DASH-MY-004 | 이번 주 트렌드 | DATE_TRUNC('week') 기준 날짜×질병별 Multi-line Chart | - 본인 데이터만 | agent_id, week_start | [{date, disease_name, count}] | 상 |
| 1339 전체 통계 | 전체 문의 현황 | DASH-ALL-001 | 전반적인 감염병 문의 현황 | 오늘/이번주/한달 전체 건수 카드 3개 + 시간대별 Bar Chart | - 전체 상담사 집계 | acw_cards | {today, this_week, this_month}, [{hour,count}] | 상 |
| | 기간별 병 추이 | DASH-ALL-002 | 기간별 병 추이 그래프 | disease_name별 문의 건수 Multi-line Chart (오늘/1주/1달 필터) | - 기간 필터 선택 | period | [{date, disease_name, count}] | 상 |
| | 기간별 중분류 추이 | DASH-ALL-003 | 기간별 중분류 추이 그래프 | category_mid별 문의 건수 Stacked Bar Chart (오늘/1주/1달 필터) | - 기간 필터 선택 | period | [{date, category_mid, count}] | 상 |
| | 감염병 조기경보 | DASH-ALL-004 | 감염병 조기경보 위젯 | 공공데이터포털 통계 기반 전주 대비 발생 증감 Top 4 표시. 증가율(%) 강조 표시 | - 1시간 TTL 캐시<br>- 공공데이터포털 API 연동 | /api/disease-stats/weekly-alert | [{disease_name, this_week, last_week, change_rate}] Top 4 | 상 |
| 알림 | 지침 변경 알림 | DASH-NOTI-001 | 지침 변경 알림 표시 | 감염병 지침 변경 알림을 대시보드 상단 배너로 표시.<br>**DB 연동** — notice_banners 테이블에서 최신 1건 조회.<br>관리자: POST /api/notice/banner로 등록, DELETE로 삭제 가능 | **DB 연동** (구 하드코딩 방식 제거)<br>- 배너 없으면 미표시 | /api/notice/banner | {banner_id, message, created_at} | 중 |

---

## 6. 요구사항 5: 외부 API 연동 (EXTN)

| 중분류 | 세부기능 | ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 검역 | 검역관리지역 조회 | EXTN-001 | 해외검역관리지역 정보 제공 | 1. 공공데이터포털 검역관리지역 API 연동<br>2. 국가명 또는 감염병명 기반 검역 정보 조회<br>3. 자유 텍스트 입력 시 자동 감지 후 적절한 API 호출<br>4. SCR-003 이관 카드 영역에 검역 정보 표시 | - 24시간 TTL 캐시<br>- 2022년 이전 데이터 필터링<br>- 매칭 실패 시 유용한 링크 제공 | country / disease_code / query | 검역감염병 목록, 위험군, 감시기간 | 상 |
| 예방접종 | 예방접종 정보 조회 | EXTN-002 | 예방접종 정보 제공 | 1. 공공데이터포털 예방접종 API 연동<br>2. 병명 키워드 → vcnCd 변환 → API 호출<br>3. OpenAI LLM으로 응답 파싱·구조화<br>4. SCR-003 AI 카드에 예방접종 관련 정보 보강 | - 24시간 TTL 캐시<br>- 키워드 매칭 실패 시 null 반환 | query (병명) | {title, summary, schedule, target, side_effects} | 상 |
| 감염병 통계 | 감염병 발생 통계 | EXTN-003 | 공공데이터 감염병 통계 제공 | 1. 공공데이터포털 질병관리청 통계 API 연동<br>2. 감염병별/성별/연령별 발생 현황 제공<br>3. 1339 콜 건수와 통합 데이터 제공<br>4. 전주 대비 증감 조기경보 (Top 4) | - 1시간 TTL 캐시<br>- 디버그·캐시 초기화 엔드포인트 제공 | 연도, 통계 유형, 기간 | 감염병별/성별/연령별 통계, 주간 증감 | 상 |

---

## 7. 요구사항 6: 공지사항 (NOTI)

| 중분류 | 세부기능 | ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 공지 배너 | 배너 조회/관리 | NOTI-001 | 공지 배너 DB 관리 | 1. notice_banners 테이블에서 최신 배너 1건 조회<br>2. POST로 새 배너 등록, DELETE로 삭제<br>3. SCR-005 대시보드 및 SCR-006 공지사항 상단에 표시 | - 인증 필요 | message | {banner_id, message, created_at} | 중 |
| 콜센터 통계 | 당일 통계 | NOTI-002 | 콜센터 당일 운영 통계 | 1. 오늘 총 통화 건수, 현재 활성 통화 수, 평균 통화 시간, 해결률 실시간 집계<br>2. SCR-006 공지사항 상단 통계 카드로 표시 | - 인증 필요 | — | {total_calls, active_calls, avg_duration_sec, resolution_rate} | 중 |
| 보도자료 | 보도자료 크롤링/조회 | NOTI-003 | 질병관리청 보도자료 제공 | 1. 질병관리청 웹사이트 보도자료 크롤링<br>2. POST /api/notice/crawl로 수동 크롤링 실행<br>3. 목록 페이지네이션 조회 (GET /api/notice/press) | - 인증 필요 | page | [{title, url, date}] | 중 |

---

## 8. 요구사항 7: 상담 내역 (HIST)

| 중분류 | 세부기능 | ID | 요구사항명 | 요구사항 설명 | 제약사항 | 인풋 | 아웃풋 | 우선순위 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 상담 목록 | 목록 조회 | HIST-001 | 상담 내역 목록 조회 | 1. 본인의 상담 목록을 페이지네이션으로 조회한다.<br>2. 필터: 날짜 범위, 질병명<br>3. 각 항목: 질병명, 카테고리, 해결 여부, 만족도, 통화 시간 표시 | - 본인 데이터만 | start_date, end_date, disease, page, page_size | [{call_id, disease_name, category, is_resolved, satisfaction, duration_sec, created_at}] | 상 |
| | 요약 통계 | HIST-002 | 상담 내역 요약 통계 | 1. 총 상담 건수, 오늘 건수, 해결/이관 건수, 해결률, 평균 통화 시간 표시<br>2. SCR-007 상단 통계 카드로 표시 | - 본인 데이터만 | agent_id | {total, today, resolved, transferred, resolution_rate, avg_duration_sec} | 상 |
| 상담 상세 | 상세 조회 | HIST-003 | 상담 상세 정보 조회 | 1. 특정 상담의 전사본, AI 응답, 카테고리, 메모 등 전체 정보 조회<br>2. 클릭 시 모달로 표시 | - 본인 데이터만 | call_id | 상담 전체 필드 (transcript, ai_guidance, qa_summary 등) | 상 |

---

## 9. 우선순위 기준

| 우선순위 | 기준 |
| --- | --- |
| **상** | 핵심 기능 — 없으면 서비스 불가 |
| **중** | 중요 기능 — MVP 이후 포함 |
| **하** | 부가 기능 — 여유 시 구현 |

---

*기능명세서 v4.0 — 2026-06-10*

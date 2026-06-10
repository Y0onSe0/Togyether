-- ============================================================
--  질병관리청 1339 콜센터 AI 지원 시스템  DB 스키마 v2.1
--  PostgreSQL 16 + pgvector
--  작성일: 2026-05-05
--  수정일: 2026-05-06
--    v2.1 변경사항:
--      - agents: username 컬럼 추가 (로그인 아이디, UNIQUE)
--      - acw_cards.ai_guidance: oos_type 필드 추가
--      - category_master: '시스템'→'접수처리', '이관'→'접수처리', '기타'→'범위외'
--      - category_master 코멘트 갱신
--
--  테이블 구성 (6개)
--  ┌─ 운영 ──────────────────────────────────────────────────┐
--  │  agents          상담사 계정                             │
--  │  calls           통화 세션                              │
--  │  acw_cards       ACW 후처리 카드 (system + ai_hub)       │
--  ├─ RAG ───────────────────────────────────────────────────┤
--  │  knowledge_chunks 통합 지식 청크 (감염병지침/FAQ/매뉴얼) │
--  │  transfer_agencies 이관기관 정보                         │
--  ├─ 유틸 ──────────────────────────────────────────────────┤
--  │  category_master  ACW 분류 드롭다운 시드                 │
--  └─────────────────────────────────────────────────────────┘
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
--  1. agents  (상담사 계정)
--
--  username : 로그인 아이디 (UNIQUE)
--  name     : 상담사 표시 이름
-- ============================================================
CREATE TABLE IF NOT EXISTS agents (
    agent_id        SERIAL          PRIMARY KEY,
    username        VARCHAR(50)     NOT NULL UNIQUE,     -- 로그인 아이디
    name            VARCHAR(50)     NOT NULL,            -- 상담사 이름
    password_hash   VARCHAR(255)    NOT NULL,            -- bcrypt
    created_at      TIMESTAMP       NOT NULL DEFAULT NOW()
);


-- ============================================================
--  2. calls  (통화 세션)
--
--  상태 전이: active → acw → ended
--  conversation_history: 실시간 STT 발화 누적
-- ============================================================
CREATE TABLE IF NOT EXISTS calls (
    call_id                 SERIAL          PRIMARY KEY,
    agent_id                INT             REFERENCES agents(agent_id),
    status                  VARCHAR(20)     NOT NULL DEFAULT 'active',
    -- 'active' | 'acw' | 'ended'
    conversation_history    JSONB           NOT NULL DEFAULT '[]',
    -- [{speaker, text, timestamp}, ...]
    started_at              TIMESTAMP       NOT NULL DEFAULT NOW(),
    ended_at                TIMESTAMP,
    duration_sec            INT,
    created_at              TIMESTAMP       NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_calls_agent_id   ON calls (agent_id);
CREATE INDEX IF NOT EXISTS idx_calls_status     ON calls (status);
CREATE INDEX IF NOT EXISTS idx_calls_started_at ON calls (started_at DESC);


-- ============================================================
--  3. acw_cards  (ACW 후처리 카드)
--
--  source='system' : 실제 통화 후 상담사 작성 → call_id/agent_id 필수
--  source='ai_hub' : DATA-017 시드 데이터   → call_id/agent_id NULL
-- ============================================================
CREATE TABLE IF NOT EXISTS acw_cards (
    acw_id                  SERIAL          PRIMARY KEY,
    call_id                 INT             UNIQUE REFERENCES calls(call_id),
    agent_id                INT             REFERENCES agents(agent_id),
    source                  VARCHAR(20)     NOT NULL DEFAULT 'system',
    -- 'system' | 'ai_hub'

    -- 상담 기본 정보
    title                   VARCHAR(200),
    customer_type           VARCHAR(20),    -- 'citizen' | 'medical' | 'other'
    customer_type_custom    VARCHAR(100),

    -- 분류 (category_master 논리적 참조)
    -- category: '감염병' | '접수처리' | '범위외'
    category                VARCHAR(50),
    category_major          VARCHAR(100),
    category_mid            VARCHAR(100),
    category_mid_list       JSONB,          -- 복수 중분류 배열
    category_mid_custom     VARCHAR(100),

    disease_name            VARCHAR(100),

    -- 상담 내용
    qa_summary              JSONB,          -- [{q, a}, ...]
    transcript              TEXT,           -- 전체 대화 원문 (ACW-001 변환본)
    ai_response_summary     TEXT,           -- 고객문의→AI안내→처리결과 서술형

    -- 이관
    is_transferred          BOOLEAN         DEFAULT FALSE,
    transfer_target         VARCHAR(200),

    -- 메타
    keywords                JSONB,          -- 키워드 배열
    satisfaction            SMALLINT,       -- AI 답변 만족도 1~5 (선택 입력)
    agent_memo              TEXT,
    is_resolved             BOOLEAN,
    agent_used_ai           VARCHAR(20),    -- 'yes' | 'partial' | 'no'

    -- 벡터 검색
    q_embedding             VECTOR(1536),   -- qa_summary 첫 번째 Q 임베딩

    -- ACW 시각
    acw_started_at          TIMESTAMP,
    acw_ended_at            TIMESTAMP,
    acw_duration_sec        INT,

    created_at              TIMESTAMP       NOT NULL DEFAULT NOW(),

    -- AI 안내 카드 (STEP 1~3 결과 영속화)
    ai_guidance             JSONB
    -- {query, disease_name, answer, is_oos, oos_type, oos_reason, sources[]}
    -- oos_type: 'unrelated' | 'action_required' | null
);

CREATE INDEX IF NOT EXISTS idx_acw_q_embedding  ON acw_cards
    USING ivfflat (q_embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_acw_source       ON acw_cards (source);
CREATE INDEX IF NOT EXISTS idx_acw_disease_name ON acw_cards (disease_name);
CREATE INDEX IF NOT EXISTS idx_acw_created_at   ON acw_cards (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_acw_agent_id     ON acw_cards (agent_id);
CREATE INDEX IF NOT EXISTS idx_acw_category     ON acw_cards (category);


-- ============================================================
--  4. knowledge_chunks  (통합 RAG 지식 청크)
--
--  knowledge_type: disease_guideline | disease_info | faq | system_manual
--  source_category: disease | system
--
--  v3.0 변경: 미사용 컬럼 제거
--    삭제: source_id, content, embed_text, keywords, source, section_category
--    추가: clean_content (정제된 텍스트, retrieval.py 메인 RAG 사용)
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id              SERIAL          PRIMARY KEY,
    data_id         VARCHAR(20)     NOT NULL,   -- 'DATA-001' ~ 'DATA-014'
    source_category VARCHAR(10)     NOT NULL,   -- 'disease' | 'system'
    knowledge_type  VARCHAR(30)     NOT NULL,
    -- 'disease_guideline' | 'disease_info' | 'faq' | 'system_manual'

    disease_name    VARCHAR(100),
    document_title  VARCHAR(300),
    chapter         VARCHAR(200),
    section_title   VARCHAR(300),

    chunk_text      TEXT,           -- step2_search.py 폴백 검색용
    clean_content   TEXT,           -- retrieval.py Hybrid RAG 메인 사용
    chunk_index     INT     DEFAULT 0,

    embedding       VECTOR(1536)
);

CREATE INDEX IF NOT EXISTS idx_kc_embedding ON knowledge_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_kc_source_category ON knowledge_chunks (source_category);
CREATE INDEX IF NOT EXISTS idx_kc_knowledge_type  ON knowledge_chunks (knowledge_type);
CREATE INDEX IF NOT EXISTS idx_kc_disease_name    ON knowledge_chunks (disease_name);
CREATE INDEX IF NOT EXISTS idx_kc_data_id         ON knowledge_chunks (data_id);


-- ============================================================
--  5. transfer_agencies  (이관기관 정보)
-- ============================================================
CREATE TABLE IF NOT EXISTS transfer_agencies (
    agency_id               SERIAL          PRIMARY KEY,
    category                VARCHAR(30),
    -- '관련 기관' | '소속기관' | '질병관리청 직원' | '응급'
    org_name                VARCHAR(200)    NOT NULL,
    dept_name               VARCHAR(200),
    phone                   VARCHAR(100),
    description             TEXT,           -- 담당업무 (임베딩 원문)
    description_embedding   VECTOR(1536),
    description_summary     TEXT            -- 프론트 표시용 요약
);

CREATE INDEX IF NOT EXISTS idx_ta_embedding ON transfer_agencies
    USING ivfflat (description_embedding vector_cosine_ops) WITH (lists = 50);
CREATE INDEX IF NOT EXISTS idx_ta_category ON transfer_agencies (category);


-- ============================================================
--  6. category_master  (ACW 분류 드롭다운 시드)
--
--  category: '감염병' | '접수처리' | '범위외'
--    감염병  : is_oos=false 상담
--    접수처리: is_oos=true, oos_type='action_required' (시스템 신고·이관 등)
--    범위외  : is_oos=true, oos_type='unrelated'
-- ============================================================
CREATE TABLE IF NOT EXISTS category_master (
    id          SERIAL          PRIMARY KEY,
    category    VARCHAR(50)     NOT NULL,   -- '감염병' | '접수처리' | '범위외'
    major       VARCHAR(100)    NOT NULL,   -- 대분류
    mid         VARCHAR(100)    NOT NULL,   -- 중분류
    UNIQUE (category, major, mid)
);


-- ============================================================
--  category_master 시드 데이터
-- ============================================================
INSERT INTO category_master (category, major, mid) VALUES
-- 감염병
('감염병', '감염병 정보 문의',   '감염병기본정보'),
('감염병', '감염병 정보 문의',   '증상·건강상태'),
('감염병', '감염병 정보 문의',   '소독·위생'),
('감염병', '감염병 정보 문의',   '독감·계절질환'),
('감염병', '감염병 정보 문의',   '백신'),
('감염병', '감염병 정보 문의',   '치료제·의약품'),
('감염병', '감염병 정보 문의',   '예방수칙·거리두기'),
('감염병', '감염병 정보 문의',   '항균·방역용품'),
('감염병', '감염병 지침 문의',   '감염병신고안내'),
('감염병', '해외/검역 정보 문의','여행·입국'),
('감염병', '감염병 통계·현황',   '국내외발생현황'),
-- 접수처리
('접수처리', '행정처리', '권한관리'),
('접수처리', '행정처리', '시스템오류 처리'),
('접수처리', '행정처리', '환자정보확인'),
('접수처리', '행정처리', '감염병신고 접수'),
('접수처리', '행정처리', '기타행정처리'),
-- 범위외
('범위외', '범위외', '범위외')
ON CONFLICT (category, major, mid) DO NOTHING;

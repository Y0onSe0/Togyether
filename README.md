# Togyether — 질병관리청 1339 콜센터 AI 지원 시스템

## 프로젝트 구조

```
Project/
├── backend/          # FastAPI 백엔드
├── frontend/         # React + Vite 프론트엔드
├── db/
│   ├── db_setup_v2.sql          # DB 스키마
│   └── scripts/
│       ├── parsed/              # 전처리 완료 데이터 (14개 데이터셋)
│       ├── load_all.py          # DB 전체 적재 (메인)
│       ├── post_process_embed.py # embed_text/chunk_text 후처리
│       └── embed_and_merge.py   # 임베딩 생성 및 병합
└── docker/
    └── docker-compose.yml       # PostgreSQL + pgvector
```

---

## 로컬 환경 셋업

### 1. DB 실행 (Docker 필요)

```bash
cd docker
docker-compose up -d
```

PostgreSQL이 `localhost:5555`에 뜹니다.

### 2. 환경변수 설정

```bash
# 백엔드
cp backend/.env.example backend/.env
# → OPENAI_API_KEY, JWT_SECRET_KEY 등 실제 값 입력

# DB 스크립트
cp db/scripts/.env.example db/scripts/.env
# → OPENAI_API_KEY 실제 값 입력
```

### 3. 백엔드 패키지 설치

```bash
cd backend
pip install -r requirements.txt
```

### 4. DB 데이터 적재

```bash
cd db/scripts

# 전체 적재 (임베딩 생성 포함 — OpenAI API 키 필요, 약 3~5분 소요)
python load_all.py --fresh

# 임베딩 없이 적재 (OpenAI 키 없어도 됨 — 벡터 검색 불가)
python load_all.py --fresh --no-embed
```

적재 내용:
- `knowledge_chunks`: 감염병 지침 3,389건 (RAG 검색 대상)
- `transfer_agencies`: 이관기관 123건
- `agents`: 상담사 계정 10명 (테스트 계정 포함)
- `acw_cards`: ACW 후처리 카드 3,783건

### 5. 백엔드 실행

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

API 문서: http://localhost:8000/docs

### 6. 프론트엔드 실행

```bash
cd frontend
npm install
npm run dev
```

---

## 테스트 계정

`load_all.py` 실행 후 생성되는 기본 계정:

| 아이디 | 비밀번호 |
|--------|---------|
| agent01 ~ agent10 | kdca1234! |

---

## 기술 스택

- **백엔드**: FastAPI, PostgreSQL + pgvector, OpenAI API
- **프론트엔드**: React, Vite
- **RAG**: Dense (text-embedding-3-small) + BM25 + Cross-encoder rerank
- **인프라**: Docker, pgvector/pgvector:pg17

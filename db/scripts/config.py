"""
config.py
모든 파일 경로 · DB 설정 중앙 관리
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# .env 로드 (scripts/.env 우선, 없으면 프로젝트 루트)
_scripts_env = Path(__file__).parent / ".env"
_root_env    = Path(__file__).parent.parent.parent / ".env"

if _scripts_env.exists():
    load_dotenv(_scripts_env)
else:
    load_dotenv(_root_env)

# ── DB 설정 ────────────────────────────────────────────
DB_HOST     = os.getenv("DB_HOST",     "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "5432"))   # Docker 포트 매핑 (선행 연구와 동일)
DB_USER     = os.getenv("DB_USER",     "kdca_admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "kdca_pwd1")
DB_NAME     = os.getenv("DB_NAME",     "kdca_db")

# ── 임베딩 설정 ────────────────────────────────────────
OPENAI_API_KEY       = os.getenv("OPENAI_API_KEY", "")
EMBED_MODEL          = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
EMBED_DIM            = int(os.getenv("OPENAI_EMBEDDING_DIMENSION", "1536"))
EMBED_BATCH          = 100          # OpenAI API 배치 크기
EMBED_REQUEST_DELAY  = 0.5          # API 호출 간격 (초), RateLimit 방지

# ── 배치 적재 설정 ─────────────────────────────────────
BATCH_SIZE      = 100           # execute_batch 단위
COMMIT_INTERVAL = 500           # 커밋 주기

# ── 경로 설정 ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.parent   # Togyether/Project
DATA_DIR     = PROJECT_ROOT                          # json 파일들 위치
CONSULT_DIR  = DATA_DIR / "상담"
DB_DIR       = DATA_DIR / "db"

# 원본 데이터 파일
DISEASE_INFO_FILE      = DATA_DIR / "diseases1.json"
FAQ_FILE               = DATA_DIR / "kdca_faq_by_category.json"
DPORTAL_FAQ_FILE       = DATA_DIR / "kdca_dportal_faq.json"
VACC_INFO_FILE         = DATA_DIR / "vacc_info.json"
CONSULTATION_FILE      = CONSULT_DIR / "merged_all_QA.json"

# 임베딩 생성 후 저장할 파일 (중간 산출물)
EMBED_DISEASE_FILE     = DATA_DIR / "diseases_with_embeddings.json"
EMBED_FAQ_FILE         = DATA_DIR / "faq_with_embeddings.json"
EMBED_VACC_FILE        = DATA_DIR / "vacc_with_embeddings.json"
EMBED_CONSULT_FILE     = CONSULT_DIR / "consultations_with_embeddings.json"

# DB SQL 파일
DB_SETUP_SQL           = DB_DIR / "db_setup.sql"

# 감염병 지침 PDF 디렉토리
GUIDELINE_PDF_DIR      = DATA_DIR / "data" / "감병병지침_전처리초안_완"

# 청킹 설정
CHUNK_SIZE             = 800    # 청크 크기 (문자 수)
CHUNK_OVERLAP          = 100    # 청크 중첩 (문자 수)

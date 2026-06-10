"""
config.py
DB 연결 · 임베딩 설정 중앙 관리
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

# ── DB 설정 (Supabase) ─────────────────────────────────
DB_HOST     = os.getenv("DB_HOST",     "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "5432"))
DB_USER     = os.getenv("DB_USER",     "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME     = os.getenv("DB_NAME",     "postgres")

# ── 임베딩 설정 ────────────────────────────────────────
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY", "")
EMBED_MODEL         = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
EMBED_DIM           = int(os.getenv("OPENAI_EMBEDDING_DIMENSION", "1536"))
EMBED_BATCH         = 100   # OpenAI API 배치 크기
EMBED_REQUEST_DELAY = 0.5   # API 호출 간격 (초), RateLimit 방지

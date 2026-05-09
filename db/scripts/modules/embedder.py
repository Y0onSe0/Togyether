"""
modules/embedder.py
OpenAI text-embedding-3-small 임베딩 생성

선행 연구와 동일한 방식:
  모델  : text-embedding-3-small
  차원  : 1536
  방식  : OpenAI API 배치 호출

토큰 한계:
  text-embedding-3-small 최대 입력 = 8192 토큰
  한국어 1글자 ≈ 1.5~3 토큰 → 안전 상한 8000 토큰으로 자름
"""

import sys
import time
from tqdm import tqdm
from openai import OpenAI

sys.path.append(str(__import__('pathlib').Path(__file__).parent.parent))
from config import OPENAI_API_KEY, EMBED_MODEL, EMBED_DIM, EMBED_BATCH, EMBED_REQUEST_DELAY

_client     = None
_enc        = None          # tiktoken 인코더 (지연 로드)
MAX_TOKENS  = 8000          # text-embedding-3-small 한계(8192)에 여유 둠


# ── tiktoken 기반 안전 토큰 잘라내기 ─────────────────────────────────────────
def _get_encoder():
    """cl100k_base 인코더 반환 (없으면 None)."""
    global _enc
    if _enc is None:
        try:
            import tiktoken
            _enc = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            _enc = False   # tiktoken 없음을 표시
    return _enc if _enc else None


def truncate_text(text: str, max_tokens: int = MAX_TOKENS) -> str:
    """
    텍스트를 max_tokens 이하로 잘라 반환.

    tiktoken 있으면 정확히 토큰 단위로 자름.
    없으면 문자 수 기반 보수적 잘라내기(4000자).
    """
    enc = _get_encoder()
    if enc:
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        truncated = enc.decode(tokens[:max_tokens])
        return truncated
    else:
        # 한국어 평균 ≈ 2 토큰/글자 → 4000자 = ~8000 토큰
        CHAR_LIMIT = 4000
        return text[:CHAR_LIMIT] if len(text) > CHAR_LIMIT else text


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            raise ValueError("[Embedder] OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        _client = OpenAI(api_key=OPENAI_API_KEY)
        print(f"[Embedder] 모델: {EMBED_MODEL} ({EMBED_DIM}차원)")
    return _client


def embed_texts(texts: list[str], prefix: str = None) -> list[list[float]]:
    """
    텍스트 리스트 → 임베딩 벡터 리스트

    Args:
        texts  : 임베딩할 텍스트 목록
        prefix : 사용 안 함 (OpenAI는 prefix 불필요, e5 모델과의 호환성 유지용)

    Returns:
        [[float, ...], ...] — 각 텍스트의 1536차원 벡터
    """
    client = _get_client()
    all_embeddings = []

    # 토큰 초과 방지: 전체 텍스트 미리 잘라내기
    truncated_texts = []
    truncated_count = 0
    for t in texts:
        safe = truncate_text(t if t.strip() else ".")
        if safe != t:
            truncated_count += 1
        truncated_texts.append(safe)

    if truncated_count:
        print(f"[Embedder] 토큰 초과 청크 {truncated_count}개 → {MAX_TOKENS}토큰으로 잘림")

    for i in tqdm(range(0, len(truncated_texts), EMBED_BATCH),
                  desc="임베딩 생성", unit="batch"):
        batch = truncated_texts[i : i + EMBED_BATCH]

        try:
            response = client.embeddings.create(
                model=EMBED_MODEL,
                input=batch,
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

        except Exception as e:
            print(f"\n[Embedder] API 오류 (batch {i}~{i+len(batch)}): {e}")
            print("  재시도 중...")
            time.sleep(5)
            response = client.embeddings.create(
                model=EMBED_MODEL,
                input=batch,
            )
            all_embeddings.extend([item.embedding for item in response.data])

        # RateLimit 방지
        if i + EMBED_BATCH < len(truncated_texts):
            time.sleep(EMBED_REQUEST_DELAY)

    return all_embeddings


def embedding_to_pgvector(vec: list[float]) -> str:
    """
    파이썬 리스트 → pgvector 문자열
    예: [0.1, 0.2, ...] → "[0.1,0.2,...]"
    """
    return "[" + ",".join(map(str, vec)) + "]"

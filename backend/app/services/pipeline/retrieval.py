"""
RAG 검색 파이프라인 (v8 — Hybrid RAG: Dense + BM25 + RRF + Cross-Encoder Reranking)
knowledge_chunks DB에서 청크를 로드해 in-memory Hybrid RAG 수행

RTL-SRCH-001: 쿼리 임베딩 (text-embedding-3-small, 1536d)
RTL-SRCH-002: 2-A — knowledge_chunks 하이브리드 검색 (is_oos=false 시에만)
  - Dense: NumPy 코사인 유사도 (embedding 벡터 in-memory 캐시)
  - BM25:  키워드 기반 in-memory 검색 (rank-bm25)
  - RRF:   Reciprocal Rank Fusion으로 결합 (k=60)
  - Rerank: bongsoo/klue-cross-encoder-v1 (sentence-transformers 설치 시 활성화)

청크 데이터: 서버 시작 후 첫 요청 시 knowledge_chunks 테이블에서 전체 로드 (lazy)
2-B/2-C: ws.py에서 step2_search.py를 통해 DB 직접 조회

반환:
  {
    "step2a": [{chunk_id, chunk_text, knowledge_type, disease_name,
                document_title, section_title, data_id, similarity}],
    "step2b": [],
    "step2c": [],
    "_disease_filter": str | None,
  }
"""

import asyncio
import json
import re
import numpy as np
from openai import AsyncOpenAI
from rank_bm25 import BM25Okapi
from app.core.config import settings
from app.core.database import get_pool

try:
    from sentence_transformers import CrossEncoder as _CrossEncoder
    _CE_AVAILABLE = True
except ImportError:
    _CE_AVAILABLE = False

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
EMBEDDING_MODEL      = "text-embedding-3-small"
SIMILARITY_THRESHOLD = 0.40
TOP_K     = 5
RRF_K     = 60
BM25_TOP  = 20
DENSE_TOP = 20
W_DENSE   = 1.0
W_BM25    = 1.0
RERANK_MODEL = "bongsoo/klue-cross-encoder-v1"
RERANK_POOL  = 20
USE_RERANK   = True

# ─────────────────────────────────────────
# 전역 캐시 (lazy load — 첫 요청 시 DB에서 로드)
# ─────────────────────────────────────────
_client: AsyncOpenAI | None = None

_all_vecs: np.ndarray | None = None   # shape: (N, 1536)
_all_meta: list | None = None          # list of chunk dicts

_reranker = None

_bm25_index: BM25Okapi | None = None
_bm25_meta: list | None = None

_load_lock: asyncio.Lock | None = None


# ─────────────────────────────────────────
# 병명 별칭 테이블 (LLM 출력 → KB disease_name)
# ─────────────────────────────────────────
DISEASE_NAME_ALIASES: dict[str, str] = {
    # HIV/AIDS
    "HIV/AIDS":                     "후천성면역결핍증(AIDS)",
    "HIV":                          "후천성면역결핍증(AIDS)",
    "에이즈":                       "후천성면역결핍증(AIDS)",
    "에이치아이브이":               "후천성면역결핍증(AIDS)",
    # 코로나
    "코로나":                       "코로나바이러스감염증-19",
    "코로나19":                     "코로나바이러스감염증-19",
    "코비드":                       "코로나바이러스감염증-19",
    "COVID-19":                     "코로나바이러스감염증-19",
    "COVID19":                      "코로나바이러스감염증-19",
    # MERS
    "메르스":                       "중동호흡기증후군(MERS)",
    "MERS":                         "중동호흡기증후군(MERS)",
    "중동호흡기증후군":             "중동호흡기증후군(MERS)",
    # 인플루엔자
    "독감":                         "인플루엔자",
    # 간염
    "에이형 간염":                  "A형간염",
    "에이 형 간염":                 "A형간염",
    "에이간염":                     "A형간염",
    "A형 간염":                     "A형간염",
    "비형 간염":                    "B형간염",
    "비 형 간염":                   "B형간염",
    "비간염":                       "B형간염",
    "B형 간염":                     "B형간염",
    "씨형 간염":                    "C형간염",
    "씨 형 간염":                   "C형간염",
    "씨간염":                       "C형간염",
    "C형 간염":                     "C형간염",
    "이형 간염":                    "E형간염",
    "이 형 간염":                   "E형간염",
    "E형 간염":                     "E형간염",
    # CRE
    "CRE":                          "카바페넴내성장내세균목(CRE) 감염증",
    "씨알이":                       "카바페넴내성장내세균목(CRE) 감염증",
    "씨알":                         "카바페넴내성장내세균목(CRE) 감염증",
    "카바페넴":                     "카바페넴내성장내세균목(CRE) 감염증",
    "CPE":                          "카바페넴내성장내세균목(CRE) 감염증",
    # VRE
    "VRE":                          "반코마이신내성장알균(VRE) 감염증",
    "브이알이":                     "반코마이신내성장알균(VRE) 감염증",
    # VRSA
    "VRSA":                         "반코마이신내성황색포도알균(VRSA) 감염증",
    "브이에스알에이":               "반코마이신내성황색포도알균(VRSA) 감염증",
    # MRAB
    "MRAB":                         "다제내성아시네토박터바우마니균(MRAB) 감염증",
    "다제내성아시네토박터바우마니균": "다제내성아시네토박터바우마니균(MRAB) 감염증",
    "엠알에이비":                   "다제내성아시네토박터바우마니균(MRAB) 감염증",
    # 기타
    "볼거리":                       "유행성이하선염",
    "유행성 이하선염":              "유행성이하선염",
    "수족구":                       "수족구병",
    "노로":                         "노로바이러스 감염증",
    "노로바이러스":                 "노로바이러스 감염증",
    "살모넬라":                     "살모넬라균 감염증",
    "캄필로박터 장염":              "캄필로박터균 감염증",
    "캄필로박터":                   "캄필로박터균 감염증",
    "캄플로박터균":                 "캄필로박터균 감염증",
    "캄필러박터":                   "캄필로박터균 감염증",
    "루벨라":                       "풍진",
    "신종 감염병 증후군":           "신종감염병증후군",
    "신종 감염병":                  "신종감염병증후군",
    "신종감염병 증후군":            "신종감염병증후군",
    "급성 호흡기 감염증":           "급성호흡기감염증",
}


def _normalize_disease_name(disease_name: str | None) -> str | None:
    if not disease_name:
        return disease_name
    return DISEASE_NAME_ALIASES.get(disease_name, disease_name)


# ─────────────────────────────────────────
# 병명 그룹 테이블 (정규화된 병명 → 검색 대상 disease_name 리스트)
#
# DB에는 개별 병명 청크 외에 여러 병명을 묶은 "공통 총론" 청크가 있음.
# 예) "페스트" 질문 → "페스트" 청크 + "두창·페스트·탄저·..." 총론 청크 모두 포함
# 예) "매독" 질문   → 모든 병기(1기/2기/3기/선천성/잠복) 청크 포함
# ─────────────────────────────────────────
DISEASE_GROUP_MAP: dict[str, list[str]] = {
    # 1급 감염병 공통 총론 그룹
    "두창":           ["두창", "두창·페스트·탄저·보툴리눔독소증·야토병"],
    "페스트":         ["페스트", "두창·페스트·탄저·보툴리눔독소증·야토병"],
    "탄저":           ["탄저", "두창·페스트·탄저·보툴리눔독소증·야토병"],
    "보툴리눔독소증": ["보툴리눔독소증", "두창·페스트·탄저·보툴리눔독소증·야토병"],
    "야토병":         ["야토병", "두창·페스트·탄저·보툴리눔독소증·야토병"],
    # 바이러스성출혈열 그룹
    "에볼라바이러스병":   ["에볼라바이러스병", "바이러스성출혈열"],
    "마버그열":           ["마버그열", "바이러스성출혈열"],
    "라싸열":             ["라싸열", "바이러스성출혈열"],
    "크리미안콩고출혈열": ["크리미안콩고출혈열", "바이러스성출혈열"],
    "리프트밸리열":       ["리프트밸리열", "바이러스성출혈열"],
    "남아메리카출혈열":   ["남아메리카출혈열", "바이러스성출혈열"],
    "니파바이러스감염증": ["니파바이러스감염증", "바이러스성출혈열"],
    # 매독 그룹 (병기별 → 공통 매독 포함)
    "매독(1기)":    ["매독(1기)", "매독"],
    "매독(2기)":    ["매독(2기)", "매독"],
    "매독(3기)":    ["매독(3기)", "매독"],
    "매독(선천성)": ["매독(선천성)", "매독"],
    "매독(잠복)":   ["매독(잠복)", "매독"],
    "매독":         ["매독", "매독(1기)", "매독(2기)", "매독(3기)", "매독(선천성)", "매독(잠복)"],
    # 풍진 그룹
    "풍진(선천성)": ["풍진(선천성)", "풍진"],
    "풍진(후천성)": ["풍진(후천성)", "풍진"],
    "풍진":         ["풍진", "풍진(선천성)", "풍진(후천성)"],
    # 마이코플라스마 그룹
    "마이코플라스마균 감염증":      ["마이코플라스마균 감염증", "마이코플라스마 폐렴균 감염증"],
    "마이코플라스마 폐렴균 감염증": ["마이코플라스마 폐렴균 감염증", "마이코플라스마균 감염증"],
}

# 병명 필터 적용 최소 청크 수
# 필터 결과가 이보다 적으면 LLM 오추출로 판단하고 전체 검색으로 폴백
DISEASE_FILTER_MIN = 3


def _get_disease_filter_names(normalized: str) -> list[str]:
    """정규화된 병명 → 필터 대상 disease_name 리스트 반환 (그룹 확장)"""
    return DISEASE_GROUP_MAP.get(normalized, [normalized])


def _apply_disease_filter(
    vecs: np.ndarray,
    meta: list,
    disease_name: str,
) -> tuple[np.ndarray, list, bool]:
    """
    disease_name 일치 청크만 추출 (그룹 확장 포함).
    반환: (filtered_vecs, filtered_meta, applied)
      applied=False → 매칭 부족으로 폴백 (전체 meta/vecs 그대로 반환)
    """
    normalized = _normalize_disease_name(disease_name)
    if not normalized:
        return vecs, meta, False

    target_names = set(_get_disease_filter_names(normalized))
    idx_list = [
        i for i, c in enumerate(meta)
        if c.get("disease_name", "") in target_names
    ]

    if len(idx_list) < DISEASE_FILTER_MIN:
        print(f"[retrieval] disease_filter 폴백: '{normalized}' (그룹={target_names}) "
              f"매칭 {len(idx_list)}건 < 최소 {DISEASE_FILTER_MIN}건 → 전체 검색")
        return vecs, meta, False

    print(f"[retrieval] disease_filter 적용: '{normalized}' → {target_names}  "
          f"{len(idx_list)}건 / 전체 {len(meta)}건")
    f_meta = [meta[i] for i in idx_list]
    f_vecs = vecs[idx_list]
    return f_vecs, f_meta, True


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


# ─────────────────────────────────────────
# DB에서 전체 청크 로드 (최초 1회)
# ─────────────────────────────────────────
async def _ensure_chunks_loaded() -> tuple[np.ndarray, list]:
    """knowledge_chunks 테이블에서 전체 데이터 로드 (lazy, thread-safe)"""
    global _all_vecs, _all_meta, _bm25_index, _bm25_meta, _load_lock

    if _all_vecs is not None:
        return _all_vecs, _all_meta

    # asyncio.Lock은 첫 호출 시 생성 (이벤트 루프 보장)
    if _load_lock is None:
        _load_lock = asyncio.Lock()

    async with _load_lock:
        if _all_vecs is not None:   # double-check
            return _all_vecs, _all_meta

        print("[retrieval] knowledge_chunks DB 로드 중...")
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT chunk_index::text AS chunk_id,
                   data_id, document_title, chapter, section_title,
                   disease_name, knowledge_type,
                   clean_content AS chunk_text,
                   embedding::text AS embedding
            FROM knowledge_chunks
            ORDER BY chunk_index
            """
        )

        meta = []
        vecs = []
        for row in rows:
            emb_raw = row["embedding"]
            # pgvector → Python list[float] 파싱
            emb = json.loads(emb_raw) if isinstance(emb_raw, str) else list(emb_raw)
            chunk = {
                "chunk_id":       row["chunk_id"],
                "data_id":        row["data_id"] or "",
                "document_title": row["document_title"] or "",
                "chapter":        row["chapter"] or "",
                "section_title":  row["section_title"] or "",
                "disease_name":   row["disease_name"] or "",
                "knowledge_type": row["knowledge_type"] or "",
                "chunk_text":     row["chunk_text"] or "",
            }
            meta.append(chunk)
            vecs.append(emb)

        _all_meta = meta
        _all_vecs = np.array(vecs, dtype=np.float32)

        # BM25 인덱스 동시 빌드 (clean_content 기준)
        corpus = [_tokenize_ko(_clean_content(c["chunk_text"])) for c in meta]
        _bm25_index = BM25Okapi(corpus)
        _bm25_meta = meta

        print(f"[retrieval] 로드 완료: {len(meta):,}건, shape={_all_vecs.shape}")
        return _all_vecs, _all_meta


# ─────────────────────────────────────────
# Reranker
# ─────────────────────────────────────────
def _load_reranker():
    global _reranker
    if _reranker is None:
        if not _CE_AVAILABLE:
            raise ImportError("sentence-transformers 필요: pip install sentence-transformers")
        _reranker = _CrossEncoder(RERANK_MODEL, max_length=512)
    return _reranker


def _rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    if not candidates:
        return candidates
    model = _load_reranker()
    pairs = [(query, _clean_content(c["chunk_text"])) for c in candidates]
    scores = model.predict(pairs)
    ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
    results = []
    for score, c in ranked[:top_k]:
        c = dict(c)
        c["rerank_score"] = round(float(score), 4)
        results.append(c)
    return results


# ─────────────────────────────────────────
# 텍스트 정제
# ─────────────────────────────────────────
def _clean_content(text: str) -> str:
    """
    BM25/리랭킹용 텍스트 정제:
    - 마크다운 테이블 → 셀 텍스트 추출
    - 마크다운 강조·헤더 기호 제거
    - 불릿 특수문자 정리
    - 연속 공백·개행 정규화
    """
    if not text:
        return ""

    # 마크다운 테이블 → 텍스트
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            # 구분선(|---|---| 등) 제거
            if re.match(r"^\|[\s\-:|]+\|$", stripped):
                continue
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            lines.append(" ".join(c for c in cells if c))
        else:
            lines.append(line)
    text = "\n".join(lines)

    # 마크다운 강조 제거 (**bold**, *italic*, `code`)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = re.sub(r"`(.+?)`",        r"\1", text)

    # 마크다운 헤더 기호 제거
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # 불릿·특수문자 정리
    text = re.sub(r"[▢◾•·※★☆□■▪▫]", " ", text)

    # 연속 공백·개행 정리
    text = re.sub(r"[ \t]+",  " ",  text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ─────────────────────────────────────────
# 토크나이저
# ─────────────────────────────────────────
def _tokenize_ko(text: str) -> list[str]:
    tokens = re.split(r"[\s\(\)\[\]▢◾·•\-,./]+", text)
    return [t for t in tokens if len(t) >= 2]


# ─────────────────────────────────────────
# 임베딩
# ─────────────────────────────────────────
async def embed_query(text: str) -> np.ndarray:
    resp = await _get_client().embeddings.create(
        model=EMBEDDING_MODEL, input=[text[:8000]]
    )
    return np.array(resp.data[0].embedding, dtype=np.float32)


# ─────────────────────────────────────────
# 쿼리 확장 (Query Expansion)
# ─────────────────────────────────────────
_EXPAND_SYSTEM = """당신은 감염병 지침 문서 검색 전문가입니다.
주어진 검색 쿼리를 다른 표현으로 재작성하세요.

규칙:
- 동일한 의미지만 다른 키워드로 표현 (유사어·관련 개념 활용)
- [병명] + [핵심개념] 명사구 형태 유지
- 반드시 JSON으로만 반환: {"expanded": "재작성된 쿼리"}

예시:
  입력: "결핵 격리기간 기준"
  출력: {"expanded": "결핵환자 전염성 격리해제 조건"}

  입력: "수족구병 신고의무 신고기준"
  출력: {"expanded": "수족구병 법정감염병 신고대상 의사환자"}

  입력: "후천성면역결핍증 신고의무 신고기준"
  출력: {"expanded": "에이즈 HIV감염인 감염병 신고 보고"}"""


async def expand_query(query: str) -> str:
    """원본 쿼리 → 확장 쿼리 1개 생성 (LLM)"""
    try:
        resp = await _get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _EXPAND_SYSTEM},
                {"role": "user",   "content": query},
            ],
            temperature=0,
            max_tokens=60,
            response_format={"type": "json_object"},
        )
        import json as _json
        return _json.loads(resp.choices[0].message.content).get("expanded", query)
    except Exception:
        return query  # 실패 시 원본 반환


def _merge_step2a(list1: list[dict], list2: list[dict]) -> list[dict]:
    """두 검색 결과를 chunk_id 기준으로 병합 (similarity 높은 것 우선, 중복 제거)"""
    merged: dict[str, dict] = {}
    for chunk in list1 + list2:
        cid = chunk.get("chunk_id", "")
        if cid not in merged or chunk["similarity"] > merged[cid]["similarity"]:
            merged[cid] = chunk
    return sorted(merged.values(), key=lambda x: x["similarity"], reverse=True)


# ─────────────────────────────────────────
# Dense: 코사인 유사도 검색
# ─────────────────────────────────────────
def _cosine_search(
    query_vec: np.ndarray,
    vecs: np.ndarray,
    k: int,
) -> list[tuple[int, float]]:
    norms = np.linalg.norm(vecs, axis=1)
    q_norm = np.linalg.norm(query_vec)
    scores = vecs @ query_vec / (norms * q_norm + 1e-9)
    top_idx = np.argsort(scores)[::-1][:k]
    return [(int(i), float(scores[i])) for i in top_idx]


def _meta_to_result(c: dict, score: float) -> dict:
    return {
        "chunk_id":       c.get("chunk_id", ""),
        "chunk_text":     c.get("chunk_text", ""),
        "knowledge_type": c.get("knowledge_type", ""),
        "disease_name":   c.get("disease_name", ""),
        "document_title": c.get("document_title", ""),
        "section_title":  c.get("section_title", ""),
        "data_id":        c.get("data_id", ""),
        "similarity":     round(score, 4),
    }


# ─────────────────────────────────────────
# BM25: 키워드 검색
# ─────────────────────────────────────────
def _bm25_search(
    query: str,
    k: int,
    meta_subset: list | None = None,
) -> list[tuple[int, float]]:
    tokens = _tokenize_ko(query)
    if meta_subset is not None:
        # disease filter 적용 시 서브셋으로 BM25 즉석 재빌드 (인덱스 정합성 보장)
        corpus = [_tokenize_ko(_clean_content(c["chunk_text"])) for c in meta_subset]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(tokens)
    else:
        scores = _bm25_index.get_scores(tokens)
    top_idx = np.argsort(scores)[::-1][:k]
    return [(int(i), float(scores[i])) for i in top_idx if scores[i] > 0]


# ─────────────────────────────────────────
# RRF 병합
# ─────────────────────────────────────────
def _rrf_merge(
    dense_ranked: list[tuple[int, float]],
    bm25_ranked:  list[tuple[int, float]],
    meta: list,
    top_k: int,
    threshold: float,
) -> list[dict]:
    rrf_scores: dict[int, float] = {}
    dense_score_map: dict[int, float] = {}

    for rank, (idx, score) in enumerate(dense_ranked):
        rrf_scores[idx] = rrf_scores.get(idx, 0.0) + W_DENSE / (RRF_K + rank + 1)
        dense_score_map[idx] = score

    for rank, (idx, _) in enumerate(bm25_ranked):
        rrf_scores[idx] = rrf_scores.get(idx, 0.0) + W_BM25 / (RRF_K + rank + 1)

    sorted_idx = sorted(rrf_scores, key=lambda i: rrf_scores[i], reverse=True)

    results = []
    for idx in sorted_idx:
        dense_score = dense_score_map.get(idx, 0.0)
        # Dense score가 없거나 threshold 미만이면 제외
        if dense_score < threshold:
            continue
        results.append(_meta_to_result(meta[idx], dense_score))
        if len(results) >= top_k:
            break

    return results


# ─────────────────────────────────────────
# 2-A: knowledge_chunks 하이브리드 검색 (동기, executor에서 실행)
# ─────────────────────────────────────────
def _search_2a_sync(
    query: str,
    query_vec: np.ndarray,
    top_k: int,
    disease_name: str | None = None,
) -> list[dict]:
    vecs = _all_vecs
    meta = _all_meta

    # ── disease_name 프리필터 ────────────────────────────────────
    disease_applied = False
    if disease_name:
        vecs, meta, disease_applied = _apply_disease_filter(vecs, meta, disease_name)

    dense_ranked = _cosine_search(query_vec, vecs, DENSE_TOP)
    # 필터 적용 시 BM25도 같은 서브셋으로 재빌드 (인덱스 정합성)
    bm25_ranked  = _bm25_search(query, BM25_TOP, meta_subset=meta if disease_applied else None)

    rrf_top = RERANK_POOL if (USE_RERANK and _CE_AVAILABLE) else top_k
    rrf_results = _rrf_merge(dense_ranked, bm25_ranked, meta, rrf_top, SIMILARITY_THRESHOLD)


    if USE_RERANK and _CE_AVAILABLE and rrf_results:
        try:
            return _rerank(query, rrf_results, top_k)
        except Exception as e:
            print(f"[Rerank 오류] {e}")
            return rrf_results[:top_k]

    return rrf_results[:top_k]


# ─────────────────────────────────────────
# 공개 인터페이스
# ─────────────────────────────────────────
async def retrieve_all(
    query: str,
    is_oos: bool,
    disease_name: str | None = None,
    query_vec: np.ndarray | None = None,
    top_k: int = TOP_K,
    knowledge_type: str | None = None,
    use_query_expansion: bool = False,
) -> dict:
    """
    하이브리드 RAG 검색 (2-A).
    2-B/2-C는 ws.py에서 step2_search.py를 통해 DB 직접 조회.

    반환:
    {
        "step2a": [{chunk_id, chunk_text, knowledge_type, disease_name,
                    document_title, section_title, data_id, similarity}],
        "step2b": [],
        "step2c": [],
        "_disease_filter": str | None,
    }
    """
    if query_vec is None:
        query_vec = await embed_query(query)

    if is_oos:
        return {
            "step2a":          [],
            "step2b":          [],
            "step2c":          [],
            "_disease_filter": None,
        }

    # 청크 로드 보장 (최초 1회 DB 로드)
    await _ensure_chunks_loaded()

    loop = asyncio.get_event_loop()

    if use_query_expansion:
        # 원본 쿼리 + 확장 쿼리 병렬 실행
        expanded = await expand_query(query)
        expanded_vec = await embed_query(expanded)

        step2a_orig, step2a_exp = await asyncio.gather(
            loop.run_in_executor(None, _search_2a_sync, query,    query_vec,    top_k, disease_name),
            loop.run_in_executor(None, _search_2a_sync, expanded, expanded_vec, top_k, disease_name),
        )
        step2a = _merge_step2a(step2a_orig, step2a_exp)[:top_k]
    else:
        step2a = await loop.run_in_executor(
            None, _search_2a_sync, query, query_vec, top_k, disease_name
        )

    normalized = _normalize_disease_name(disease_name)

    return {
        "step2a":          step2a,
        "step2b":          [],
        "step2c":          [],
        "_disease_filter": normalized if normalized else None,
    }

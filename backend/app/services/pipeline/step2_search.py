"""
STEP 2: 병렬 pgvector 검색
2A: knowledge_chunks (disease_name 프리필터, is_oos=false 시만)
2B: acw_cards (q_embedding, 항상)
2C: transfer_agencies (description_embedding, 항상)
"""
import asyncio
import json
from openai import AsyncOpenAI
from app.core.config import settings
from app.core.database import get_pool

_client: AsyncOpenAI | None = None
SIMILARITY_THRESHOLD = 0.40       # knowledge_chunks, acw_cards 임계값
TRANSFER_THRESHOLD   = 0.60       # transfer_agencies 임계값 (엄격하게)
TOP_K = 5

# ── 이관기관 키워드 매핑 ───────────────────────────────────────────
# 키워드가 query에 포함되면 해당 기관을 우선 추천 (임베딩 검색보다 우선)
TRANSFER_KEYWORD_MAP = [
    # ── ★ 응급 최우선 (항상 맨 위) ───────────────────────────────────
    {
        "keywords": [
            "응급", "위급", "119", "생명이 위험",
            "숨이 안", "숨을 못", "숨쉬기 힘", "호흡곤란",
            "의식을 잃", "의식이 없", "의식없", "의식불명",
            "심정지", "심폐소생", "쓰러", "실신",
            "경련", "흉통", "가슴 통증", "가슴이 아파",
            "출혈이 심", "피가 안 멈", "피가 너무", "다량 출혈",
        ],
        "org_name": "소방청 (119)",
        "dept_name": None,
        "phone": "119",
        "description_summary": "생명이 위급한 응급 상황에서 신속한 응급처치 및 병원 이송. 즉시 119에 신고하세요.",
    },

    # ── 헬프데스크 ────────────────────────────────────────────────────
    {
        "keywords": ["헬프데스크", "헬프 데스크", "helpdesk"],
        "org_name": "질병보건통합관리시스템 헬프데스크",
        "dept_name": None,
        "phone": "1522-6339",
        "description_summary": "질병보건통합관리시스템 로그인 오류, 권한 신청, 감염병 신고 시스템 사용 문의 전용 헬프데스크",
    },

    # ── 감염병 전문 기관 (감염병 쿼리에도 이관카드 표시) ──────────────
    {
        "keywords": ["결핵 입원", "입원 치료", "국립마산", "국립목포"],
        "org_name": "국립마산병원",
        "dept_name": None,
        "phone": "055-249-5001",
        "description_summary": "결핵 입원 치료 전문 국립병원. 결핵 입원 문의, 결핵 검사 신청, 내성결핵 전문 치료",
    },
    {
        "keywords": ["결핵 헬프", "결핵관리", "결핵 문의", "결핵"],
        "org_name": "결핵관리 HelpDesk",
        "dept_name": None,
        "phone": "043-719-7312",
        "description_summary": "결핵 환자 치료·검진·관리, 결핵 예방 정책 및 국가 결핵관리 전문 문의 창구",
    },
    {
        "keywords": ["에이즈", "HIV", "AIDS", "후천성면역결핍"],
        "org_name": "감염병정책국 에이즈관리과",
        "dept_name": "에이즈관리과",
        "phone": "043-719-7330",
        "description_summary": "에이즈(HIV/AIDS) 및 성매개감염병 관리·예방·홍보 업무. 에이즈 신고, 감염인 관리, 정책 수립 관련 전문 문의",
    },
    {
        "keywords": ["B형간염", "C형간염", "비형간염", "씨형간염", "B형 간염", "C형 간염", "비형 간염", "씨형 간염"],
        "org_name": "감염병정책국 감염병관리과",
        "dept_name": "감염병관리과",
        "phone": "043-719-7140",
        "description_summary": "B형·C형 바이러스 간염, 수인성·식품매개감염병 관리 총괄 문의",
    },
    {
        "keywords": ["한센", "한센병"],
        "org_name": "한국한센복지협회",
        "dept_name": None,
        "phone": "02-753-2037",
        "description_summary": "한센병 조기 발견, 환자 진료, 이동 진료 및 상담, 정착 마을 복지 지원 사업",
    },
    # ── 보건환경연구원 ────────────────────────────────────────────────
    {
        "keywords": ["보건환경연구원", "보환연", "보건환경 연구원"],
        "org_name": "서울특별시보건환경연구원",
        "dept_name": None,
        "phone": "02-570-3000",
        "description_summary": "감염병 검사·진단, 식품·환경 위생 검사, 병원체 확인 등 보건환경 관련 문의. 타 지역은 관할 보건환경연구원으로 문의하세요.",
    },

    # ── 전문 부서 ──────────────────────────────────────────────────────
    {
        "keywords": ["미생물", "세균", "병원체", "세균분석", "미생물 검사", "미생물 관리"],
        "org_name": "진단분석국 세균분석과",
        "dept_name": "세균분석과",
        "phone": "043-719-8110",
        "description_summary": "결핵·성매개·호흡기세균 감염병 진단, 감시, 분석 및 교육. 미생물 검사 및 병원체 분석 문의",
    },
    {
        "keywords": ["항생제 내성", "항생제내성", "CRE", "VRSA", "MRAB", "내성균", "카바페넴"],
        "org_name": "의료안전예방국 항생제내성관리과",
        "dept_name": "항생제내성관리과",
        "phone": "043-719-7530",
        "description_summary": "국가 항생제 내성 관리 대책, 내성균 감시 조사사업, CRE·VRSA·MRAB 등 내성균 관리 문의",
    },
    {
        "keywords": ["결핵 입원", "입원 치료", "결핵 치료", "국립마산", "국립목포"],
        "org_name": "국립마산병원",
        "dept_name": None,
        "phone": "055-249-5001",
        "description_summary": "결핵 입원 치료 전문 국립병원. 결핵 입원 문의, 결핵 검사 신청, 내성결핵 전문 치료",
    },
    {
        "keywords": ["검역", "출입국 검역", "검역정책", "국립검역소"],
        "org_name": "감염병위기관리국 검역정책과",
        "dept_name": "검역정책과",
        "phone": "043-719-9200",
        "description_summary": "검역 정책 총괄, 출입국 검역감염병 대응, 국립검역소 운영 및 해외 유입 감염병 관리 문의",
    },
    {
        "keywords": ["건강보험", "보험료", "장기요양", "건강검진 대상"],
        "org_name": "건강보험공단",
        "dept_name": None,
        "phone": "1577-1000",
        "description_summary": "건강보험 자격·보험료 관리, 국가 건강검진 대상자 확인, 노인장기요양보험 신청 및 등급 판정",
    },
    {
        "keywords": ["진료비", "심사", "비급여", "의약품 정보"],
        "org_name": "건강보험심사평가원",
        "dept_name": None,
        "phone": "1644-2000",
        "description_summary": "진료비 적정성 심사 및 평가, 비급여 진료비 가격 공개, 의약품 안심 서비스",
    },
    {
        "keywords": ["병원감염", "의료감염", "의료관련감염"],
        "org_name": "의료안전예방국 의료감염관리과",
        "dept_name": "의료감염관리과",
        "phone": "043-719-7580",
        "description_summary": "의료관련감염병 예방·관리 총괄, 병원감염 관리 지침, 의료기관 감염관리 문의",
    },
    {
        "keywords": [
            "예방접종관리과", "예방접종 관리과", "예방접종 정책",
            "접종 이상반응 신고", "예방접종 이상반응", "국가예방접종",
            "독감 예방접종", "독감 접종", "독감 백신",
            "예방접종", "무료접종", "백신 접종", "접종 일정", "접종 대상",
        ],
        "org_name": "의료안전예방국 예방접종관리과",
        "dept_name": "예방접종관리과",
        "phone": "043-719-8360",
        "description_summary": "국가예방접종 기획·효과평가·관리, 예방접종 이상반응 신고·보상, 접종 정책 및 일정 관련 전문 문의",
    },
    {
        "keywords": ["말라리아", "진드기", "인수공통"],
        "org_name": "감염병정책국 인수공통감염병관리과",
        "dept_name": "인수공통감염병관리과",
        "phone": "043-719-7160",
        "description_summary": "말라리아, 진드기 매개 감염병 관리, 인수공통감염병 예방대책 수립 문의",
    },
]

# 기관 미발견 시 폴백
TRANSFER_FALLBACK = {
    "org_name": "정부민원안내콜센터",
    "dept_name": None,
    "phone": "110",
    "description_summary": "정부 민원 통합 안내. 담당 기관을 찾지 못한 경우 110으로 연결하면 적절한 기관으로 안내받을 수 있습니다.",
    "similarity": 0.0,
}

TRANSFER_FALLBACK_INFECTIOUS = {
    "org_name": "감염병정책국 감염병관리과",
    "dept_name": "감염병관리과",
    "phone": "043-719-7140",
    "description_summary": "법정감염병 신고·관리, 감염병 예방·대응 관련 문의. 담당 질환이 불분명한 경우 감염병관리과로 문의하세요.",
    "similarity": 0.0,
}


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def _embed(text: str) -> list[float]:
    client = _get_client()
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding


def _vec_str(vec: list[float]) -> str:
    return "[" + ",".join(map(str, vec)) + "]"


async def _search_knowledge(pool, query_vec: list[float], disease_name: str | None) -> list[dict]:
    disease_filter = "AND disease_name = $3" if disease_name else ""
    params = [_vec_str(query_vec), SIMILARITY_THRESHOLD]
    if disease_name:
        params.append(disease_name)

    rows = await pool.fetch(
        f"""
        SELECT chunk_index AS chunk_id, document_title, section_title, data_id, chunk_text,
               1 - (embedding <=> $1::vector) AS similarity
        FROM knowledge_chunks
        WHERE 1 - (embedding <=> $1::vector) >= $2
          {disease_filter}
        ORDER BY embedding <=> $1::vector
        LIMIT {TOP_K}
        """,
        *params,
    )
    return [dict(r) for r in rows]


async def _search_acw(pool, query_vec: list[float]) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT acw_id, title, qa_summary,
               1 - (q_embedding <=> $1::vector) AS similarity
        FROM acw_cards
        WHERE q_embedding IS NOT NULL
          AND 1 - (q_embedding <=> $1::vector) >= $2
        ORDER BY q_embedding <=> $1::vector
        LIMIT $3
        """,
        _vec_str(query_vec), SIMILARITY_THRESHOLD, TOP_K,
    )
    result = []
    for r in rows:
        qa_raw = r["qa_summary"] or "[]"
        if isinstance(qa_raw, str):
            try:
                qa = json.loads(qa_raw)
            except Exception:
                qa = []
        elif isinstance(qa_raw, list):
            qa = qa_raw
        else:
            qa = []
        result.append({
            "acw_id": r["acw_id"],
            "title": r["title"],
            "similarity": float(r["similarity"]),
            "qa_summary": qa,   # [{q: "...", a: "..."}] 형태로 파싱
        })
    return result


async def _pick_best_agency(pool, query_vec: list[float], agencies: list[dict]) -> dict:
    """agencies 리스트 중 query와 description_embedding 유사도가 가장 높은 1개 반환"""
    org_names = [a["org_name"] for a in agencies]
    try:
        rows = await pool.fetch(
            """
            SELECT org_name,
                   1 - (description_embedding <=> $1::vector) AS similarity
            FROM transfer_agencies
            WHERE org_name = ANY($2::text[])
              AND description_embedding IS NOT NULL
            ORDER BY description_embedding <=> $1::vector
            LIMIT 1
            """,
            _vec_str(query_vec), org_names,
        )
        if rows:
            best_name = rows[0]["org_name"]
            return next((a for a in agencies if a["org_name"] == best_name), agencies[0])
    except Exception:
        pass
    return agencies[0]


async def _search_transfer(
    pool, query_vec: list[float], query_text: str = "", keyword_only: bool = False,
    category: str | None = None,
) -> list[dict]:
    # pool은 asyncpg Pool 또는 Connection 모두 허용
    # ── ① 키워드 매칭 (모든 카테고리) ────────────────────────────
    for mapping in TRANSFER_KEYWORD_MAP:
        if any(kw in query_text for kw in mapping["keywords"]):
            # agencies 리스트 형태 → 유사도로 1개 선택
            if "agencies" in mapping:
                best = await _pick_best_agency(pool, query_vec, mapping["agencies"])
                return [{
                    "org_name":            best["org_name"],
                    "dept_name":           best["dept_name"],
                    "phone":               best["phone"],
                    "description_summary": best["description_summary"],
                    "similarity":          1.0,
                    "matched_by":          "keyword",
                }]
            # 단일 기관 형태
            return [{
                "org_name":            mapping["org_name"],
                "dept_name":           mapping["dept_name"],
                "phone":               mapping["phone"],
                "description_summary": mapping["description_summary"],
                "similarity":          1.0,
                "matched_by":          "keyword",
            }]

    # 키워드 미매칭 + 이관 외 카테고리 → 빈 배열 반환
    if keyword_only:
        return []

    # ── ② 임베딩 검색 (이관 카테고리 전용) ──────────────────────
    rows = await pool.fetch(
        """
        SELECT org_name, dept_name, phone, description_summary,
               1 - (description_embedding <=> $1::vector) AS similarity
        FROM transfer_agencies
        WHERE description_embedding IS NOT NULL
          AND 1 - (description_embedding <=> $1::vector) >= $2
        ORDER BY description_embedding <=> $1::vector
        LIMIT 1
        """,
        _vec_str(query_vec), TRANSFER_THRESHOLD,
    )

    if rows:
        r = rows[0]
        return [{
            "org_name":            r["org_name"],
            "dept_name":           r["dept_name"],
            "phone":               r["phone"],
            "description_summary": r["description_summary"],
            "similarity":          float(r["similarity"]),
            "matched_by":          "embedding",
        }]

    # ── ③ 폴백: 감염병이면 감염병관리과, 나머지는 110 ────────────
    if category == "감염병":
        return [TRANSFER_FALLBACK_INFECTIOUS]
    return [TRANSFER_FALLBACK]


async def run_step2(query: str, disease_name: str | None, call_id: int) -> dict:
    pool = await get_pool()
    query_vec = await _embed(query)

    results = await asyncio.gather(
        _search_knowledge(pool, query_vec, disease_name),
        _search_acw(pool, query_vec),
        _search_transfer(pool, query_vec),
        return_exceptions=True,
    )

    knowledge = results[0] if not isinstance(results[0], Exception) else []
    similar = results[1] if not isinstance(results[1], Exception) else []
    transfer = results[2] if not isinstance(results[2], Exception) else []

    return {
        "knowledge_chunks": knowledge,
        "similar_cases": similar,
        "transfer_suggestions": transfer,
    }

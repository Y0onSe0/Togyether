"""
검역관리지역 API 라우터
공공데이터포털 검역관리지역 정보 API 연동

API 1 (icdCd 기반): 감염병코드 → 검역 대상국가 목록
API 2 (ntnNm 기반): 국가명 → 해당 국가의 검역감염병 목록

endpoints:
  GET /api/quarantine/country?name={국가명}   — 국가별 검역감염병 조회
  GET /api/quarantine/disease?icd={코드}      — 감염병별 검역대상국 조회
  GET /api/quarantine/search?query={쿼리}     — 쿼리 자동 분석 후 적절한 API 호출
"""
import time
from datetime import datetime
from urllib.parse import quote

import httpx
import xml.etree.ElementTree as ET
from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings

router = APIRouter(prefix="/api/quarantine", tags=["quarantine"])

# ── 감염병 코드 매핑 ──────────────────────────────────────────────────
ICD_MAP = {
    "뎅기열": "182", "동물인플루엔자": "172", "조류인플루엔자": "172",
    "라싸열": "179", "사스": "103",
    "에볼라": "178", "에볼라바이러스": "178",
    "엠폭스": "181", "원숭이두창": "181",
    "메르스": "176", "중동호흡기증후군": "176",
    "지카": "177", "지카바이러스": "177",
    "치쿤구니야": "183",
    "코로나": "180", "코로나19": "180", "코비드": "180",
    "콜레라": "100", "페스트": "101",
    "폴리오": "175", "소아마비": "175",
    "홍역": "184", "황열": "102",
}

# ── 24시간 인메모리 캐시 ─────────────────────────────────────────────
_cache: dict[str, tuple[float, list]] = {}  # key → (timestamp, data)
CACHE_TTL = 60 * 60 * 24  # 24시간


def _cache_get(key: str) -> list | None:
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
    return None


def _cache_set(key: str, data: list):
    _cache[key] = (time.time(), data)


# ── API 호출 헬퍼 ─────────────────────────────────────────────────────
async def _call_api(endpoint: str, params: dict) -> list[dict]:
    """공통 API 호출 → items 파싱"""
    base = settings.QUARANTINE_API_URL.rstrip("/")
    param_str = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
    url = f"{base}/{endpoint}?serviceKey={quote(settings.DATA_GO_KR_API_KEY, safe='')}&resType=1&pageNo=1&numOfRows=50&{param_str}"

    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    result_code = root.findtext(".//resultCode", "")
    if result_code not in ("00", "0"):
        raise HTTPException(status_code=502, detail=f"API 오류: {root.findtext('.//resultMsg', '')}")

    return [
        {child.tag: (child.text or "").strip() for child in item}
        for item in root.findall(".//item")
    ]


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


DATE_FILTER_FROM = "2022-01-01"  # 이 날짜 이전 start_date 데이터는 표시하지 않음


# ── 엔드포인트 ────────────────────────────────────────────────────────

@router.get("/country")
async def get_by_country(name: str = Query(..., description="국가명 (예: 베트남)")):
    """
    국가명 → 해당 국가의 현재 검역감염병 목록
    """
    cache_key = f"country:{name}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {"success": True, "country": name, "data": cached, "cached": True}

    items = await _call_api(
        "NationDisease",
        {"ntnNm": name, "useYn": "Y"},
    )

    # 병명 기준 중복 제거 (같은 병명 중 start_date 최신 것만 유지)
    seen: dict[str, dict] = {}
    for r in items:
        if r.get("useYn", "Y") != "Y":
            continue
        disease    = r.get("ovseaIcdKornNm", "")
        start_date = r.get("srvlncBgngYmd", "") or ""
        end_date   = r.get("srvlncEndYmd",  "") or ""
        # 2022년 이전 데이터 필터링
        if start_date and start_date < DATE_FILTER_FROM:
            continue
        if disease not in seen or start_date > seen[disease]["start_date"]:
            seen[disease] = {
                "disease":    disease,
                "start_date": start_date,
                "end_date":   end_date if end_date else "현재",
            }

    result = sorted(seen.values(), key=lambda x: x["start_date"], reverse=True)

    _cache_set(cache_key, result)
    return {"success": True, "country": name, "data": result, "cached": False}


@router.get("/disease")
async def get_by_disease(icd: str = Query(..., description="감염병 코드 (예: 180)")):
    """
    감염병 코드 → 검역 대상국가 목록 + 감시기간
    """
    cache_key = f"disease:{icd}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {"success": True, "icd": icd, "data": cached, "cached": True}

    items = await _call_api(
        "DiseaseNation",
        {"icdCd": icd},
    )

    result = sorted(
        [
            {
                "group_name": r.get("riskGroupNm", ""),
                "nations":    [n.strip() for n in r.get("nationNm", "").split(",") if n.strip()],
                "watch_days": r.get("srvlncPerdCnt", ""),
                "start_date": r.get("mngBgngDt", ""),
                "end_date":   r.get("mngEndDt", ""),
            }
            for r in items
            if r.get("useYn", "Y") == "Y"
            and (r.get("mngBgngDt", "") or "") >= DATE_FILTER_FROM  # 2022년 이전 제외
        ],
        key=lambda x: x["start_date"] or "",
        reverse=True,  # 최신순
    )

    _cache_set(cache_key, result)
    return {"success": True, "icd": icd, "data": result, "cached": False}


@router.get("/search")
async def search(query: str = Query(..., description="고객 문의 텍스트")):
    """
    쿼리 자동 분석:
    - 국가명 감지 → /country API
    - 감염병명 감지 → /disease API
    """
    # 국가명 간단 매칭 (자주 나오는 국가)
    COMMON_COUNTRIES = [
        "베트남", "태국", "필리핀", "인도네시아", "말레이시아", "싱가포르",
        "인도", "중국", "일본", "미국", "유럽", "아프리카", "중동",
        "이집트", "터키", "브라질", "멕시코", "페루", "콜롬비아",
    ]
    print(f"[검역] search query: {query!r}")
    found_country = next((c for c in COMMON_COUNTRIES if c in query), None)
    print(f"[검역] found_country: {found_country}")

    if found_country:
        return await get_by_country(found_country)

    # 감염병명 매칭
    found_icd = next((ICD_MAP[k] for k in ICD_MAP if k in query), None)

    if found_icd:
        return await get_by_disease(found_icd)

    # 매칭 실패
    return {
        "success": True,
        "matched": False,
        "message": "국가명이나 감염병명을 포함해 다시 문의해 주세요.",
        "links": [
            {"label": "해외감염병 NOW", "url": "https://해외감염병now.kr"},
            {"label": "검역정보 포털",  "url": "https://quarantine.kdca.go.kr"},
        ],
    }

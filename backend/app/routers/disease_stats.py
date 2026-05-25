"""
전수신고 감염병 발생현황 API 연동 라우터
공공데이터포털: apis.data.go.kr/1790387/EIDAPIService

확인된 오퍼레이션 (Swagger 기준):
  /Gender   - 성별 발생현황    (searchType, searchYear)
  /Age      - 연령별 발생현황  (searchType, searchYear)
  /Region   - 지역별 발생현황  (searchType, searchYear, searchSidoCd)
  /Disease  - 감염병별 발생현황 (searchType, searchYear, patntType)

응답 구조: response.body.items.item (JSON, resType=2)
"""

import asyncio
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Query
import asyncpg

from app.core.config import settings
from app.core.database import get_conn
from app.core.dependencies import get_current_agent

router = APIRouter(prefix="/api/disease-stats", tags=["disease-stats"])

# ── 인메모리 캐시 (TTL 1시간) ─────────────────────────────────
_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 3600

def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < _CACHE_TTL:
        return entry[1]
    return None

def _cache_set(key: str, value):
    _cache[key] = (time.time(), value)


# ── 공통 ──────────────────────────────────────────────────────
_BASE_URL = "https://apis.data.go.kr/1790387/EIDAPIService"
_last_api_error: dict = {}


def _safe_int(v) -> int:
    try:
        return int(v or 0)
    except (ValueError, TypeError):
        return 0


async def _fetch(operation: str, params: dict) -> list[dict]:
    """EIDAPIService 호출. 실패 시 [] 반환."""
    global _last_api_error
    if not settings.DATA_GO_KR_API_KEY:
        _last_api_error = {"reason": "API 키 미설정"}
        return []

    url = f"{_BASE_URL}/{operation}"
    query = {
        "serviceKey": settings.DATA_GO_KR_API_KEY,
        "resType": "2",       # JSON
        "pageNo": 1,
        "numOfRows": 1000,
        **params,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=query)
            _last_api_error = {
                "url": str(resp.url),
                "status": resp.status_code,
                "body_preview": resp.text[:400],
            }
            if resp.status_code != 200:
                return []
            body = resp.json()

            # 표준 응답: response.body.items.item
            items = (
                body.get("response", {})
                    .get("body", {})
                    .get("items", {})
                    .get("item", [])
            )
            if isinstance(items, dict):
                items = [items]
            return items if isinstance(items, list) else []
    except Exception as e:
        _last_api_error = {"exception": str(e), "url": url}
        return []


# ── Mock 데이터 ───────────────────────────────────────────────
_MOCK_BY_DISEASE = [
    {"diseaseName": "코로나19(COVID-19)", "cnt": 14320},
    {"diseaseName": "인플루엔자(독감)",   "cnt": 9870},
    {"diseaseName": "수두",               "cnt": 3421},
    {"diseaseName": "결핵",               "cnt": 2810},
    {"diseaseName": "성홍열",             "cnt": 1934},
    {"diseaseName": "유행성이하선염",     "cnt": 1452},
    {"diseaseName": "풍진",               "cnt": 874},
    {"diseaseName": "백일해",             "cnt": 643},
    {"diseaseName": "홍역",               "cnt": 421},
    {"diseaseName": "B형간염",            "cnt": 318},
]

_MOCK_TREND = [
    {"period": "2024-11", "label": "11월", "코로나19": 9820,  "독감": 3200,  "calls": 14320},
    {"period": "2024-12", "label": "12월", "코로나19": 12400, "독감": 6800,  "calls": 18750},
    {"period": "2025-01", "label": "1월",  "코로나19": 18200, "독감": 11200, "calls": 27430},
    {"period": "2025-02", "label": "2월",  "코로나19": 15600, "독감": 9800,  "calls": 22180},
    {"period": "2025-03", "label": "3월",  "코로나19": 11300, "독감": 7200,  "calls": 16920},
    {"period": "2025-04", "label": "4월",  "코로나19": 9100,  "독감": 4500,  "calls": 13540},
    {"period": "2025-05", "label": "5월",  "코로나19": 14320, "독감": 9870,  "calls": 21650},
]

_MOCK_GENDER = [
    {"sex": "남성", "cnt": 52840},
    {"sex": "여성", "cnt": 61230},
]

_MOCK_AGE = [
    {"ageGroup": "0-9세",   "cnt": 8420},
    {"ageGroup": "10-19세", "cnt": 12380},
    {"ageGroup": "20-29세", "cnt": 15920},
    {"ageGroup": "30-39세", "cnt": 14870},
    {"ageGroup": "40-49세", "cnt": 17230},
    {"ageGroup": "50-59세", "cnt": 19840},
    {"ageGroup": "60-69세", "cnt": 18620},
    {"ageGroup": "70세+",   "cnt": 16790},
]


# ── 감염병별 발생현황 TOP 10 ──────────────────────────────────
@router.get("/by-disease")
async def by_disease(
    year: str = Query("2025", description="조회 연도 (YYYY)"),
    search_type: str = Query("1", description="1:발생수 / 2:인구10만명당발생률"),
    patnt_type: str = Query("1", description="1:전체 / 2:환자분류별"),
    agent_id: int = Depends(get_current_agent),
):
    """
    /Disease 오퍼레이션
    파라미터: searchType, searchYear, patntType
    응답 필드: year, patntType, icdGroupNm, icdNm, resultVal
    """
    cache_key = f"by_disease:{year}:{search_type}:{patnt_type}"
    if cached := _cache_get(cache_key):
        return cached

    items = await _fetch("Disease", {
        "searchType": search_type,
        "searchYear": year,
        "patntType": patnt_type,
    })

    if items:
        # patntType='계' 행만 집계 (전체 합계)
        agg: dict[str, int] = {}
        for it in items:
            if it.get("patntType") in ("계", None, ""):
                name = it.get("icdNm", "알 수 없음")
                agg[name] = agg.get(name, 0) + _safe_int(it.get("resultVal"))
        result = sorted(
            [{"diseaseName": k, "cnt": v} for k, v in agg.items()],
            key=lambda x: x["cnt"], reverse=True
        )[:10]
        if not result:
            # patntType 필드 없는 경우 전체 합산
            agg2: dict[str, int] = {}
            for it in items:
                name = it.get("icdNm", "알 수 없음")
                agg2[name] = agg2.get(name, 0) + _safe_int(it.get("resultVal"))
            result = sorted(
                [{"diseaseName": k, "cnt": v} for k, v in agg2.items()],
                key=lambda x: x["cnt"], reverse=True
            )[:10]
    else:
        result = _MOCK_BY_DISEASE

    data = {"year": year, "items": result, "is_mock": not bool(items)}
    _cache_set(cache_key, data)
    return data


# ── 성별 발생현황 ──────────────────────────────────────────────
@router.get("/by-gender")
async def by_gender(
    year: str = Query("2025", description="연도 (YYYY)"),
    search_type: str = Query("1", description="1:발생수 / 2:인구10만명당발생률"),
    agent_id: int = Depends(get_current_agent),
):
    """
    /Gender 오퍼레이션
    파라미터: searchType, searchYear
    응답 필드: year, sex(계/남/여), icdGroupNm, icdNm, resultVal
    """
    cache_key = f"gender:{year}:{search_type}"
    if cached := _cache_get(cache_key):
        return cached

    items = await _fetch("Gender", {"searchType": search_type, "searchYear": year})

    if items:
        agg: dict[str, int] = {}
        for it in items:
            sex = it.get("sex", "")
            if sex in ("남", "여"):
                agg[sex] = agg.get(sex, 0) + _safe_int(it.get("resultVal"))
        result = [{"sex": k + "성", "cnt": v} for k, v in agg.items()]
    else:
        result = _MOCK_GENDER

    data = {"year": year, "items": result, "is_mock": not bool(items)}
    _cache_set(cache_key, data)
    return data


# ── 연령별 발생현황 ────────────────────────────────────────────
@router.get("/by-age")
async def by_age(
    year: str = Query("2025", description="연도 (YYYY)"),
    search_type: str = Query("10", description="1:1세단위 / 5:5세단위 / 10:10세단위"),
    agent_id: int = Depends(get_current_agent),
):
    """
    /Age 오퍼레이션
    파라미터: searchType(연령단위), searchYear
    응답 필드: year, ageRange, icdGroupNm, icdNm, resultVal
    """
    cache_key = f"age:{year}:{search_type}"
    if cached := _cache_get(cache_key):
        return cached

    items = await _fetch("Age", {"searchType": search_type, "searchYear": year})

    if items:
        agg: dict[str, int] = {}
        for it in items:
            age = it.get("ageRange", "")
            if age and age != "계":
                agg[age] = agg.get(age, 0) + _safe_int(it.get("resultVal"))
        result = [{"ageGroup": k, "cnt": v} for k, v in sorted(agg.items())]
    else:
        result = _MOCK_AGE

    data = {"year": year, "items": result, "is_mock": not bool(items)}
    _cache_set(cache_key, data)
    return data


# ── 연도별 추이 + 1339 콜 건수 상관관계 ──────────────────────
@router.get("/trend-with-calls")
async def trend_with_calls(
    months: int = Query(7, ge=1, le=24, description="조회 개월 수"),
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    """
    연도별 주요 감염병 확진자 수 + 1339 콜 건수 통합 데이터
    · 확진자: /Disease (연도별)
    · 콜 건수: acw_cards 테이블
    """
    cache_key = f"trend_calls:{months}"
    if cached := _cache_get(cache_key):
        return cached

    # 내부 DB 월별 콜 건수
    call_rows = await conn.fetch(
        """
        SELECT TO_CHAR(DATE_TRUNC('month', created_at), 'YYYY-MM') AS ym,
               COUNT(*) AS calls
        FROM acw_cards
        WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE)
                           - ($1 - 1) * INTERVAL '1 month'
        GROUP BY ym ORDER BY ym
        """,
        months,
    )
    call_map = {r["ym"]: int(r["calls"]) for r in call_rows}

    if settings.DATA_GO_KR_API_KEY:
        now = datetime.now(timezone.utc)
        # 최근 N개월의 연도 목록 (중복 제거)
        years: list[str] = []
        for i in range(months - 1, -1, -1):
            month = now.month - i
            year = now.year
            while month <= 0:
                month += 12; year -= 1
            y = str(year)
            if y not in years:
                years.append(y)

        # 연도별 Disease API 병렬 호출
        tasks = [_fetch("Disease", {"searchType": "1", "searchYear": y, "patntType": "1"})
                 for y in years]
        results_by_year = dict(zip(years, await asyncio.gather(*tasks, return_exceptions=True)))

        # 월별 트렌드 구성
        trend = []
        for i in range(months - 1, -1, -1):
            month = now.month - i
            year = now.year
            while month <= 0:
                month += 12; year -= 1
            ym     = f"{year}-{month:02d}"
            label  = f"{month}월"
            row    = {"period": ym, "label": label, "calls": call_map.get(ym, 0)}

            year_items = results_by_year.get(str(year))
            if isinstance(year_items, list) and year_items:
                agg: dict[str, int] = {}
                for it in year_items:
                    if it.get("patntType") in ("계", None, ""):
                        name = it.get("icdNm", "")
                        agg[name] = agg.get(name, 0) + _safe_int(it.get("resultVal"))
                top3 = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:3]
                for name, cnt in top3:
                    row[name] = cnt
            trend.append(row)
    else:
        trend = []
        for item in _MOCK_TREND[-months:]:
            row = dict(item)
            row["calls"] = call_map.get(item["period"], item["calls"])
            trend.append(row)

    data = {
        "months": months,
        "trend": trend,
        "is_mock": not bool(settings.DATA_GO_KR_API_KEY),
    }
    _cache_set(cache_key, data)
    return data


# ── 디버그 ────────────────────────────────────────────────────
@router.get("/debug")
async def debug_api(agent_id: int = Depends(get_current_agent)):
    key = settings.DATA_GO_KR_API_KEY
    key_set = bool(key)
    live = {}
    if key_set:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{_BASE_URL}/Gender", params={
                    "serviceKey": key, "resType": "2",
                    "searchType": "1", "searchYear": "2025",
                    "pageNo": 1, "numOfRows": 3,
                })
                live = {"status": r.status_code, "body": r.text[:300]}
        except Exception as e:
            live = {"exception": str(e)}

    return {
        "key_set": key_set,
        "key_preview": (key[:8] + "..." + key[-4:]) if key_set else "(없음)",
        "last_api_error": _last_api_error,
        "live_test_Gender": live,
        "cached_keys": list(_cache.keys()),
    }


# ── 캐시 초기화 ───────────────────────────────────────────────
@router.delete("/cache")
async def clear_cache(agent_id: int = Depends(get_current_agent)):
    _cache.clear()
    return {"message": "캐시 초기화 완료"}

"""
예방접종 정보 API 라우터
공공데이터포털 예방접종(대상 감염병 관련) 정보 API 연동

흐름:
  쿼리 → 키워드 매칭 → vcnCd
    캐시 HIT  → 즉시 반환
    캐시 MISS → getVcnInfo API → LLM 파싱 → 24h 캐시 저장 → 반환

endpoints:
  GET /api/vaccine/search?query={쿼리}
"""
import json
import time
from urllib.parse import quote

import httpx
import xml.etree.ElementTree as ET
from fastapi import APIRouter, HTTPException, Query
from openai import AsyncOpenAI

from app.core.config import settings

router = APIRouter(prefix="/api/vaccine", tags=["vaccine"])

BASE_URL = "https://apis.data.go.kr/1790387/vcninfo"

_openai: AsyncOpenAI | None = None

def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai


# ── 키워드 → vcnCd 매핑 ───────────────────────────────────────────────
KEYWORD_MAP = {
    "bcg": "01", "결핵": "01",
    "b형간염": "02", "비형간염": "02",
    "dtap": "03", "디프테리아": "03", "파상풍": "03", "백일해": "03",
    "소아마비": "04", "폴리오": "04", "ipv": "04",
    "헤모필루스": "05", "hib": "05",
    "폐렴구균": "06", "폐렴": "06",
    "로타": "07", "로타바이러스": "07",
    "수두": "08",
    "홍역": "09", "유행성이하선염": "09", "볼거리": "09", "풍진": "09", "mmr": "09",
    "a형간염": "10", "에이형간염": "10",
    "일본뇌염": "11", "뇌염": "11",
    "td": "12",
    "독감": "13", "인플루엔자": "13", "플루": "13",
    "장티푸스": "14",
    "신증후군출혈열": "15", "유행성출혈열": "15",
    "광견병": "16", "공수병": "16",
    "탄저": "17",
    "두창": "18", "천연두": "18",
    "콜레라": "19",
    "황열": "20",
    "hpv": "21", "자궁경부암": "21", "인유두종": "21",
}

VCN_NAMES = {
    "01": "결핵(BCG)", "02": "B형간염", "03": "DTaP(디프테리아·파상풍·백일해)",
    "04": "폴리오(소아마비)", "05": "B형헤모필루스인플루엔자", "06": "폐렴구균",
    "07": "로타바이러스", "08": "수두", "09": "MMR(홍역·유행성이하선염·풍진)",
    "10": "A형간염", "11": "일본뇌염", "12": "Td(파상풍·디프테리아)",
    "13": "인플루엔자(독감)", "14": "장티푸스", "15": "신증후군출혈열",
    "16": "광견병", "17": "탄저", "18": "두창", "19": "콜레라",
    "20": "황열", "21": "HPV(사람유두종바이러스)",
}

# ── 24시간 캐시 (vcnCd → 파싱 결과) ─────────────────────────────────
_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 60 * 60 * 24


def _cache_get(vcn_cd: str) -> dict | None:
    if vcn_cd in _cache:
        ts, data = _cache[vcn_cd]
        if time.time() - ts < CACHE_TTL:
            return data
    return None


def _cache_set(vcn_cd: str, data: dict):
    _cache[vcn_cd] = (time.time(), data)


# ── API + LLM ─────────────────────────────────────────────────────────
async def _fetch_vcn_info(vcn_cd: str) -> dict:
    url = (
        f"{BASE_URL}/getVcnInfo"
        f"?serviceKey={quote(settings.DATA_GO_KR_API_KEY, safe='')}"
        f"&vcnCd={vcn_cd}"
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    item = root.find(".//item")
    if item is None:
        return {}
    return {
        "title":   (item.findtext("title") or "").strip(),
        "message": (item.findtext("message") or "").strip(),
    }


async def _parse_with_llm(title: str, message: str) -> dict:
    system = """예방접종 공식 정보에서 아래 필드를 추출해 JSON으로 반환하세요.
{
  "schedule":     "접종 시기·일정 (없으면 null)",
  "target":       "접종 대상 (없으면 null)",
  "side_effects": "주요 이상반응 (없으면 null)",
  "summary":      "감염병 한 줄 설명 (없으면 null)"
}
규칙: 원문에 없는 내용은 생성하지 마세요. 각 필드는 1~2문장 이내."""

    resp = await _get_openai().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": f"[{title}]\n{message[:3000]}"},
        ],
        temperature=0,
        max_tokens=300,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


# ── 엔드포인트 ────────────────────────────────────────────────────────
@router.get("/search")
async def vaccine_search(query: str = Query(...)):
    q = query.lower().replace(" ", "")
    vcn_cd = next((KEYWORD_MAP[k] for k in KEYWORD_MAP if k in q), None)

    if not vcn_cd:
        return {
            "success": False,
            "matched": False,
            "message": "접종 정보를 찾지 못했습니다. 예방접종도우미에서 확인해 주세요.",
        }

    # 캐시 HIT → 즉시 반환
    cached = _cache_get(vcn_cd)
    if cached:
        return {"success": True, "matched": True, "cached": True, **cached}

    # 캐시 MISS → API + LLM
    raw = await _fetch_vcn_info(vcn_cd)
    if not raw:
        raise HTTPException(status_code=404, detail="예방접종 정보 없음")

    parsed = await _parse_with_llm(raw["title"], raw["message"])

    result = {
        "vcn_cd":      vcn_cd,
        "title":       raw["title"],
        "summary":     parsed.get("summary"),
        "schedule":    parsed.get("schedule"),
        "target":      parsed.get("target"),
        "side_effects": parsed.get("side_effects"),
    }

    _cache_set(vcn_cd, result)
    return {"success": True, "matched": True, "cached": False, **result}

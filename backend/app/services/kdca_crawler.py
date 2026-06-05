"""
질병관리청 보도자료 RSS 크롤러
https://www.kdca.go.kr/bbs/kdca/42/rssList.do?row=50

- 6시간마다 자동 실행 (main.py lifespan에서 등록)
- 중복 방지: link 컬럼 UNIQUE 제약으로 ON CONFLICT DO NOTHING
"""

import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx
from app.core.database import get_pool

logger = logging.getLogger(__name__)

KDCA_RSS_URL = "https://www.kdca.go.kr/bbs/kdca/42/rssList.do?row=50"
CRAWL_INTERVAL_SECONDS = 6 * 60 * 60  # 6시간


async def fetch_kdca_notices() -> list[dict]:
    """KDCA RSS 피드 파싱 → 보도자료 목록 반환"""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(KDCA_RSS_URL, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    channel = root.find("channel")
    if channel is None:
        return []

    notices = []
    for item in channel.findall("item"):
        def get_text(tag):
            el = item.find(tag)
            if el is None:
                return ""
            return (el.text or "").strip()

        title = get_text("title")
        link  = get_text("link")
        pub_date_raw = get_text("pubDate")
        author = get_text("author")
        description = get_text("description")

        # link가 상대경로면 절대경로로 변환
        if link and link.startswith("/"):
            link = f"https://www.kdca.go.kr{link}"

        # pubDate 파싱: "2026-06-04 14:20:00.0"
        published_at = None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                published_at = datetime.strptime(pub_date_raw, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue

        if title and link:
            notices.append({
                "title": title,
                "link": link,
                "published_at": published_at,
                "author": author or None,
                "description": description[:500] if description else None,
            })

    return notices


async def save_notices(notices: list[dict]) -> int:
    """DB에 저장 — 중복 link는 스킵. 저장된 건수 반환."""
    if not notices:
        return 0

    pool = await get_pool()
    saved = 0
    async with pool.acquire() as conn:
        for n in notices:
            result = await conn.execute(
                """
                INSERT INTO kdca_notices (title, link, published_at, author, description)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (link) DO NOTHING
                """,
                n["title"], n["link"], n["published_at"], n["author"], n["description"],
            )
            if result == "INSERT 0 1":
                saved += 1

    return saved


async def crawl_once():
    """1회 크롤링 실행"""
    try:
        logger.info("[KDCA Crawler] 보도자료 크롤링 시작")
        notices = await fetch_kdca_notices()
        saved = await save_notices(notices)
        logger.info(f"[KDCA Crawler] 완료 — 총 {len(notices)}건 파싱, {saved}건 신규 저장")
    except Exception as e:
        logger.error(f"[KDCA Crawler] 오류: {e}")


async def crawl_loop():
    """서버 시작 시 즉시 1회 실행 후, 6시간마다 반복"""
    await crawl_once()
    while True:
        await asyncio.sleep(CRAWL_INTERVAL_SECONDS)
        await crawl_once()

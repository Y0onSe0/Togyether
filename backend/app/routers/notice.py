"""
공지사항 API
GET /api/notice/press        — 질병관리청 보도자료 목록
GET /api/notice/similar      — 유사 상담 사례 테이블
GET /api/notice/stats        — 콜센터 실시간 현황
POST /api/notice/crawl       — 수동 즉시 크롤링 트리거
"""

from fastapi import APIRouter, Depends, Query
import asyncpg

from app.core.database import get_conn
from app.core.dependencies import get_current_agent

router = APIRouter(prefix="/api/notice", tags=["notice"])


# ── 콜센터 실시간 현황 ────────────────────────────────────────

@router.get("/stats")
async def get_stats(
    conn: asyncpg.Connection = Depends(get_conn),
    _: int = Depends(get_current_agent),
):
    """콜센터 오늘 현황 통계"""
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE DATE(c.started_at) = CURRENT_DATE)              AS today_calls,
            COUNT(*) FILTER (WHERE c.status = 'active')                             AS active_calls,
            COUNT(*) FILTER (WHERE c.status = 'ended'
                             AND DATE(c.ended_at) = CURRENT_DATE)                   AS today_ended,
            AVG(c.duration_sec) FILTER (WHERE c.status = 'ended'
                                        AND DATE(c.ended_at) = CURRENT_DATE)::INT   AS avg_duration_sec,
            COUNT(DISTINCT c.agent_id) FILTER (WHERE c.status = 'active')           AS active_agents
        FROM calls c
        """
    )
    # 오늘 해결률
    resolved = await conn.fetchval(
        """
        SELECT COUNT(*) FROM acw_cards a
        JOIN calls c USING (call_id)
        WHERE a.is_resolved = true AND DATE(c.ended_at) = CURRENT_DATE
        """
    )
    ended = row["today_ended"] or 0
    resolution_rate = round(resolved / ended * 100) if ended > 0 else 0

    return {
        "today_calls":     row["today_calls"]     or 0,
        "active_calls":    row["active_calls"]    or 0,
        "today_ended":     ended,
        "avg_duration_sec": row["avg_duration_sec"] or 0,
        "active_agents":   row["active_agents"]   or 0,
        "resolution_rate": resolution_rate,
    }


@router.get("/press")
async def get_press_releases(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    conn: asyncpg.Connection = Depends(get_conn),
    _: int = Depends(get_current_agent),
):
    """질병관리청 보도자료 목록 (최신순)"""
    offset = (page - 1) * size

    rows = await conn.fetch(
        """
        SELECT id, title, link, published_at, author, description, created_at
        FROM kdca_notices
        ORDER BY published_at DESC NULLS LAST, created_at DESC
        LIMIT $1 OFFSET $2
        """,
        size, offset,
    )
    total = await conn.fetchval("SELECT COUNT(*) FROM kdca_notices")

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [dict(r) for r in rows],
    }


@router.get("/similar")
async def get_similar_cases(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    conn: asyncpg.Connection = Depends(get_conn),
    _: int = Depends(get_current_agent),
):
    """유사 상담 사례 테이블 — 완료된 통화 기준"""
    offset = (page - 1) * size

    rows = await conn.fetch(
        """
        SELECT
            c.call_id,
            c.started_at,
            c.ended_at,
            EXTRACT(EPOCH FROM (c.ended_at - c.started_at))::int AS duration_sec,
            a.category,
            a.disease_name,
            a.oos_type,
            a.summary
        FROM calls c
        LEFT JOIN acw_cards a ON c.call_id = a.call_id
        WHERE c.status = 'ended'
        ORDER BY c.started_at DESC
        LIMIT $1 OFFSET $2
        """,
        size, offset,
    )
    total = await conn.fetchval(
        "SELECT COUNT(*) FROM calls WHERE status = 'ended'"
    )

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [dict(r) for r in rows],
    }


@router.post("/crawl")
async def trigger_crawl(_: int = Depends(get_current_agent)):
    """수동 즉시 크롤링 트리거"""
    from app.services.kdca_crawler import crawl_once
    import asyncio
    asyncio.create_task(crawl_once())
    return {"message": "크롤링 시작됨"}

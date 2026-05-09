from fastapi import APIRouter, Depends, Query
import asyncpg

from app.core.database import get_conn
from app.core.dependencies import get_current_agent
from app.schemas.dashboard import (
    MySummaryResponse, MyTodayResponse, MyKeywordsResponse,
    MyWeeklyTrendResponse, AllSummaryResponse, TrendResponse,
    CategoryCount, MidCount, KeywordCount, WeeklyTrendItem,
    HourlyCount, TrendItem,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# ── 내 통계 ───────────────────────────────────────────────

@router.get("/my/summary", response_model=MySummaryResponse)
async def my_summary(
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*)                                            AS total_calls,
            COUNT(*) FILTER (WHERE a.is_resolved = true)        AS resolved,
            COUNT(*) FILTER (WHERE a.is_resolved = false)       AS unresolved,
            AVG(c.duration_sec)::INT                            AS avg_duration_sec
        FROM acw_cards a
        JOIN calls c USING (call_id)
        WHERE a.agent_id = $1
          AND DATE(a.created_at) = CURRENT_DATE
        """,
        agent_id,
    )
    return MySummaryResponse(**dict(row))


@router.get("/my/today", response_model=MyTodayResponse)
async def my_today(
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    total = await conn.fetchval(
        "SELECT COUNT(*) FROM acw_cards WHERE agent_id=$1 AND DATE(created_at)=CURRENT_DATE",
        agent_id,
    )
    majors = await conn.fetch(
        """
        SELECT category_major, COUNT(*) AS count
        FROM acw_cards
        WHERE agent_id=$1 AND DATE(created_at)=CURRENT_DATE AND category_major IS NOT NULL
        GROUP BY category_major ORDER BY count DESC
        """,
        agent_id,
    )
    mids = await conn.fetch(
        """
        SELECT category_mid, COUNT(*) AS count
        FROM acw_cards
        WHERE agent_id=$1 AND DATE(created_at)=CURRENT_DATE AND category_mid IS NOT NULL
        GROUP BY category_mid ORDER BY count DESC
        """,
        agent_id,
    )
    return MyTodayResponse(
        total=total,
        by_major=[CategoryCount(**dict(r)) for r in majors],
        by_mid=[MidCount(**dict(r)) for r in mids],
    )


@router.get("/my/keywords", response_model=MyKeywordsResponse)
async def my_keywords(
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    rows = await conn.fetch(
        """
        SELECT kw AS keyword, COUNT(*) AS count
        FROM acw_cards, jsonb_array_elements_text(keywords) AS kw
        WHERE agent_id=$1 AND DATE(created_at)=CURRENT_DATE
        GROUP BY kw ORDER BY count DESC LIMIT 10
        """,
        agent_id,
    )
    return MyKeywordsResponse(keywords=[KeywordCount(**dict(r)) for r in rows])


@router.get("/my/weekly-trend", response_model=MyWeeklyTrendResponse)
async def my_weekly_trend(
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    rows = await conn.fetch(
        """
        SELECT DATE(created_at)::text AS date, disease_name, COUNT(*) AS count
        FROM acw_cards
        WHERE agent_id=$1
          AND created_at >= DATE_TRUNC('week', CURRENT_DATE)
          AND disease_name IS NOT NULL
        GROUP BY DATE(created_at), disease_name
        ORDER BY date, count DESC
        """,
        agent_id,
    )
    return MyWeeklyTrendResponse(data=[WeeklyTrendItem(**dict(r)) for r in rows])


# ── 전체 통계 ─────────────────────────────────────────────

@router.get("/all/summary", response_model=AllSummaryResponse)
async def all_summary(
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE DATE(created_at) = CURRENT_DATE)                      AS today,
            COUNT(*) FILTER (WHERE created_at >= DATE_TRUNC('week', CURRENT_DATE))       AS this_week,
            COUNT(*) FILTER (WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE))      AS this_month
        FROM acw_cards
        """
    )
    hourly = await conn.fetch(
        """
        SELECT EXTRACT(HOUR FROM created_at)::INT AS hour, COUNT(*) AS count
        FROM acw_cards
        WHERE DATE(created_at) = CURRENT_DATE
        GROUP BY hour ORDER BY hour
        """
    )
    return AllSummaryResponse(
        today=row["today"],
        this_week=row["this_week"],
        this_month=row["this_month"],
        hourly=[HourlyCount(**dict(r)) for r in hourly],
    )


def _period_sql(period: str) -> str:
    if period == "today":
        return "DATE(created_at) = CURRENT_DATE"
    elif period == "week":
        return "created_at >= DATE_TRUNC('week', CURRENT_DATE)"
    else:
        return "created_at >= DATE_TRUNC('month', CURRENT_DATE)"


@router.get("/all/disease-trend", response_model=TrendResponse)
async def all_disease_trend(
    period: str = Query("week", pattern="^(today|week|month)$"),
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    rows = await conn.fetch(
        f"""
        SELECT DATE(created_at)::text AS date, disease_name, COUNT(*) AS count
        FROM acw_cards
        WHERE {_period_sql(period)} AND disease_name IS NOT NULL
        GROUP BY DATE(created_at), disease_name
        ORDER BY date, count DESC
        """
    )
    return TrendResponse(
        period=period,
        data=[TrendItem(date=r["date"], disease_name=r["disease_name"], count=r["count"]) for r in rows],
    )


@router.get("/all/category-trend", response_model=TrendResponse)
async def all_category_trend(
    period: str = Query("week", pattern="^(today|week|month)$"),
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    rows = await conn.fetch(
        f"""
        SELECT DATE(created_at)::text AS date, category_mid, COUNT(*) AS count
        FROM acw_cards
        WHERE {_period_sql(period)} AND category_mid IS NOT NULL
        GROUP BY DATE(created_at), category_mid
        ORDER BY date, count DESC
        """
    )
    return TrendResponse(
        period=period,
        data=[TrendItem(date=r["date"], category_mid=r["category_mid"], count=r["count"]) for r in rows],
    )

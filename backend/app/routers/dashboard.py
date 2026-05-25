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


# ── 통합 엔드포인트 (프론트에서 한 번에 호출) ──────────────
@router.get("")
async def get_dashboard(
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # 내 통계 - 요약
    summary = await conn.fetchrow(
        """
        SELECT
            COUNT(*)                                             AS total_calls,
            COUNT(*) FILTER (WHERE a.is_resolved = true)         AS resolved,
            AVG(c.duration_sec)::INT                             AS avg_duration_sec
        FROM acw_cards a
        JOIN calls c USING (call_id)
        WHERE a.agent_id = $1
          AND DATE_TRUNC('month', a.created_at) = DATE_TRUNC('month', CURRENT_DATE)
        """,
        agent_id,
    )

    # 내 통계 - 대분류
    majors = await conn.fetch(
        """
        SELECT category_major AS name, COUNT(*) AS count
        FROM acw_cards
        WHERE agent_id=$1 AND category_major IS NOT NULL
          AND DATE_TRUNC('month', created_at) = DATE_TRUNC('month', CURRENT_DATE)
        GROUP BY category_major ORDER BY count DESC
        """,
        agent_id,
    )

    # 내 통계 - 중분류
    mids = await conn.fetch(
        """
        SELECT category_mid AS name, COUNT(*) AS count
        FROM acw_cards
        WHERE agent_id=$1 AND category_mid IS NOT NULL
          AND DATE_TRUNC('month', created_at) = DATE_TRUNC('month', CURRENT_DATE)
        GROUP BY category_mid ORDER BY count DESC LIMIT 10
        """,
        agent_id,
    )

    # 내 통계 - 키워드
    keywords = await conn.fetch(
        """
        SELECT kw AS keyword, COUNT(*) AS count
        FROM acw_cards, jsonb_array_elements_text(keywords) AS kw
        WHERE agent_id=$1
          AND DATE_TRUNC('month', created_at) = DATE_TRUNC('month', CURRENT_DATE)
        GROUP BY kw ORDER BY count DESC LIMIT 10
        """,
        agent_id,
    )

    # 내 통계 - 주간 트렌드
    weekly = await conn.fetch(
        """
        SELECT TO_CHAR(DATE(created_at), 'Dy') AS day, COUNT(*) AS count
        FROM acw_cards
        WHERE agent_id=$1
          AND created_at >= DATE_TRUNC('week', CURRENT_DATE)
        GROUP BY DATE(created_at)
        ORDER BY DATE(created_at)
        """,
        agent_id,
    )

    # 전체 통계 - 요약
    all_summary = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE DATE(created_at) = CURRENT_DATE)                 AS today_count,
            COUNT(*) FILTER (WHERE created_at >= DATE_TRUNC('week', CURRENT_DATE))  AS week_count,
            COUNT(*) FILTER (WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE)) AS month_count
        FROM acw_cards
        """
    )

    # 전체 통계 - 시간대별
    hourly = await conn.fetch(
        """
        SELECT EXTRACT(HOUR FROM created_at)::INT AS hour,
               TO_CHAR(EXTRACT(HOUR FROM created_at)::INT, 'FM00') || '시' AS hour_label,
               COUNT(*) AS count
        FROM acw_cards
        WHERE DATE(created_at) = CURRENT_DATE
        GROUP BY hour ORDER BY hour
        """
    )

    # 전체 통계 - 질병별 월간 추이
    disease_trend = await conn.fetch(
        """
        SELECT TO_CHAR(DATE(created_at), 'MM월') AS month, disease_name, COUNT(*) AS count
        FROM acw_cards
        WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '4 months'
          AND disease_name IS NOT NULL
        GROUP BY TO_CHAR(DATE(created_at), 'MM월'), DATE_TRUNC('month', created_at), disease_name
        ORDER BY DATE_TRUNC('month', created_at), count DESC
        """
    )

    total = summary["total_calls"] or 0
    resolved = summary["resolved"] or 0
    avg_sec = summary["avg_duration_sec"] or 0
    avg_min = f"{avg_sec // 60}분 {avg_sec % 60}초" if avg_sec else "-"
    resolution_rate = round(resolved / total * 100) if total > 0 else 0

    # disease_trend를 {month: {disease: count}} 형태로 변환
    trend_map = {}
    for r in disease_trend:
        month = r["month"]
        if month not in trend_map:
            trend_map[month] = {"month": month}
        trend_map[month][r["disease_name"]] = r["count"]
    disease_line_data = list(trend_map.values())

    return {
        "my_stats": {
            "total_calls": total,
            "avg_duration": avg_min,
            "resolution_rate": resolution_rate,
            "ai_usage_rate": None,
            "major_category_chart": [dict(r) for r in majors],
            "sub_category_chart": [dict(r) for r in mids],
            "top_keywords": [dict(r) for r in keywords],
            "weekly_trend": [dict(r) for r in weekly],
        },
        "all_stats": {
            "today_count": all_summary["today_count"],
            "week_count": all_summary["week_count"],
            "month_count": all_summary["month_count"],
            "hourly_chart": [{"hour": f"{r['hour']}시", "count": r["count"]} for r in hourly],
            "disease_trend": disease_line_data,
        },
    }


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

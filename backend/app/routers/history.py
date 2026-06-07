"""
상담 내역 조회 API
GET /api/history           - 내 상담 목록 (페이징 + 날짜/질병명 필터)
GET /api/history/summary   - 요약 통계
GET /api/history/{call_id} - 상담 상세
"""

import json
from fastapi import APIRouter, Depends, Query, HTTPException
from datetime import date
import asyncpg

from app.core.database import get_conn
from app.core.dependencies import get_current_agent

router = APIRouter(prefix="/api/history", tags=["history"])


def _parse_jsonb(val):
    """asyncpg JSONB 반환값을 Python 객체로 안전하게 변환"""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return None
    return None


@router.get("")
async def get_history(
    start_date: date = Query(None),
    end_date: date = Query(None),
    disease: str = Query(None, description="질병명 검색"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    """내 상담 목록 조회 (최신순) — 날짜 + 질병명 필터"""
    offset = (page - 1) * page_size

    conditions = ["a.agent_id = $1", "a.acw_ended_at IS NOT NULL"]
    params: list = [agent_id]

    if start_date:
        params.append(start_date)
        conditions.append(f"DATE(a.created_at) >= ${len(params)}")
    if end_date:
        params.append(end_date)
        conditions.append(f"DATE(a.created_at) <= ${len(params)}")
    if disease:
        params.append(f"%{disease}%")
        conditions.append(f"a.disease_name ILIKE ${len(params)}")

    where = " AND ".join(conditions)

    total = await conn.fetchval(
        f"SELECT COUNT(*) FROM acw_cards a WHERE {where}", *params
    )

    params += [page_size, offset]
    rows = await conn.fetch(
        f"""
        SELECT
            a.acw_id, a.call_id, a.disease_name,
            a.category_major, a.category_mid,
            a.is_resolved, a.is_transferred, a.transfer_target,
            a.title, a.satisfaction, a.agent_used_ai, a.created_at,
            c.duration_sec, c.started_at
        FROM acw_cards a
        LEFT JOIN calls c USING (call_id)
        WHERE {where}
        ORDER BY a.created_at DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )

    items = []
    for r in rows:
        dur = r["duration_sec"]
        dur_str = f"{dur // 60}분 {dur % 60}초" if dur else "-"
        items.append({
            "acw_id": r["acw_id"],
            "call_id": r["call_id"],
            "disease_name": r["disease_name"] or "-",
            "category_major": r["category_major"] or "-",
            "category_mid": r["category_mid"] or "-",
            "is_resolved": r["is_resolved"],
            "is_transferred": r["is_transferred"],
            "transfer_target": r["transfer_target"],
            "title": r["title"] or "",
            "satisfaction": r["satisfaction"],
            "agent_used_ai": r["agent_used_ai"],
            "duration": dur_str,
            "duration_sec": dur or 0,
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/summary")
async def get_history_summary(
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*)                                                 AS total_calls,
            COUNT(*) FILTER (WHERE is_resolved = true)              AS resolved_calls,
            COUNT(*) FILTER (WHERE is_transferred = true)           AS transferred_calls,
            COUNT(*) FILTER (WHERE DATE(a.created_at) = CURRENT_DATE) AS today_calls,
            AVG(c.duration_sec)::INT                                AS avg_duration_sec
        FROM acw_cards a
        LEFT JOIN calls c USING (call_id)
        WHERE a.agent_id = $1 AND a.acw_ended_at IS NOT NULL
        """,
        agent_id,
    )
    avg_sec = row["avg_duration_sec"] or 0
    avg_str = f"{avg_sec // 60}분 {avg_sec % 60}초" if avg_sec else "-"
    total = row["total_calls"] or 0
    resolved = row["resolved_calls"] or 0

    return {
        "total_calls": total,
        "today_calls": row["today_calls"] or 0,
        "resolved_calls": resolved,
        "transferred_calls": row["transferred_calls"] or 0,
        "resolution_rate": round(resolved / total * 100) if total > 0 else 0,
        "avg_duration": avg_str,
    }


@router.get("/{call_id}")
async def get_history_detail(
    call_id: int,
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    """상담 상세 — q_embedding 제외하고 명시적 컬럼 지정"""
    row = await conn.fetchrow(
        """
        SELECT
            a.acw_id, a.call_id, a.agent_id,
            a.title, a.transcript,
            a.customer_type, a.customer_type_custom,
            a.category, a.category_major, a.category_mid,
            a.category_mid_list, a.category_mid_custom,
            a.disease_name,
            a.qa_summary,
            a.ai_response_summary, a.ai_guidance,
            a.is_resolved, a.is_transferred, a.transfer_target,
            a.keywords, a.agent_used_ai, a.agent_memo,
            a.satisfaction, a.source,
            a.acw_started_at, a.acw_ended_at, a.acw_duration_sec,
            a.created_at,
            c.duration_sec, c.started_at
        FROM acw_cards a
        LEFT JOIN calls c USING (call_id)
        WHERE a.call_id = $1 AND a.agent_id = $2
        """,
        call_id, agent_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="상담 내역을 찾을 수 없습니다.")

    r = dict(row)

    # datetime 직렬화
    for key in ["created_at", "acw_started_at", "acw_ended_at", "started_at"]:
        if r.get(key):
            r[key] = r[key].isoformat()

    # JSONB 필드 명시적 파싱
    r["qa_summary"] = _parse_jsonb(r.get("qa_summary")) or []
    r["ai_guidance"] = _parse_jsonb(r.get("ai_guidance"))
    r["keywords"] = _parse_jsonb(r.get("keywords")) or []
    r["category_mid_list"] = _parse_jsonb(r.get("category_mid_list")) or []

    dur = r.get("duration_sec")
    r["duration"] = f"{dur // 60}분 {dur % 60}초" if dur else "-"

    return r

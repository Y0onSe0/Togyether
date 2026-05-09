import json
from fastapi import APIRouter, Depends, HTTPException
import asyncpg

from app.core.database import get_conn
from app.core.dependencies import get_current_agent
from app.schemas.calls import CallResponse, CallEndResponse
from app.services.pipeline.session import session_store

router = APIRouter(prefix="/api/calls", tags=["calls"])


@router.post("", response_model=CallResponse, status_code=201)
async def start_call(
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow(
        """
        INSERT INTO calls (agent_id, status, started_at)
        VALUES ($1, 'active', NOW())
        RETURNING call_id, agent_id, status, started_at
        """,
        agent_id,
    )
    return CallResponse(**dict(row))


@router.patch("/{call_id}/end", response_model=CallEndResponse)
async def end_call(
    call_id: int,
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # 세션 메모리에서 conversation_history 가져오기
    session = session_store.get(call_id)
    history = session.conversation_history if session else []

    row = await conn.fetchrow(
        """
        UPDATE calls
        SET status               = 'acw',
            ended_at             = NOW(),
            duration_sec         = EXTRACT(EPOCH FROM (NOW() - started_at))::INT,
            conversation_history = $2::jsonb
        WHERE call_id = $1 AND agent_id = $3
        RETURNING call_id, status, ended_at, duration_sec
        """,
        call_id,
        json.dumps(history, ensure_ascii=False),
        agent_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="통화를 찾을 수 없습니다.")
    return CallEndResponse(**dict(row))


@router.get("/{call_id}", response_model=CallResponse)
async def get_call(
    call_id: int,
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow(
        """
        SELECT call_id, agent_id, status, started_at, conversation_history
        FROM calls WHERE call_id = $1 AND agent_id = $2
        """,
        call_id,
        agent_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="통화를 찾을 수 없습니다.")
    data = dict(row)
    if data["conversation_history"] is None:
        data["conversation_history"] = []
    return CallResponse(**data)

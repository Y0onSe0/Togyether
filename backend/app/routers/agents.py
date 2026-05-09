from fastapi import APIRouter, Depends, HTTPException, status
import asyncpg

from app.core.database import get_conn
from app.core.dependencies import get_current_agent
from app.core.security import hash_password
from app.schemas.agents import AgentCreate, AgentResponse, CheckNameResponse
from app.schemas.auth import AgentBrief

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(body: AgentCreate, conn: asyncpg.Connection = Depends(get_conn)):
    if body.password != body.password_confirm:
        raise HTTPException(status_code=400, detail="비밀번호가 일치하지 않습니다.")

    try:
        row = await conn.fetchrow(
            """
            INSERT INTO agents (username, name, password_hash)
            VALUES ($1, $2, $3)
            RETURNING agent_id, username, name, created_at
            """,
            body.username,
            body.name,
            hash_password(body.password),
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.")

    return AgentResponse(**dict(row))


@router.get("/check-name", response_model=CheckNameResponse)
async def check_name(username: str, conn: asyncpg.Connection = Depends(get_conn)):
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM agents WHERE username = $1", username
    )
    return CheckNameResponse(available=count == 0)


@router.get("/me", response_model=AgentResponse)
async def get_me(
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow(
        "SELECT agent_id, username, name, created_at FROM agents WHERE agent_id = $1",
        agent_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="에이전트를 찾을 수 없습니다.")
    return AgentResponse(**dict(row))

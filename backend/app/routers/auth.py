from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import asyncpg

from app.core.database import get_conn
from app.core.security import verify_password, create_access_token, revoke_token
from app.schemas.auth import LoginRequest, LoginResponse, AgentBrief

router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer = HTTPBearer()


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, conn: asyncpg.Connection = Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT agent_id, username, name, password_hash FROM agents WHERE username = $1",
        body.username,
    )
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )
    token = create_access_token(row["agent_id"])
    return LoginResponse(
        access_token=token,
        agent=AgentBrief(
            agent_id=row["agent_id"],
            username=row["username"],
            name=row["name"],
        ),
    )


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # 통화 중 로그아웃 차단
    from app.core.security import decode_token
    try:
        agent_id = decode_token(credentials.credentials)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    active = await conn.fetchval(
        "SELECT call_id FROM calls WHERE agent_id=$1 AND status='active' LIMIT 1",
        agent_id,
    )
    if active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="통화 중에는 로그아웃할 수 없습니다.",
        )
    revoke_token(credentials.credentials)
    return {"message": "로그아웃 되었습니다."}

from datetime import datetime
from typing import Any
from pydantic import BaseModel


class CallResponse(BaseModel):
    call_id: int
    agent_id: int
    agent_name: str | None = None   # agents.name JOIN
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_sec: int | None = None
    conversation_history: list[Any] | None = None


class CallEndResponse(BaseModel):
    call_id: int
    status: str
    ended_at: datetime
    duration_sec: int

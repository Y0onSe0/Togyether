from datetime import datetime
from typing import Any
from pydantic import BaseModel


class CallResponse(BaseModel):
    call_id: int
    agent_id: int
    status: str
    started_at: datetime
    conversation_history: list[Any] | None = None


class CallEndResponse(BaseModel):
    call_id: int
    status: str
    ended_at: datetime
    duration_sec: int

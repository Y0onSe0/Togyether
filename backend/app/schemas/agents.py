from datetime import datetime
from pydantic import BaseModel


class AgentCreate(BaseModel):
    username: str
    name: str
    password: str
    password_confirm: str


class AgentResponse(BaseModel):
    agent_id: int
    username: str
    name: str
    created_at: datetime


class CheckNameResponse(BaseModel):
    available: bool

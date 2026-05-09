from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class AgentBrief(BaseModel):
    agent_id: int
    username: str
    name: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    agent: AgentBrief

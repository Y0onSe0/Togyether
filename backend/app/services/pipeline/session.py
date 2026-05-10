"""
통화 세션 메모리 저장소.
call_id → CallSession (conversation_history, ai_guidance 캐시, LLMSession)
"""
from dataclasses import dataclass, field
from app.services.pipeline.llm_session import CallSession as LLMSession


@dataclass
class CallSession:
    call_id: int
    agent_id: int
    conversation_history: list[dict] = field(default_factory=list)
    ai_guidance: dict | None = None
    llm_session: LLMSession = field(default_factory=LLMSession)


# 프로세스 메모리 기반 세션 저장소 {call_id: CallSession}
session_store: dict[int, CallSession] = {}


def create_session(call_id: int, agent_id: int) -> CallSession:
    session = CallSession(call_id=call_id, agent_id=agent_id)
    session_store[call_id] = session
    return session


def get_session(call_id: int) -> CallSession | None:
    return session_store.get(call_id)


def close_session(call_id: int):
    session_store.pop(call_id, None)

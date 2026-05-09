from datetime import datetime
from typing import Any
from pydantic import BaseModel


class AiGuidanceSource(BaseModel):
    chunk_id: int
    document_title: str
    section_title: str
    data_id: str
    chunk_text: str | None = None


class AiGuidance(BaseModel):
    query: str | None = None
    disease_name: str | None = None
    is_oos: bool = False
    oos_type: str | None = None
    oos_reason: str | None = None
    answer: str | None = None
    sources: list[AiGuidanceSource] = []


class AcwInitResponse(BaseModel):
    acw_id: int
    transcript: str | None
    ai_guidance: AiGuidance | None
    acw_started_at: datetime


class QaSummaryItem(BaseModel):
    q: str
    a: str


class AcwGenerateResponse(BaseModel):
    title: str | None = None
    customer_type: str | None = None
    customer_type_custom: str | None = None
    category: str | None = None
    category_major: str | None = None
    category_mid: str | None = None
    category_mid_list: list[str] = []
    category_mid_custom: str | None = None
    disease_name: str | None = None
    qa_summary: list[QaSummaryItem] = []
    ai_response_summary: str | None = None
    is_transferred: bool = False
    transfer_target: str | None = None
    keywords: list[str] = []


class AcwSaveRequest(BaseModel):
    title: str | None = None
    customer_type: str | None = None
    customer_type_custom: str | None = None
    category: str | None = None
    category_major: str | None = None
    category_mid: str | None = None
    category_mid_list: list[str] = []
    category_mid_custom: str | None = None
    disease_name: str | None = None
    qa_summary: list[QaSummaryItem] = []
    ai_response_summary: str | None = None
    is_transferred: bool = False
    transfer_target: str | None = None
    keywords: list[str] = []
    ai_guidance: AiGuidance | None = None
    is_resolved: bool | None = None
    agent_used_ai: str | None = None
    satisfaction: int | None = None
    agent_memo: str | None = None


class AcwSaveResponse(BaseModel):
    acw_id: int
    call_id: int
    acw_ended_at: datetime
    acw_duration_sec: int

import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
import asyncpg

from app.core.database import get_conn
from app.core.dependencies import get_current_agent
from app.services.pipeline.session import get_session
from app.schemas.acw import (
    AcwInitResponse, AcwGenerateResponse, AcwSaveRequest, AcwSaveResponse,
    AiGuidance, QaSummaryItem,
)

router = APIRouter(prefix="/api/acw", tags=["acw"])


def _history_to_transcript(history: list[dict]) -> str:
    lines = []
    for turn in history:
        ts = turn.get("timestamp", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts)
                ts_str = dt.strftime("%H:%M:%S")
            except Exception:
                ts_str = ts
        else:
            ts_str = ""
        speaker = turn.get("speaker", "")
        text = turn.get("text", "")
        lines.append(f"[{ts_str}] {speaker}: {text}" if ts_str else f"{speaker}: {text}")
    return "\n".join(lines)


@router.get("/{call_id}/init", response_model=AcwInitResponse)
async def acw_init(
    call_id: int,
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # conversation_history 조회
    call_row = await conn.fetchrow(
        "SELECT conversation_history, agent_id FROM calls WHERE call_id=$1", call_id
    )
    if not call_row:
        raise HTTPException(status_code=404, detail="통화를 찾을 수 없습니다.")

    raw_history = call_row["conversation_history"] or []
    if isinstance(raw_history, str):
        try:
            raw_history = json.loads(raw_history)
        except Exception:
            raw_history = []
    history = raw_history if isinstance(raw_history, list) else []
    try:
        transcript = _history_to_transcript(history)
    except Exception:
        transcript = None

    # acw_cards shell 레코드 upsert
    row = await conn.fetchrow(
        """
        INSERT INTO acw_cards (call_id, agent_id, source, transcript, acw_started_at)
        VALUES ($1, $2, 'system', $3, NOW())
        ON CONFLICT (call_id) DO UPDATE
          SET transcript     = EXCLUDED.transcript,
              acw_started_at = EXCLUDED.acw_started_at
        RETURNING acw_id, acw_started_at
        """,
        call_id,
        agent_id,
        transcript or None,
    )

    # ai_guidance 조회: 세션(메모리) → acw_cards(DB) 순으로 fallback
    session = get_session(call_id)
    ai_guidance = None

    # 1차: 세션이 살아있으면 메모리에서 읽기
    if session and session.ai_guidance:
        try:
            ai_guidance = AiGuidance(**session.ai_guidance)
        except Exception:
            pass

    # 2차: 세션이 없으면 DB(acw_cards)에서 읽기 (end_call 시 저장된 값)
    if ai_guidance is None:
        guid_row = await conn.fetchrow(
            "SELECT ai_guidance FROM acw_cards WHERE call_id=$1", call_id
        )
        if guid_row and guid_row["ai_guidance"]:
            try:
                guid_data = guid_row["ai_guidance"]
                # asyncpg는 JSONB를 dict로 반환하지만 혹시 str인 경우 대비
                if isinstance(guid_data, str):
                    import json as _json
                    guid_data = _json.loads(guid_data)
                ai_guidance = AiGuidance(**guid_data)
            except Exception:
                pass

    return AcwInitResponse(
        acw_id=row["acw_id"],
        transcript=transcript or None,
        ai_guidance=ai_guidance,
        acw_started_at=row["acw_started_at"],
    )


@router.post("/{call_id}/generate", response_model=AcwGenerateResponse)
async def acw_generate(
    call_id: int,
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    acw_row = await conn.fetchrow(
        "SELECT acw_id, transcript FROM acw_cards WHERE call_id=$1 AND agent_id=$2",
        call_id, agent_id,
    )
    if not acw_row:
        raise HTTPException(status_code=404, detail="ACW 카드를 찾을 수 없습니다.")

    session = get_session(call_id)
    ai_guidance_dict = session.ai_guidance if session else None

    from app.services.acw_service import generate_acw_fields
    result = await generate_acw_fields(acw_row["transcript"], ai_guidance_dict)
    return result


@router.put("/{call_id}", response_model=AcwSaveResponse)
async def acw_save(
    call_id: int,
    body: AcwSaveRequest,
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    ai_guid_json = body.ai_guidance.model_dump() if body.ai_guidance else None
    qa_json = [item.model_dump() for item in body.qa_summary]

    # q_embedding 생성 (실패 시 None)
    # asyncpg vector 타입은 "[x,y,z,...]" 문자열 형식 필요
    q_embedding = None
    if body.qa_summary:
        try:
            from app.services.acw_service import embed_text
            vec = await embed_text(body.qa_summary[0].q)
            q_embedding = "[" + ",".join(map(str, vec)) + "]"
        except Exception:
            pass

    row = await conn.fetchrow(
        """
        UPDATE acw_cards
        SET title               = $3,
            customer_type       = $4,
            customer_type_custom = $5,
            category            = $6,
            category_major      = $7,
            category_mid        = $8,
            category_mid_list   = $9::jsonb,
            category_mid_custom = $10,
            disease_name        = $11,
            qa_summary          = $12::jsonb,
            ai_response_summary = $13,
            is_transferred      = $14,
            transfer_target     = $15,
            keywords            = $16::jsonb,
            ai_guidance         = $17::jsonb,
            is_resolved         = $18,
            agent_used_ai       = $19,
            satisfaction        = $20,
            agent_memo          = $21,
            q_embedding         = $22,
            acw_ended_at        = NOW(),
            acw_duration_sec    = EXTRACT(EPOCH FROM (NOW() - acw_started_at))::INT
        WHERE call_id=$1 AND agent_id=$2
        RETURNING acw_id, call_id, acw_ended_at, acw_duration_sec
        """,
        call_id, agent_id,
        body.title, body.customer_type, body.customer_type_custom,
        body.category, body.category_major, body.category_mid,
        json.dumps(body.category_mid_list, ensure_ascii=False),
        body.category_mid_custom, body.disease_name,
        json.dumps(qa_json, ensure_ascii=False),
        body.ai_response_summary, body.is_transferred, body.transfer_target,
        json.dumps(body.keywords, ensure_ascii=False),
        json.dumps(ai_guid_json, ensure_ascii=False) if ai_guid_json else None,
        body.is_resolved, body.agent_used_ai, body.satisfaction, body.agent_memo,
        q_embedding,
    )
    if not row:
        raise HTTPException(status_code=404, detail="ACW 카드를 찾을 수 없습니다.")

    # calls 상태 ended로 변경
    await conn.execute(
        "UPDATE calls SET status='ended' WHERE call_id=$1", call_id
    )

    return AcwSaveResponse(**dict(row))


@router.get("/{call_id}", response_model=dict)
async def get_acw(
    call_id: int,
    agent_id: int = Depends(get_current_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    row = await conn.fetchrow(
        "SELECT * FROM acw_cards WHERE call_id=$1 AND agent_id=$2",
        call_id, agent_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="ACW 카드를 찾을 수 없습니다.")
    return dict(row)

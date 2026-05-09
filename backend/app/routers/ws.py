"""
WebSocket 라우터
WS /ws/call/{call_id}?token={access_token}

현재: 텍스트 수신 → conversation_history 누적 → 파이프라인 stub
STT(voice.py)는 별도 단계에서 연결
"""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status

from app.core.security import decode_token
from app.services.pipeline.session import create_session, get_session, close_session

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/call/{call_id}")
async def call_websocket(
    call_id: int,
    websocket: WebSocket,
    token: str = Query(...),
):
    # JWT 검증
    try:
        agent_id = decode_token(token)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    session = create_session(call_id, agent_id)
    print(f"[WS] 연결: call_id={call_id}, agent_id={agent_id}")

    try:
        while True:
            data = await websocket.receive()

            # binary frame: 오디오 (STT 연결 전 무시)
            if "bytes" in data:
                continue

            # text frame: {"speaker": "고객"|"상담사", "text": "..."}
            if "text" in data:
                try:
                    msg = json.loads(data["text"])
                except json.JSONDecodeError:
                    continue

                speaker = msg.get("speaker", "고객")
                text = msg.get("text", "").strip()
                if not text:
                    continue

                timestamp = datetime.now(timezone.utc).isoformat()
                turn = {"speaker": speaker, "text": text, "timestamp": timestamp}
                session.conversation_history.append(turn)

                # conversation_update push
                await websocket.send_text(json.dumps({
                    "type": "conversation_update",
                    "speaker": speaker,
                    "text": text,
                    "timestamp": timestamp,
                }, ensure_ascii=False))

                # 고객 발화일 때만 파이프라인 트리거
                if speaker == "고객":
                    await _run_pipeline(call_id, session, websocket)

    except WebSocketDisconnect:
        print(f"[WS] 종료: call_id={call_id}")
        # 세션은 유지 (PATCH /end 호출 시 DB 저장)


async def _run_pipeline(call_id: int, session, websocket: WebSocket):
    """RTL 파이프라인 실행 (STEP1 → STEP2 병렬 → STEP3)"""
    await websocket.send_text(json.dumps({"type": "ai_update", "status": "loading"}))

    try:
        from app.services.pipeline.step1_llm import run_step1
        from app.services.pipeline.step2_search import run_step2
        from app.services.pipeline.step3_llm import run_step3

        # STEP 1: ready 판정 + OOS 분류
        step1 = await run_step1(session.conversation_history)

        if not step1["ready"]:
            return  # 발화 더 필요

        if step1["is_oos"]:
            session.ai_guidance = {
                "is_oos": True,
                "oos_type": step1.get("oos_type"),
                "oos_reason": step1.get("oos_reason"),
                "query": step1.get("query"),
                "disease_name": step1.get("disease_name"),
                "answer": None,
                "sources": [],
            }
            await websocket.send_text(json.dumps({
                "type": "ai_update",
                "status": "oos",
                "oos_type": step1.get("oos_type"),
                "oos_reason": step1.get("oos_reason"),
            }, ensure_ascii=False))
            return

        query = step1.get("query", "")
        disease_name = step1.get("disease_name")

        # STEP 2: 병렬 벡터 검색
        step2 = await run_step2(query, disease_name, call_id)

        # 2B similar_cases 즉시 push
        if step2.get("similar_cases"):
            await websocket.send_text(json.dumps({
                "type": "similar_cases",
                "data": step2["similar_cases"],
            }, ensure_ascii=False))

        # 2C transfer_suggestion 즉시 push
        if step2.get("transfer_suggestions"):
            await websocket.send_text(json.dumps({
                "type": "transfer_suggestion",
                "data": step2["transfer_suggestions"],
            }, ensure_ascii=False))

        # 2A 결과 없음
        if not step2.get("knowledge_chunks"):
            await websocket.send_text(json.dumps({
                "type": "ai_update",
                "status": "no_result",
                "query": query,
            }, ensure_ascii=False))
            return

        # STEP 3: AI 안내 생성
        answer, sources = await run_step3(
            query, disease_name, step2["knowledge_chunks"], session.conversation_history
        )

        session.ai_guidance = {
            "query": query,
            "disease_name": disease_name,
            "is_oos": False,
            "oos_type": None,
            "oos_reason": None,
            "answer": answer,
            "sources": sources,
        }

        await websocket.send_text(json.dumps({
            "type": "ai_update",
            "status": "success",
            "query": query,
            "disease_name": disease_name,
            "answer": answer,
            "sources": sources,
        }, ensure_ascii=False))

    except Exception as e:
        print(f"[Pipeline 오류] {e}")
        await websocket.send_text(json.dumps({"type": "ai_update", "status": "error"}))

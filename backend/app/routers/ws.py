"""
WebSocket 라우터
WS /ws/call/{call_id}?token={access_token}

파이프라인:
  발화 수신
  → STEP 1 (llm_session): READY 판정 + 카테고리 분류
  → STEP 2A (retrieval):  pgvector Hybrid 검색 (knowledge_chunks)
    STEP 2B (step2):      acw_cards 유사사례 검색  ┐ 병렬
    STEP 2C (step2):      transfer_agencies 검색   ┘
  → STEP 3 (card_generator): 상담사 카드 생성
"""
import asyncio
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

            if "bytes" in data:
                continue

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

                await websocket.send_text(json.dumps({
                    "type": "conversation_update",
                    "speaker": speaker,
                    "text": text,
                    "timestamp": timestamp,
                }, ensure_ascii=False))

                # 모든 발화를 LLMSession에 전달 (상담사 발화는 컨텍스트 누적만)
                try:
                    llm_result = await session.llm_session.on_utterance(text, speaker)
                except Exception as e:
                    print(f"[LLM 오류] {e}")
                    llm_result = None
                if llm_result:
                    await _run_pipeline(call_id, session, websocket, llm_result)

    except WebSocketDisconnect:
        print(f"[WS] 종료: call_id={call_id}")


async def _run_pipeline(call_id: int, session, websocket: WebSocket, llm_result: dict):
    """STEP 2A/B/C 병렬 → STEP 3"""
    from app.services.pipeline.retrieval import retrieve_knowledge
    from app.services.pipeline.card_generator import generate_card
    from app.services.pipeline.step2_search import _search_acw, _search_transfer, _embed
    from app.core.database import get_pool

    await websocket.send_text(json.dumps({"type": "ai_update", "status": "loading"}))

    try:
        category      = llm_result["category"]
        refined_query = llm_result["query"]
        query_vec     = llm_result["_query_vec"]   # llm_session에서 이미 생성된 벡터
        disease_name  = llm_result.get("disease_name")  # 감염병일 때만 존재

        # 범위외: 카드만 생성하고 종료
        if category == "범위외":
            card = await generate_card(refined_query, "범위외", {"results": [], "_disease_filter": None})
            session.ai_guidance = _build_guidance(refined_query, card, [], [], is_oos=True)
            await websocket.send_text(json.dumps({
                "type": "ai_update",
                "status": "oos",
                "oos_type": "unrelated",
                "query": refined_query,
                "intent": card["intent"],
                "answer": card["answer"],
            }, ensure_ascii=False))
            return

        pool = await get_pool()
        vec_list = query_vec.tolist()

        # STEP 2: 병렬 실행
        #   2A: knowledge_chunks Hybrid 검색
        #   2B: acw_cards 유사사례
        #   2C: transfer_agencies
        results = await asyncio.gather(
            retrieve_knowledge(query_vec, refined_query, category, disease_name=disease_name),
            _search_acw(pool, vec_list),
            _search_transfer(pool, vec_list),
            return_exceptions=True,
        )

        retrieval      = results[0] if not isinstance(results[0], Exception) else {"results": [], "_disease_filter": None}
        similar_cases  = results[1] if not isinstance(results[1], Exception) else []
        transfer_suggs = results[2] if not isinstance(results[2], Exception) else []

        # 유사사례 즉시 push
        if similar_cases:
            await websocket.send_text(json.dumps({
                "type": "similar_cases",
                "data": similar_cases,
            }, ensure_ascii=False))

        # 이관기관 즉시 push
        if transfer_suggs:
            await websocket.send_text(json.dumps({
                "type": "transfer_suggestion",
                "data": transfer_suggs,
            }, ensure_ascii=False))

        # STEP 3: 카드 생성
        card = await generate_card(refined_query, category, retrieval)

        session.ai_guidance = _build_guidance(
            refined_query, card, similar_cases, transfer_suggs, is_oos=False
        )

        await websocket.send_text(json.dumps({
            "type":         "ai_update",
            "status":       "success",
            "query":        refined_query,
            "category":     card["category"],
            "intent":       card["intent"],
            "answer":       card["answer"],
            "references":   card["references"],
            "disease_name": retrieval.get("_disease_filter"),
            **({"emergency": True} if card.get("emergency") else {}),
        }, ensure_ascii=False))

    except Exception as e:
        print(f"[Pipeline 오류] {e}")
        await websocket.send_text(json.dumps({"type": "ai_update", "status": "error"}))


def _build_guidance(query: str, card: dict, similar: list, transfer: list, is_oos: bool) -> dict:
    return {
        "query":        query,
        "disease_name": card.get("_disease_filter"),
        "is_oos":       is_oos,
        "oos_type":     "unrelated" if is_oos else None,
        "oos_reason":   card.get("answer") if is_oos else None,
        "answer":       card.get("answer") if not is_oos else None,
        "sources":      card.get("references", []),
    }

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

# call_id → 연결된 WebSocket 집합 (브로드캐스트용)
_connections: dict[int, set[WebSocket]] = {}


async def _broadcast(call_id: int, message: str):
    """call_id에 연결된 모든 클라이언트에 메시지 전송"""
    targets = _connections.get(call_id, set())
    dead = set()
    for ws in targets:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    for ws in dead:
        targets.discard(ws)


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

    # 연결 등록
    if call_id not in _connections:
        _connections[call_id] = set()
    _connections[call_id].add(websocket)

    # 세션은 call_id당 하나만 유지 (이미 있으면 재사용)
    session = get_session(call_id) or create_session(call_id, agent_id)
    print(f"[WS] 연결: call_id={call_id}, agent_id={agent_id}, 연결수={len(_connections[call_id])}")

    try:
        while True:
            data = await websocket.receive()

            # 클라이언트 연결 종료 감지
            if data.get("type") == "websocket.disconnect":
                break

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

                # 모든 연결에 대화 업데이트 브로드캐스트
                await _broadcast(call_id, json.dumps({
                    "type": "conversation_update",
                    "speaker": speaker,
                    "text": text,
                    "timestamp": timestamp,
                }, ensure_ascii=False))

                # 고객 발화만 LLM 파이프라인 실행
                if speaker != "상담사":
                    try:
                        llm_result = await session.llm_session.on_utterance(text, speaker)
                    except Exception as e:
                        print(f"[LLM 오류] {e}")
                        llm_result = None
                    if llm_result:
                        await _run_pipeline(call_id, session, llm_result)

    except WebSocketDisconnect:
        print(f"[WS] 종료: call_id={call_id}")
    except RuntimeError as e:
        print(f"[WS] 연결 오류: call_id={call_id}, {e}")
    finally:
        _connections.get(call_id, set()).discard(websocket)
        if not _connections.get(call_id):
            _connections.pop(call_id, None)
            close_session(call_id)
        print(f"[WS] 세션 정리: call_id={call_id}")


async def _run_pipeline(call_id: int, session, llm_result: dict):
    """STEP 2A/B/C 병렬 → STEP 3"""
    from app.services.pipeline.card_generator import generate_card
    from app.services.pipeline.step2_search import _search_knowledge, _search_acw, _search_transfer
    from app.core.database import get_pool

    await _broadcast(call_id, json.dumps({"type": "ai_update", "status": "loading"}))

    try:
        is_oos        = llm_result["is_oos"]
        oos_type      = llm_result.get("oos_type")
        oos_reason    = llm_result.get("oos_reason")
        category      = llm_result["category"]
        refined_query = llm_result["query"]
        query_vec     = llm_result["_query_vec"]   # llm_session에서 이미 생성된 벡터
        disease_name  = llm_result.get("disease_name")

        pool = await get_pool()
        vec_list = query_vec.tolist()

        # STEP 2: 병렬 실행
        #   2A: knowledge_chunks DB 검색 (is_oos=false 시에만)
        #   2B: acw_cards 유사사례
        #   2C: transfer_agencies
        if is_oos:
            knowledge_task = asyncio.sleep(0)  # 스킵
        else:
            knowledge_task = _search_knowledge(pool, vec_list, disease_name)

        results = await asyncio.gather(
            knowledge_task,
            _search_acw(pool, vec_list),
            _search_transfer(pool, vec_list),
            return_exceptions=True,
        )

        knowledge_chunks = (results[0] if not isinstance(results[0], Exception) else []) if not is_oos else []
        similar_cases    = results[1] if not isinstance(results[1], Exception) else []
        transfer_suggs   = results[2] if not isinstance(results[2], Exception) else []

        # generate_card가 기대하는 retrieval 구조로 변환
        retrieval = {
            "step2a":          knowledge_chunks,
            "_disease_filter": disease_name if knowledge_chunks else None,
        }

        # 유사사례 즉시 push
        if similar_cases:
            await _broadcast(call_id, json.dumps({
                "type": "similar_cases",
                "data": similar_cases,
            }, ensure_ascii=False))

        # 이관기관 즉시 push
        if transfer_suggs:
            await _broadcast(call_id, json.dumps({
                "type": "transfer_suggestion",
                "data": transfer_suggs,
            }, ensure_ascii=False))

        # STEP 3: 카드 생성
        card = await generate_card(refined_query, is_oos, oos_type, oos_reason, disease_name, retrieval)

        session.ai_guidance = _build_guidance(refined_query, card, similar_cases, transfer_suggs)

        card_status = card.get("status", "error")

        if card_status == "oos":
            await _broadcast(call_id, json.dumps({
                "type":     "ai_update",
                "status":   "oos",
                "oos_type": card.get("oos_type"),
                "query":    refined_query,
                "answer":   card.get("oos_reason"),
                **({"emergency": True} if card.get("emergency") else {}),
            }, ensure_ascii=False))

        elif card_status == "success":
            await _broadcast(call_id, json.dumps({
                "type":         "ai_update",
                "status":       "success",
                "query":        refined_query,
                "category":     category,
                "answer":       card.get("answer"),
                "references":   card.get("sources", []),
                "disease_name": retrieval.get("_disease_filter"),
                **({"emergency": True} if card.get("emergency") else {}),
            }, ensure_ascii=False))

        else:  # no_result
            await _broadcast(call_id, json.dumps({
                "type":     "ai_update",
                "status":   "no_result",
                "query":    refined_query,
                "category": category,
            }, ensure_ascii=False))

    except Exception as e:
        print(f"[Pipeline 오류] {e}")
        import traceback
        traceback.print_exc()
        await _broadcast(call_id, json.dumps({"type": "ai_update", "status": "error"}))


def _build_guidance(query: str, card: dict, similar: list, transfer: list) -> dict:
    status = card.get("status")
    return {
        "query":        query,
        "status":       status,
        "is_oos":       status == "oos",
        "oos_type":     card.get("oos_type"),
        "oos_reason":   card.get("oos_reason"),
        "disease_name": card.get("disease_name"),
        "answer":       card.get("answer") if status == "success" else None,
        "sources":      card.get("sources", []),
    }

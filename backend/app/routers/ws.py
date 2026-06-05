"""
WebSocket 라우터
WS /ws/call/{call_id}?token={access_token}

파이프라인:
  발화 수신
  → STEP 1 (llm_session): READY 판정 + 카테고리 분류
  → STEP 2A (retrieval):  Hybrid RAG 검색 (in-memory BM25+Dense+Rerank)
    STEP 2B (step2_search): acw_cards 유사사례 검색  ┐ 병렬 (DB)
    STEP 2C (step2_search): transfer_agencies 검색   ┘
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

                await _broadcast(call_id, json.dumps({
                    "type": "conversation_update",
                    "speaker": speaker,
                    "text": text,
                    "timestamp": timestamp,
                }, ensure_ascii=False))

                # 모든 발화를 LLMSession에 전달 (상담사 발화는 컨텍스트 누적만, LLM 호출 없음)
                try:
                    llm_result = await session.llm_session.on_utterance(text, speaker)
                except Exception as e:
                    print(f"[LLM 오류] {e}")
                    llm_result = None
                if llm_result:
                    await _run_pipeline(call_id, session, llm_result)

    except WebSocketDisconnect:
        pass
    except RuntimeError as e:
        print(f"[WS] 연결 오류: call_id={call_id}, {e}")
    finally:
        _connections.get(call_id, set()).discard(websocket)
        if not _connections.get(call_id):
            _connections.pop(call_id, None)
            close_session(call_id)
        print(f"[WS] 종료: call_id={call_id}, 남은연결={len(_connections.get(call_id, set()))}")


async def _run_pipeline(call_id: int, session, llm_result: dict):
    """STEP 2A (Hybrid RAG) + 2B/2C (DB) 병렬 → STEP 3"""
    from app.services.pipeline.retrieval import retrieve_all
    from app.services.pipeline.card_generator import generate_card
    from app.services.pipeline.step2_search import _search_acw, _search_transfer
    from app.core.database import get_pool

    await _broadcast(call_id, json.dumps({"type": "ai_update", "status": "loading"}))

    try:
        category     = llm_result["category"]
        query        = llm_result["query"]
        query_vec    = llm_result["_query_vec"]
        disease_name = llm_result.get("disease_name")
        is_oos       = llm_result.get("is_oos", False)
        oos_type     = llm_result.get("oos_type")
        oos_reason   = llm_result.get("oos_reason")

        pool = await get_pool()
        vec_list = query_vec.tolist()

        # STEP 2: 병렬 실행
        #   2A: Hybrid RAG in-memory (is_oos=false 시에만)
        #   2B: acw_cards DB 검색
        #   2C: transfer_agencies DB 검색
        empty_retrieval = {"step2a": [], "step2b": [], "step2c": [], "_disease_filter": None}

        _API_PENDING = {"예방접종", "감염병 통계·현황", "해외/검역 정보 문의"}
        skip_rag = is_oos or (category in _API_PENDING) or (not disease_name)

        if skip_rag:
            knowledge_task = asyncio.sleep(0)
        else:
            knowledge_task = retrieve_all(
                query, is_oos=False, disease_name=disease_name, query_vec=query_vec
            )

        # 유사상담 검색 비활성화 (항상 스킵)
        results = await asyncio.gather(
            knowledge_task,
            asyncio.sleep(0),
            _search_transfer(pool, vec_list, query_text=query,
                             keyword_only=not (is_oos and oos_type == "transfer")),
            return_exceptions=True,
        )

        retrieval      = empty_retrieval if skip_rag else (results[0] if not isinstance(results[0], Exception) else empty_retrieval)
        similar_cases  = []
        transfer_suggs = results[2] if not isinstance(results[2], Exception) else []

        # 이관기관 즉시 push
        if transfer_suggs:
            await _broadcast(call_id, json.dumps({
                "type": "transfer_suggestion",
                "data": transfer_suggs,
            }, ensure_ascii=False))

        # STEP 3: 카드 생성
        card = await generate_card(
            query, is_oos, oos_type, oos_reason, disease_name, retrieval, category=category
        )

        # no_result 시 이관카드 강제 표시 (키워드 미매칭이어도 임베딩 검색으로 보완)
        if card.get("status") == "no_result" and not transfer_suggs:
            try:
                fallback_transfer = await _search_transfer(pool, vec_list, query_text=query, keyword_only=False)
                if fallback_transfer:
                    transfer_suggs = fallback_transfer
                    await _broadcast(call_id, json.dumps({
                        "type": "transfer_suggestion",
                        "data": transfer_suggs,
                    }, ensure_ascii=False))
            except Exception as e:
                print(f"[no_result 이관 폴백 오류] {e}")

        session.ai_guidance = _build_guidance(query, card, similar_cases, transfer_suggs)

        card_status = card.get("status", "error")

        if card_status == "oos":
            await _broadcast(call_id, json.dumps({
                "type":     "ai_update",
                "status":   "oos",
                "oos_type": oos_type,
                "query":    query,
                "answer":   card.get("oos_reason", ""),
                **({"emergency": True} if card.get("emergency") else {}),
            }, ensure_ascii=False))

        elif card_status == "api_pending":
            await _broadcast(call_id, json.dumps({
                "type":     "ai_update",
                "status":   "api_pending",
                "category": category,
                "query":    query,
                **({"emergency": True} if card.get("emergency") else {}),
            }, ensure_ascii=False))

        elif card_status == "success":
            await _broadcast(call_id, json.dumps({
                "type":         "ai_update",
                "status":       "success",
                "query":        query,
                "category":     category,
                "intent":       card.get("intent", ""),
                "answer":       card.get("answer", ""),
                "references":   card.get("sources", []),
                "disease_name": retrieval.get("_disease_filter"),
                **({"emergency": True} if card.get("emergency") else {}),
            }, ensure_ascii=False))

        else:  # no_result
            await _broadcast(call_id, json.dumps({
                "type":     "ai_update",
                "status":   "no_result",
                "query":    query,
                "category": category,
                "message":  card.get("message"),
            }, ensure_ascii=False))

    except Exception as e:
        import traceback
        print(f"[Pipeline 오류] {e}")
        traceback.print_exc()
        await _broadcast(call_id, json.dumps({"type": "ai_update", "status": "error"}))


def _build_guidance(query: str, card: dict, similar: list, transfer: list) -> dict:
    card_status = card.get("status")
    return {
        "query":        query,
        "status":       card_status,
        "is_oos":       card_status == "oos",
        "oos_type":     card.get("oos_type"),
        "oos_reason":   card.get("oos_reason"),
        "disease_name": card.get("disease_name"),
        "answer":       card.get("answer") if card_status == "success" else None,
        "sources":      card.get("sources", []),
    }

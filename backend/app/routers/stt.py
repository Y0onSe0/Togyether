"""
STT WebSocket 프록시
WS /ws/stt/{call_id}?token={access_token}

브라우저에서 16kHz 16bit PCM 오디오를 받아서
GPU 서버 STT(ws://210.94.179.19:8765)로 중계하고
결과를 기존 call WebSocket 채널에 브로드캐스트 + LLM 파이프라인 실행
"""

import asyncio
import json
from datetime import datetime, timezone

import websockets as ws_lib
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status

from app.core.security import decode_token
from app.services.pipeline.session import get_session, create_session

router = APIRouter(tags=["stt"])

STT_SERVER_URI = "ws://127.0.0.1:8765"


@router.websocket("/ws/stt/{call_id}")
async def stt_proxy(
    call_id: int,
    websocket: WebSocket,
    token: str = Query(...),
):
    # 토큰 검증
    try:
        agent_id = decode_token(token)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    # 기존 세션 재사용 (없으면 새로 생성)
    session = get_session(call_id) or create_session(call_id, agent_id)
    print(f"[STT] 브라우저 연결됨: call_id={call_id}, agent_id={agent_id}")

    try:
        async with ws_lib.connect(STT_SERVER_URI) as stt_ws:
            print(f"[STT] GPU 서버 연결됨: {STT_SERVER_URI}")

            async def relay_audio():
                """브라우저 PCM 오디오 → STT 서버"""
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("type") == "websocket.disconnect":
                            print("[STT] 브라우저 연결 종료")
                            break
                        raw = msg.get("bytes")
                        if raw:
                            await stt_ws.send(raw)
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    print(f"[STT relay_audio 종료] {e}")

            async def relay_result():
                """STT 결과 → 기존 call 채널 브로드캐스트 + LLM 파이프라인

                V3 형식: { speaker, text, timestamp }
                V9 형식: { speaker, text, segments: [{speaker, text, start, end}], timestamp, stt_elapsed }
                  → segments가 있으면 각 세그먼트를 개별 발화로 브로드캐스트
                """
                from app.routers.ws import _broadcast, _run_pipeline

                try:
                    async for raw in stt_ws:
                        try:
                            result = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        stt_time = result.get("timestamp", "")
                        segments = result.get("segments")  # V9 전용 필드

                        # V9: segments 배열로 각 화자 발화를 개별 처리
                        # V3: segments 없음 → 최상위 speaker/text 단일 처리
                        if segments:
                            utterances = [
                                {"speaker": seg.get("speaker", "고객"),
                                 "text":    seg.get("text", "").strip()}
                                for seg in segments
                                if seg.get("text", "").strip()
                            ]
                        else:
                            speaker = result.get("speaker", "고객")
                            text    = result.get("text", "").strip()
                            utterances = [{"speaker": speaker, "text": text}] if text else []

                        if not utterances:
                            continue

                        timestamp = datetime.now(timezone.utc).isoformat()

                        for utt in utterances:
                            speaker = utt["speaker"]
                            text    = utt["text"]

                            # 대화 히스토리 기록
                            session.conversation_history.append({
                                "speaker":   speaker,
                                "text":      text,
                                "timestamp": timestamp,
                            })

                            # 기존 /ws/call/{call_id} 연결 전체에 브로드캐스트
                            msg = json.dumps({
                                "type":      "conversation_update",
                                "speaker":   speaker,
                                "text":      text,
                                "timestamp": timestamp,
                                "stt_time":  stt_time,
                            }, ensure_ascii=False)

                            await _broadcast(call_id, msg)
                            print(f"[STT] [{speaker}] {text}")

                            # 고객 발화 → LLM 파이프라인 실행
                            if speaker == "고객":
                                try:
                                    llm_result = await session.llm_session.on_utterance(text, speaker)
                                    if llm_result:
                                        await _run_pipeline(call_id, session, llm_result)
                                except Exception as e:
                                    print(f"[STT Pipeline 오류] {e}")

                except Exception as e:
                    print(f"[STT relay_result 종료] {e}")

            # 오디오 중계 + 결과 수신 병렬 실행
            await asyncio.gather(relay_audio(), relay_result())

    except Exception as e:
        print(f"[STT Proxy 오류] {e}")
    finally:
        print(f"[STT] 연결 종료: call_id={call_id}")

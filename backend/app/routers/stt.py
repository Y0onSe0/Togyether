"""
STT WebSocket 프록시 (Deepgram 버전)
WS /ws/stt/{call_id}?token={access_token}

브라우저에서 16kHz 16bit PCM 오디오를 받아서
Deepgram Nova-2 API로 스트리밍 전송 후
결과를 기존 call WebSocket 채널에 브로드캐스트 + LLM 파이프라인 실행

Deepgram 응답:
  - is_final=true일 때만 처리
  - speaker 필드로 화자 분리 (0=첫번째 화자, 1=두번째 화자...)
  - 첫 번째 화자 = 상담사, 이후 = 고객 (추정)
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

# 평가 로그 저장 여부 (환경변수로 제어)
EVAL_MODE = os.getenv("STT_EVAL_MODE", "0") == "1"
EVAL_LOG_DIR = Path("eval_logs")

from websockets.legacy.client import connect as ws_connect
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status

from app.core.config import settings
from app.core.security import decode_token
from app.services.pipeline.session import get_session, create_session

router = APIRouter(tags=["stt"])

DEEPGRAM_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-3"
    "&language=ko"
    "&diarize=true"
    "&encoding=linear16"
    "&sample_rate=16000"
    "&channels=1"
    "&interim_results=true"
)

# 한글 숫자 → 아라비아 숫자 변환
KO_DIGIT = {"영":0,"공":0,"일":1,"이":2,"삼":3,"사":4,"오":5,"육":6,"칠":7,"팔":8,"구":9}
KO_UNIT  = {"십":10,"백":100,"천":1000,"만":10000}
KO_NUM   = {**KO_DIGIT, **KO_UNIT}

def _ko_to_int(tokens: list) -> int:
    """['이', '십', '일'] → 21"""
    total = 0
    current = 0  # 현재 자릿수 누적
    last_digit = 0  # 마지막 단일 숫자

    for t in tokens:
        if t in KO_DIGIT:
            last_digit = KO_DIGIT[t]
        elif t in KO_UNIT:
            unit = KO_UNIT[t]
            if unit == 10000:
                total += (current + last_digit) * unit
                current = 0
                last_digit = 0
            else:
                current += (last_digit if last_digit > 0 else 1) * unit
                last_digit = 0

    return total + current + last_digit


def _normalize_numbers(text: str) -> str:
    """공백 구분된 한글 숫자를 아라비아 숫자로 변환
    예: '이 십 일 시' → '21 시'
    """
    tokens = text.split()
    result = []
    i = 0
    while i < len(tokens):
        if tokens[i] in KO_NUM:
            num_tokens = []
            while i < len(tokens) and tokens[i] in KO_NUM:
                num_tokens.append(tokens[i])
                i += 1
            result.append(str(_ko_to_int(num_tokens)))
        else:
            result.append(tokens[i])
            i += 1
    return " ".join(result)


def _map_speaker(speaker_idx: int, first_speaker: dict) -> str:
    """
    Deepgram speaker 인덱스 → 상담사/고객 매핑
    첫 번째로 말한 화자 = 상담사 (콜센터 특성상)
    """
    if first_speaker.get("idx") is None:
        first_speaker["idx"] = speaker_idx
    return "상담사" if speaker_idx == first_speaker["idx"] else "고객"


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

    session = get_session(call_id) or create_session(call_id, agent_id)
    print(f"[STT] 브라우저 연결됨: call_id={call_id}, agent_id={agent_id}")

    # 평가 모드: 로그 파일 초기화
    eval_log_path = None
    if EVAL_MODE:
        EVAL_LOG_DIR.mkdir(exist_ok=True)
        eval_log_path = EVAL_LOG_DIR / f"call_{call_id}.jsonl"
        print(f"[STT 평가모드] 로그 저장: {eval_log_path}")

    last_audio_send_time: dict = {"t": None}  # 마지막 오디오 전송 시각

    try:
        async with ws_connect(
            DEEPGRAM_URL,
            extra_headers={"Authorization": f"Token {settings.DEEPGRAM_API_KEY}"},
            open_timeout=10,
        ) as dg_ws:
            print(f"[STT] Deepgram 연결됨")
            first_speaker: dict = {"idx": None}

            async def relay_audio():
                """브라우저 PCM → Deepgram"""
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        raw = msg.get("bytes")
                        if raw:
                            last_audio_send_time["t"] = time.time()
                            await dg_ws.send(raw)
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    print(f"[STT relay_audio 종료] {e}")
                finally:
                    # Deepgram에 스트림 종료 신호
                    try:
                        await dg_ws.send(json.dumps({"type": "CloseStream"}))
                    except Exception:
                        pass

            async def relay_result():
                """Deepgram 결과 → call 채널 브로드캐스트 + LLM 파이프라인"""
                from app.routers.ws import _broadcast, _run_pipeline

                try:
                    async for raw in dg_ws:
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        # is_final=true인 결과만 처리
                        if data.get("type") != "Results":
                            continue
                        if not data.get("is_final"):
                            continue

                        channel = data.get("channel", {})
                        alternatives = channel.get("alternatives", [])
                        if not alternatives:
                            continue

                        transcript = alternatives[0].get("transcript", "").strip()
                        if not transcript:
                            continue

                        words = alternatives[0].get("words", [])
                        timestamp = datetime.now(timezone.utc).isoformat()

                        # 화자 분리: words 단위로 speaker 변경 감지
                        if words:
                            # speaker별로 텍스트 그룹핑
                            utterances = []
                            cur_speaker = words[0].get("speaker", 0)
                            cur_words = []

                            for w in words:
                                spk = w.get("speaker", cur_speaker)
                                if spk != cur_speaker:
                                    if cur_words:
                                        utterances.append({
                                            "speaker": _map_speaker(cur_speaker, first_speaker),
                                            "text": " ".join(cur_words).strip(),
                                        })
                                    cur_speaker = spk
                                    cur_words = []
                                cur_words.append(w.get("punctuated_word") or w.get("word", ""))

                            if cur_words:
                                utterances.append({
                                    "speaker": _map_speaker(cur_speaker, first_speaker),
                                    "text": " ".join(cur_words).strip(),
                                })
                        else:
                            # words 없으면 전체 transcript 단일 발화
                            utterances = [{"speaker": "고객", "text": transcript}]

                        for utt in utterances:
                            speaker = utt["speaker"]
                            text    = _normalize_numbers(utt["text"])  # 숫자 정규화
                            if not text:
                                continue

                            session.conversation_history.append({
                                "speaker":   speaker,
                                "text":      text,
                                "timestamp": timestamp,
                            })

                            msg = json.dumps({
                                "type":      "conversation_update",
                                "speaker":   speaker,
                                "text":      text,
                                "timestamp": timestamp,
                            }, ensure_ascii=False)

                            await _broadcast(call_id, msg)
                            print(f"[STT] [{speaker}] {text}")

                            # latency 계산 (마지막 오디오 전송 → 전사 수신)
                            latency_ms = None
                            if last_audio_send_time["t"]:
                                latency_ms = round((time.time() - last_audio_send_time["t"]) * 1000)

                            # 평가 모드: 전사 결과 로그 저장
                            if EVAL_MODE and eval_log_path:
                                with open(eval_log_path, "a", encoding="utf-8") as f:
                                    f.write(json.dumps({
                                        "speaker":    speaker,
                                        "text":       text,
                                        "timestamp":  timestamp,
                                        "latency_ms": latency_ms,
                                    }, ensure_ascii=False) + "\n")
                            if latency_ms:
                                print(f"[STT] [{speaker}] {text} ({latency_ms}ms)")

                            if speaker == "고객":
                                try:
                                    llm_result = await session.llm_session.on_utterance(text, speaker)
                                    if llm_result:
                                        await _run_pipeline(call_id, session, llm_result)
                                except Exception as e:
                                    print(f"[STT Pipeline 오류] {e}")

                except Exception as e:
                    print(f"[STT relay_result 종료] {e}")

            await asyncio.gather(relay_audio(), relay_result())

    except Exception as e:
        print(f"[STT Proxy 오류] {e}")
    finally:
        print(f"[STT] 연결 종료: call_id={call_id}")

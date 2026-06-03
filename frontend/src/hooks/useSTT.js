/**
 * useSTT.js
 * 마이크 오디오를 16kHz 16bit PCM으로 캡처해서
 * /ws/stt/{callId} WebSocket으로 스트리밍
 *
 * STT 결과는 기존 /ws/call/{callId} 채널로 브로드캐스트되어
 * ChatPanel에 자동 표시됨 (별도 onTranscript 콜백 불필요)
 */

import { useRef, useState, useCallback } from 'react';

const getSTTUrl = (callId) => {
  const token = localStorage.getItem('access_token');
  return `ws://127.0.0.1:8000/ws/stt/${callId}?token=${token}`;
};

export const useSTT = (callId) => {
  const wsRef          = useRef(null);
  const audioCtxRef    = useRef(null);
  const processorRef   = useRef(null);
  const streamRef      = useRef(null);
  const isRecordingRef = useRef(false);  // 상태 대신 ref로 즉각 반영

  const [isRecording, setIsRecording] = useState(false);
  const [error, setError]             = useState(null);

  const start = useCallback(async () => {
    if (isRecordingRef.current || !callId) return;
    isRecordingRef.current = true;
    setError(null);

    try {
      /* 1. STT 프록시 WebSocket 연결 */
      const ws = new WebSocket(getSTTUrl(callId));
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      await new Promise((resolve, reject) => {
        ws.onopen  = resolve;
        ws.onerror = () => reject(new Error('STT 서버 연결 실패'));
        setTimeout(() => reject(new Error('STT 연결 시간 초과')), 6000);
      });

      /* 2. 마이크 접근 (sampleRate는 getUserMedia 미지원 → AudioContext에서 처리) */
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount:     1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      streamRef.current = stream;

      /* 3. AudioContext 16kHz 고정 */
      const audioCtx = new AudioContext({ sampleRate: 16000 });
      audioCtxRef.current = audioCtx;

      const source    = audioCtx.createMediaStreamSource(stream);
      // 4096 샘플 = 16kHz 기준 약 0.25초 단위로 처리
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        if (ws.readyState !== WebSocket.OPEN) return;

        const float32 = e.inputBuffer.getChannelData(0);

        /* Float32 → Int16 변환 (STT 서버가 16bit PCM 기대) */
        const int16 = new Int16Array(float32.length);
        for (let i = 0; i < float32.length; i++) {
          const clamped = Math.max(-1, Math.min(1, float32[i]));
          int16[i] = clamped < 0 ? clamped * 32768 : clamped * 32767;
        }
        ws.send(int16.buffer);
      };

      source.connect(processor);
      processor.connect(audioCtx.destination);

      setIsRecording(true);
      console.log('[STT] 녹음 시작 - call_id:', callId);

    } catch (err) {
      isRecordingRef.current = false;
      setIsRecording(false);
      setError(err.message);
      console.error('[STT 오류]', err);
      streamRef.current?.getTracks().forEach((t) => t.stop());
      audioCtxRef.current?.close();
      wsRef.current?.close();
    }
  }, [callId]);

  const stop = useCallback(() => {
    if (!isRecordingRef.current) return;
    isRecordingRef.current = false;

    processorRef.current?.disconnect();
    audioCtxRef.current?.close();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.close();
    }

    processorRef.current = null;
    audioCtxRef.current  = null;
    streamRef.current    = null;
    wsRef.current        = null;

    setIsRecording(false);
    console.log('[STT] 녹음 종료');
  }, []);

  return { isRecording, start, stop, error };
};

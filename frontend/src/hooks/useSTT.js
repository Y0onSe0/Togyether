/**
 * useSTT.js
 * single 모드: 마이크 단일 채널 → diarize
 * dual   모드: 마이크(ch0=상담사) + VB-Cable(ch1=고객) 스테레오 → multichannel
 */

import { useRef, useState, useCallback } from 'react';

const getSTTUrl = (callId, mode = 'single') => {
  const token = localStorage.getItem('access_token');
  return `ws://127.0.0.1:8000/ws/stt/${callId}?token=${token}&mode=${mode}`;
};

export const useSTT = (callId) => {
  const wsRef          = useRef(null);
  const audioCtxRef    = useRef(null);
  const processorRef   = useRef(null);
  const streamsRef     = useRef([]);
  const isRecordingRef = useRef(false);

  const [isRecording, setIsRecording] = useState(false);
  const [error, setError]             = useState(null);
  const [devices, setDevices]         = useState([]);   // 오디오 입력 장치 목록

  // 오디오 장치 목록 조회
  const loadDevices = useCallback(async () => {
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true }); // 권한 요청
      const all = await navigator.mediaDevices.enumerateDevices();
      const inputs = all.filter(d => d.kind === 'audioinput');
      setDevices(inputs);
      return inputs;
    } catch {
      return [];
    }
  }, []);

  const _cleanup = () => {
    processorRef.current?.disconnect();
    audioCtxRef.current?.close();
    streamsRef.current.forEach(s => s.getTracks().forEach(t => t.stop()));
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.close();
    processorRef.current = null;
    audioCtxRef.current  = null;
    streamsRef.current   = [];
    wsRef.current        = null;
  };

  // ── 싱글 모드 (기존) ──────────────────────────────────────────
  const start = useCallback(async () => {
    if (isRecordingRef.current || !callId) return;
    isRecordingRef.current = true;
    setError(null);

    try {
      const ws = new WebSocket(getSTTUrl(callId, 'single'));
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      await new Promise((resolve, reject) => {
        ws.onopen  = resolve;
        ws.onerror = () => reject(new Error('STT 서버 연결 실패'));
        setTimeout(() => reject(new Error('STT 연결 시간 초과')), 6000);
      });

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      streamsRef.current = [stream];

      const audioCtx = new AudioContext({ sampleRate: 16000 });
      audioCtxRef.current = audioCtx;

      const source    = audioCtx.createMediaStreamSource(stream);
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        if (ws.readyState !== WebSocket.OPEN) return;
        const float32 = e.inputBuffer.getChannelData(0);
        const int16 = new Int16Array(float32.length);
        for (let i = 0; i < float32.length; i++) {
          const c = Math.max(-1, Math.min(1, float32[i]));
          int16[i] = c < 0 ? c * 32768 : c * 32767;
        }
        ws.send(int16.buffer);
      };

      source.connect(processor);
      processor.connect(audioCtx.destination);
      setIsRecording(true);

    } catch (err) {
      isRecordingRef.current = false;
      setIsRecording(false);
      setError(err.message);
      _cleanup();
    }
  }, [callId]);

  // ── 듀얼 모드 (Zoom + VB-Cable) ──────────────────────────────
  const startDual = useCallback(async (agentDeviceId, customerDeviceId) => {
    if (isRecordingRef.current || !callId) return;
    isRecordingRef.current = true;
    setError(null);

    try {
      const ws = new WebSocket(getSTTUrl(callId, 'dual'));
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      await new Promise((resolve, reject) => {
        ws.onopen  = resolve;
        ws.onerror = () => reject(new Error('STT 서버 연결 실패'));
        setTimeout(() => reject(new Error('STT 연결 시간 초과')), 6000);
      });

      // 두 오디오 소스 캡처
      const agentStream = await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: { exact: agentDeviceId }, channelCount: 1 },
      });
      const customerStream = await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: { exact: customerDeviceId }, channelCount: 1 },
      });
      streamsRef.current = [agentStream, customerStream];

      const audioCtx = new AudioContext({ sampleRate: 16000 });
      audioCtxRef.current = audioCtx;

      // 스테레오 합치기: ch0=상담사, ch1=고객
      const merger  = audioCtx.createChannelMerger(2);
      const agentSrc    = audioCtx.createMediaStreamSource(agentStream);
      const customerSrc = audioCtx.createMediaStreamSource(customerStream);
      agentSrc.connect(merger, 0, 0);    // 상담사 → 왼쪽 (ch0)
      customerSrc.connect(merger, 0, 1); // 고객   → 오른쪽 (ch1)

      const processor = audioCtx.createScriptProcessor(4096, 2, 2);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        if (ws.readyState !== WebSocket.OPEN) return;
        const left  = e.inputBuffer.getChannelData(0); // 상담사
        const right = e.inputBuffer.getChannelData(1); // 고객

        // 인터리브 스테레오 PCM: L0, R0, L1, R1, ...
        const int16 = new Int16Array(left.length * 2);
        for (let i = 0; i < left.length; i++) {
          int16[i * 2]     = Math.max(-32768, Math.min(32767, left[i]  * 32767));
          int16[i * 2 + 1] = Math.max(-32768, Math.min(32767, right[i] * 32767));
        }
        ws.send(int16.buffer);
      };

      merger.connect(processor);
      processor.connect(audioCtx.destination);
      setIsRecording(true);
      console.log('[STT/dual] 듀얼 채널 녹음 시작');

    } catch (err) {
      isRecordingRef.current = false;
      setIsRecording(false);
      setError(err.message);
      _cleanup();
    }
  }, [callId]);

  const stop = useCallback(() => {
    if (!isRecordingRef.current) return;
    isRecordingRef.current = false;
    _cleanup();
    setIsRecording(false);
  }, []);

  return { isRecording, start, startDual, stop, error, devices, loadDevices };
};

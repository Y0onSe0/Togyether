import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import GNB from '../components/GNB';
import LNB from '../components/LNB';
import AICard from '../components/AICard';
import ChatPanel from '../components/ChatPanel';
import { startCall, endCall } from '../api/calls';
import { useWebSocket } from '../hooks/useWebSocket';
import { useSTT } from '../hooks/useSTT';

const Timer = ({ active }) => {
  const [seconds, setSeconds] = useState(0);
  const intervalRef = useRef(null);

  useEffect(() => {
    if (active) {
      setSeconds(0);
      intervalRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    } else {
      clearInterval(intervalRef.current);
      setSeconds(0);
    }
    return () => clearInterval(intervalRef.current);
  }, [active]);

  const format = (s) => {
    const m = Math.floor(s / 60).toString().padStart(2, '0');
    const sec = (s % 60).toString().padStart(2, '0');
    return `${m}:${sec}`;
  };

  return <span className="font-mono text-[15px] font-semibold">{format(seconds)}</span>;
};

const Main = () => {
  const navigate = useNavigate();
  const [callState, setCallState] = useState('idle'); // idle | calling
  const [callId, setCallId] = useState(null);
  const [ending, setEnding] = useState(false);

  const [aiState, setAiState] = useState({ status: 'idle' });
  const [similarCases, setSimilarCases] = useState([]);
  const [transferData, setTransferData] = useState([]);
  const [messages, setMessages] = useState([]);

  const handleWsMessage = useCallback((data) => {
    // 백엔드는 { type, ...rest } 형식으로 전송
    const type = data.type || data.event;

    if (type === 'ai_update') {
      const status = data.status || data.payload?.status;
      if (status === 'loading') {
        setAiState({ status: 'loading' });
      } else if (status === 'success') {
        setAiState({
          status: 'success',
          category: data.category || data.payload?.category,
          query: data.query || data.payload?.query,
          answer: data.answer || data.payload?.answer,
          references: data.references || data.payload?.references || [],
        });
      } else if (status === 'oos') {
        setAiState({
          status: 'oos',
          oos_type: data.oos_type || data.payload?.oos_type,
          query:    data.query   || data.payload?.query,
          answer:   data.answer  || data.payload?.answer,
        });
      } else if (status === 'api_pending') {
        setAiState({
          status:   'api_pending',
          category: data.category || data.payload?.category,
          query:    data.query    || data.payload?.query,
        });
      } else if (status === 'no_result') {
        setAiState({ status: 'no_result' });
      }
    }

    if (type === 'similar_cases') {
      const cases = data.data || data.payload?.cases || data.payload || [];
      setSimilarCases(cases);
    }

    if (type === 'transfer_suggestion') {
      const institutions = data.data || data.payload?.institutions || data.payload || [];
      setTransferData(institutions);
    }

    if (type === 'conversation_update') {
      // 백엔드: { type, speaker, text, timestamp }
      const msg = data.payload?.message || data.payload || {
        speaker: data.speaker,
        text: data.text,
        content: data.text,
        timestamp: data.timestamp,
        role: data.speaker === '상담사' ? 'agent' : 'customer',
      };
      if (msg?.text || msg?.content) {
        setMessages((prev) => [...prev, msg]);
      }
    }
  }, []);

  const [testText, setTestText] = useState('');
  const { connect, disconnect, sendMessage } = useWebSocket(callId, handleWsMessage);
  const { isRecording, start: startSTT, stop: stopSTT, error: sttError } = useSTT(callId);

  useEffect(() => {
    if (callId) {
      connect();
    }
  }, [callId, connect]);

  const handleStartCall = async () => {
    try {
      const data = await startCall();
      const id = data.call_id || data.id;
      setCallId(id);
      setCallState('calling');
      setAiState({ status: 'idle' });
      setSimilarCases([]);
      setTransferData([]);
      setMessages([]);
    } catch (err) {
      console.error('통화 시작 실패:', err);
      alert('통화 시작에 실패했습니다.');
    }
  };

  const handleEndCall = async () => {
    if (ending) return;
    setEnding(true);
    stopSTT(); // STT 먼저 종료
    try {
      await endCall(callId);
      disconnect();
      navigate(`/acw/${callId}`);
    } catch (err) {
      console.error('통화 종료 실패:', err);
      alert('통화 종료에 실패했습니다.');
      setEnding(false);
    }
  };

  const handleToggleSTT = () => {
    if (isRecording) stopSTT();
    else startSTT();
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <GNB />
      <LNB />

      <div className="pt-[52px] pl-[7%] min-w-[64px] h-screen flex flex-col">
        {/* 상태 바 */}
        <div className="bg-white border-b border-gray-100 px-6 py-3 flex items-center gap-4 shadow-sm">
          {callState === 'idle' ? (
            <>
              <div className="flex items-center gap-2">
                <div className="w-2.5 h-2.5 bg-green-500 rounded-full animate-pulse" />
                <span className="text-[15px] font-medium text-green-700">대기 중</span>
              </div>
              <button
                onClick={handleStartCall}
                className="ml-4 bg-[#1E40AF] hover:bg-blue-800 text-white text-[15px] font-semibold px-5 py-2 rounded-xl transition-colors flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"
                  />
                </svg>
                상담 시작
              </button>
            </>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <div className="w-2.5 h-2.5 bg-red-500 rounded-full animate-pulse" />
                <span className="text-[15px] font-medium text-red-700">상담 중</span>
              </div>
              <Timer active={callState === 'calling'} />
              <span className="text-[13px] text-gray-400">통화 ID: {callId}</span>

              {/* STT 마이크 버튼 */}
              <button
                onClick={handleToggleSTT}
                title={isRecording ? 'STT 중지' : 'STT 시작 (실시간 자막)'}
                className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-[13px] font-semibold transition-all ${
                  isRecording
                    ? 'bg-red-100 text-red-600 ring-2 ring-red-400 ring-offset-1'
                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                }`}
              >
                {/* 마이크 아이콘 */}
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4M12 3a4 4 0 014 4v4a4 4 0 01-8 0V7a4 4 0 014-4z"
                  />
                </svg>
                {isRecording
                  ? <><span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" /> 자막 ON</>
                  : '자막'}
              </button>

              {/* STT 오류 표시 */}
              {sttError && (
                <span className="text-[12px] text-red-500">{sttError}</span>
              )}

              <button
                onClick={handleEndCall}
                disabled={ending}
                className="ml-auto bg-red-500 hover:bg-red-600 text-white text-[15px] font-semibold px-5 py-2 rounded-xl transition-colors disabled:opacity-60 flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M16 8l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2M5 3a2 2 0 00-2 2v1c0 8.284 6.716 15 15 15h1a2 2 0 002-2v-3.28a1 1 0 00-.684-.948l-4.493-1.498a1 1 0 00-1.21.502l-1.13 2.257a11.042 11.042 0 01-5.516-5.517l2.257-1.128a1 1 0 00.502-1.21L9.228 3.683A1 1 0 008.279 3H5z"
                  />
                </svg>
                {ending ? '종료 중...' : '통화 종료'}
              </button>
            </>
          )}
        </div>

        {/* 테스트용 발화 입력 (개발 모드) */}
        {callState === 'calling' && (
          <div className="bg-yellow-50 border-b border-yellow-200 px-6 py-2 flex items-center gap-2">
            <span className="text-[13px] text-yellow-600 font-medium flex-shrink-0">🧪 테스트</span>
            <select
              id="test-speaker"
              className="text-[13px] border border-yellow-300 rounded px-2 py-1 bg-white"
              defaultValue="고객"
            >
              <option value="고객">고객</option>
              <option value="상담사">상담사</option>
            </select>
            <input
              type="text"
              value={testText}
              onChange={(e) => setTestText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && testText.trim()) {
                  const speaker = document.getElementById('test-speaker').value;
                  sendMessage({ speaker, text: testText.trim() });
                  setTestText('');
                }
              }}
              placeholder="발화 입력 후 Enter"
              className="flex-1 text-[13px] border border-yellow-300 rounded px-3 py-1 focus:outline-none focus:ring-1 focus:ring-yellow-400"
            />
            <button
              onClick={() => {
                if (testText.trim()) {
                  const speaker = document.getElementById('test-speaker').value;
                  sendMessage({ speaker, text: testText.trim() });
                  setTestText('');
                }
              }}
              className="text-[13px] bg-yellow-400 hover:bg-yellow-500 text-white px-3 py-1 rounded transition-colors"
            >
              전송
            </button>
          </div>
        )}

        {/* 콘텐츠 영역 */}
        <div className="flex flex-1 overflow-hidden">
          {/* 좌측: AI 카드 (43%) */}
          <div className="w-[43%] p-4 overflow-y-auto border-r border-gray-100">
            <AICard
              aiState={aiState}
              similarCases={similarCases}
              transferData={transferData}
            />
          </div>

          {/* 우측: 대화 내역 (57%) */}
          <div className="flex-1 p-4 overflow-hidden flex flex-col">
            <ChatPanel messages={messages} />
          </div>
        </div>
      </div>
    </div>
  );
};

export default Main;

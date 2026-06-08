import { useEffect, useRef } from 'react';

const MessageBubble = ({ message }) => {
  const isAgent = message.role === 'agent' || message.speaker === 'agent';
  const isCustomer = message.role === 'customer' || message.speaker === 'customer';

  return (
    <div className={`flex gap-2 mb-3 ${isAgent ? 'flex-row-reverse' : 'flex-row'}`}>
      <div className="flex-shrink-0 mt-0.5">
        <div className={`w-7 h-7 rounded-full flex items-center justify-center text-[13px] ${
          isAgent ? 'bg-[#EAF0FA] text-[#003F7D]' : 'bg-gray-100 text-gray-600'
        }`}>
          {isAgent ? '🎧' : '👤'}
        </div>
      </div>
      <div className={`flex flex-col gap-0.5 max-w-[75%] ${isAgent ? 'items-end' : 'items-start'}`}>
        <span className="text-[12px] text-gray-400 font-medium">
          {isAgent ? '상담사' : '고객'}
        </span>
        <div className={`px-3 py-2 rounded text-[15px] leading-relaxed ${
          isAgent
            ? 'bg-[#0054A6] text-white rounded-tr-sm'
            : 'bg-gray-100 text-gray-800 rounded-tl-sm'
        }`}>
          {message.content || message.text || message.message}
        </div>
        {message.timestamp && (
          <span className="text-[11px] text-gray-300">
            {new Date(message.timestamp).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>
    </div>
  );
};

const ChatPanel = ({ messages = [] }) => {
  const bottomRef = useRef(null);

  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  return (
    <div className="flex flex-col h-full bg-white rounded-lg border border-gray-100 shadow-sm overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
        <svg className="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
          />
        </svg>
        <h3 className="text-[15px] font-semibold text-gray-700">대화 내역</h3>
        {messages.length > 0 && (
          <span className="ml-auto text-[13px] text-gray-400">{messages.length}개</span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-300">
            <svg className="w-12 h-12 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              />
            </svg>
            <p className="text-[15px]">대화 내역이 없습니다</p>
          </div>
        ) : (
          <>
            {messages.map((msg, i) => (
              <MessageBubble key={i} message={msg} />
            ))}
            <div ref={bottomRef} />
          </>
        )}
      </div>
    </div>
  );
};

export default ChatPanel;

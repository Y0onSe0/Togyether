import { useState, useEffect, useCallback } from 'react';
import LNB from '../components/LNB';
import GNB from '../components/GNB';

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

const authHeaders = () => ({
  Authorization: `Bearer ${localStorage.getItem('access_token')}`,
  'Content-Type': 'application/json',
});

// ── 포맷 헬퍼 ──────────────────────────────────────────────
const fmtDateTime = (iso) => {
  if (!iso) return '-';
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};

const fmtDate = (iso) => {
  if (!iso) return '-';
  return iso.slice(0, 10);
};

// ── 뱃지 컴포넌트 ──────────────────────────────────────────
const Badge = ({ resolved, transferred }) => {
  if (transferred) return <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-700">이관</span>;
  if (resolved === true) return <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">해결</span>;
  if (resolved === false) return <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">미해결</span>;
  return <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-500">-</span>;
};

// ── 상담 상세 패널 ─────────────────────────────────────────
const DetailPanel = ({ callId, onClose }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('summary'); // 'summary' | 'transcript' | 'ai'

  useEffect(() => {
    if (!callId) return;
    setLoading(true);
    setTab('summary');
    fetch(`${API}/api/history/${callId}`, { headers: authHeaders() })
      .then((r) => r.json())
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [callId]);

  if (!callId) return null;

  return (
    <div className="w-[400px] min-w-[360px] bg-white border-l border-gray-200 flex flex-col h-full overflow-hidden">
      {/* 패널 헤더 */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
        <div>
          <h3 className="font-semibold text-gray-800 text-sm">상담 상세</h3>
          {data && <p className="text-xs text-gray-400 mt-0.5">{fmtDateTime(data.started_at)}</p>}
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {loading ? (
        <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">불러오는 중...</div>
      ) : !data ? (
        <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">데이터 없음</div>
      ) : (
        <>
          {/* 기본 정보 카드 */}
          <div className="px-5 py-3 bg-gray-50 border-b border-gray-100">
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-gray-400">질환명</span>
                <p className="font-medium text-gray-800 mt-0.5">{data.disease_name || '-'}</p>
              </div>
              <div>
                <span className="text-gray-400">통화시간</span>
                <p className="font-medium text-gray-800 mt-0.5">{data.duration}</p>
              </div>
              <div>
                <span className="text-gray-400">대분류</span>
                <p className="font-medium text-gray-800 mt-0.5">{data.category_major || '-'}</p>
              </div>
              <div>
                <span className="text-gray-400">중분류</span>
                <p className="font-medium text-gray-800 mt-0.5">{data.category_mid || '-'}</p>
              </div>
              <div>
                <span className="text-gray-400">해결 여부</span>
                <div className="mt-0.5">
                  <Badge resolved={data.is_resolved} transferred={data.is_transferred} />
                </div>
              </div>
              {data.agent_used_ai && (
                <div>
                  <span className="text-gray-400">AI 활용</span>
                  <p className="font-medium text-blue-600 mt-0.5">✓ 사용</p>
                </div>
              )}
            </div>
          </div>

          {/* 탭 */}
          <div className="flex border-b border-gray-100 bg-white">
            {[
              { key: 'summary', label: 'Q&A 요약' },
              { key: 'transcript', label: '대화 내역' },
              { key: 'ai', label: 'AI 가이드' },
            ].map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`flex-1 py-2.5 text-xs font-medium transition-colors ${
                  tab === t.key
                    ? 'text-blue-600 border-b-2 border-blue-600'
                    : 'text-gray-400 hover:text-gray-600'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* 탭 콘텐츠 */}
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
            {/* Q&A 요약 탭 */}
            {tab === 'summary' && (
              <>
                {data.ai_response_summary && (
                  <div className="bg-blue-50 rounded-lg p-3 mb-3">
                    <p className="text-xs font-semibold text-blue-700 mb-1">AI 응답 요약</p>
                    <p className="text-xs text-blue-800 leading-relaxed">{data.ai_response_summary}</p>
                  </div>
                )}
                {data.agent_memo && (
                  <div className="bg-yellow-50 rounded-lg p-3 mb-3">
                    <p className="text-xs font-semibold text-yellow-700 mb-1">상담사 메모</p>
                    <p className="text-xs text-yellow-800 leading-relaxed">{data.agent_memo}</p>
                  </div>
                )}
                {Array.isArray(data.qa_summary) && data.qa_summary.length > 0 ? (
                  data.qa_summary.map((qa, idx) => (
                    <div key={idx} className="border border-gray-100 rounded-lg p-3">
                      <div className="flex items-start gap-2 mb-2">
                        <span className="shrink-0 w-5 h-5 rounded-full bg-blue-100 text-blue-700 text-[10px] font-bold flex items-center justify-center">Q</span>
                        <p className="text-xs text-gray-800 leading-relaxed">{qa.q}</p>
                      </div>
                      <div className="flex items-start gap-2">
                        <span className="shrink-0 w-5 h-5 rounded-full bg-green-100 text-green-700 text-[10px] font-bold flex items-center justify-center">A</span>
                        <p className="text-xs text-gray-600 leading-relaxed">{qa.a}</p>
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="text-xs text-gray-400 text-center py-4">Q&A 요약 데이터가 없습니다.</p>
                )}
                {/* 키워드 */}
                {Array.isArray(data.keywords) && data.keywords.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs text-gray-400 mb-2">키워드</p>
                    <div className="flex flex-wrap gap-1">
                      {data.keywords.map((kw, i) => (
                        <span key={i} className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full text-[11px]">{kw}</span>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            {/* 대화 내역 탭 */}
            {tab === 'transcript' && (
              <div className="space-y-2">
                {data.transcript ? (
                  data.transcript.split('\n').filter(Boolean).map((line, idx) => {
                    const isAgent = line.includes('상담사:');
                    const isCustomer = line.includes('고객:');
                    const timeMatch = line.match(/^\[(\d{2}:\d{2}:\d{2})\]/);
                    const timeStr = timeMatch ? timeMatch[1] : '';
                    const content = line.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '').replace(/^(상담사|고객):\s*/, '');
                    const speaker = isAgent ? '상담사' : isCustomer ? '고객' : '';

                    return (
                      <div
                        key={idx}
                        className={`flex gap-2 ${isAgent ? 'flex-row-reverse' : 'flex-row'}`}
                      >
                        {speaker && (
                          <div className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold ${
                            isAgent ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-600'
                          }`}>
                            {isAgent ? '상' : '고'}
                          </div>
                        )}
                        <div className={`max-w-[75%] ${isAgent ? 'items-end' : 'items-start'} flex flex-col gap-0.5`}>
                          {timeStr && <span className="text-[10px] text-gray-300">{timeStr}</span>}
                          <div className={`px-3 py-2 rounded-xl text-xs leading-relaxed ${
                            isAgent
                              ? 'bg-blue-50 text-blue-900'
                              : 'bg-gray-100 text-gray-800'
                          }`}>
                            {content}
                          </div>
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <p className="text-xs text-gray-400 text-center py-4">대화 내역이 없습니다.</p>
                )}
              </div>
            )}

            {/* AI 가이드 탭 */}
            {tab === 'ai' && (
              <>
                {data.ai_guidance ? (
                  <div className="space-y-3">
                    {data.ai_guidance.query && (
                      <div className="bg-blue-50 rounded-lg p-3">
                        <p className="text-[10px] font-semibold text-blue-500 uppercase mb-1">인식된 질문</p>
                        <p className="text-xs text-blue-900 font-medium">{data.ai_guidance.query}</p>
                      </div>
                    )}
                    {data.ai_guidance.category && (
                      <div className="flex gap-2 items-center">
                        <span className="text-[10px] text-gray-400">카테고리</span>
                        <span className="px-2 py-0.5 bg-purple-100 text-purple-700 rounded text-[11px] font-medium">{data.ai_guidance.category}</span>
                      </div>
                    )}
                    {data.ai_guidance.answer && (
                      <div className="border border-gray-100 rounded-lg p-3">
                        <p className="text-[10px] font-semibold text-gray-400 uppercase mb-2">AI 안내 내용</p>
                        <p className="text-xs text-gray-700 leading-relaxed whitespace-pre-wrap">{data.ai_guidance.answer}</p>
                      </div>
                    )}
                    {data.ai_guidance.sources && data.ai_guidance.sources.length > 0 && (
                      <div>
                        <p className="text-[10px] text-gray-400 mb-2">참고 출처</p>
                        <div className="space-y-1">
                          {data.ai_guidance.sources.map((src, i) => (
                            <div key={i} className="text-[11px] text-gray-500 bg-gray-50 px-2 py-1 rounded">
                              {typeof src === 'string' ? src : src.title || src.source || JSON.stringify(src)}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {!data.ai_guidance.query && !data.ai_guidance.answer && (
                      <p className="text-xs text-gray-400 text-center py-4">AI 가이드 정보가 없습니다.</p>
                    )}
                  </div>
                ) : (
                  <p className="text-xs text-gray-400 text-center py-4">AI 가이드 정보가 없습니다.</p>
                )}
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
};

// ── 메인 페이지 ────────────────────────────────────────────
const History = () => {
  const [summary, setSummary] = useState(null);
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [selectedCallId, setSelectedCallId] = useState(null);

  // 날짜 필터
  const today = new Date().toISOString().slice(0, 10);
  const monthAgo = new Date(Date.now() - 30 * 24 * 3600 * 1000).toISOString().slice(0, 10);
  const [startDate, setStartDate] = useState(monthAgo);
  const [endDate, setEndDate] = useState(today);

  const PAGE_SIZE = 15;

  const loadSummary = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/history/summary`, { headers: authHeaders() });
      if (r.ok) setSummary(await r.json());
    } catch (e) {}
  }, []);

  const [diseaseSearch, setDiseaseSearch] = useState('');

  const loadItems = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: p, page_size: PAGE_SIZE });
      if (startDate) params.append('start_date', startDate);
      if (endDate) params.append('end_date', endDate);
      if (diseaseSearch.trim()) params.append('disease', diseaseSearch.trim());
      const r = await fetch(`${API}/api/history?${params}`, { headers: authHeaders() });
      if (r.ok) {
        const d = await r.json();
        setItems(d.items);
        setTotal(d.total);
        setPage(p);
      }
    } catch (e) {}
    setLoading(false);
  }, [startDate, endDate, diseaseSearch]);

  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => { loadItems(1); }, [loadItems]);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="min-h-screen bg-gray-50">
      <GNB />
      <LNB />
      <div className="ml-[7%] min-w-0 pt-[52px] flex h-[calc(100vh-52px)]">
        {/* 메인 영역 */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* 상단 헤더 */}
          <div className="bg-white border-b border-gray-200 px-6 py-4">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-lg font-bold text-gray-800">상담 내역</h1>
                <p className="text-xs text-gray-400 mt-0.5">완료된 상담 내역을 조회합니다</p>
              </div>
              {/* 필터 영역 */}
              <div className="flex items-center gap-2 flex-wrap">
                {/* 질병명 검색 */}
                <div className="relative">
                  <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                  <input
                    type="text"
                    placeholder="질병명 검색"
                    value={diseaseSearch}
                    onChange={(e) => setDiseaseSearch(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && loadItems(1)}
                    className="pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 w-36"
                  />
                </div>
                <div className="w-px h-5 bg-gray-200" />
                {/* 날짜 필터 */}
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <span className="text-gray-400 text-sm">~</span>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <button
                  onClick={() => loadItems(1)}
                  className="bg-blue-600 text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
                >
                  조회
                </button>
              </div>
            </div>
          </div>

          {/* 요약 카드 */}
          {summary && (
            <div className="px-6 py-4 grid grid-cols-5 gap-3">
              {[
                { label: '전체 상담', value: `${summary.total_calls}건`, color: 'text-gray-800' },
                { label: '오늘 상담', value: `${summary.today_calls}건`, color: 'text-blue-600' },
                { label: '해결 완료', value: `${summary.resolved_calls}건`, color: 'text-green-600' },
                { label: '해결률', value: `${summary.resolution_rate}%`, color: 'text-purple-600' },
                { label: '평균 통화', value: summary.avg_duration, color: 'text-orange-600' },
              ].map((s) => (
                <div key={s.label} className="bg-white rounded-xl border border-gray-100 px-4 py-3 shadow-sm">
                  <p className="text-xs text-gray-400">{s.label}</p>
                  <p className={`text-xl font-bold mt-1 ${s.color}`}>{s.value}</p>
                </div>
              ))}
            </div>
          )}

          {/* 테이블 */}
          <div className="flex-1 overflow-auto px-6 pb-4">
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-100">
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 w-12">No</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500">상담 일시</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500">질환명</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500">대분류</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500">중분류</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500">통화시간</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500">AI 활용</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500">해결 상태</th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <tr>
                      <td colSpan={8} className="text-center py-12 text-gray-400 text-sm">
                        불러오는 중...
                      </td>
                    </tr>
                  ) : items.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="text-center py-12 text-gray-400 text-sm">
                        상담 내역이 없습니다.
                      </td>
                    </tr>
                  ) : (
                    items.map((item, idx) => {
                      const rowNo = total - ((page - 1) * PAGE_SIZE) - idx;
                      const isSelected = selectedCallId === item.call_id;
                      return (
                        <tr
                          key={item.acw_id}
                          onClick={() => setSelectedCallId(isSelected ? null : item.call_id)}
                          className={`border-b border-gray-50 cursor-pointer transition-colors ${
                            isSelected ? 'bg-blue-50' : 'hover:bg-gray-50'
                          }`}
                        >
                          <td className="px-4 py-3 text-xs text-gray-400">{rowNo}</td>
                          <td className="px-4 py-3 text-xs text-gray-700">{fmtDateTime(item.started_at || item.created_at)}</td>
                          <td className="px-4 py-3">
                            <span className="text-xs font-medium text-gray-800">{item.disease_name}</span>
                          </td>
                          <td className="px-4 py-3 text-xs text-gray-600">{item.category_major}</td>
                          <td className="px-4 py-3 text-xs text-gray-600">{item.category_mid}</td>
                          <td className="px-4 py-3 text-xs text-gray-600">{item.duration}</td>
                          <td className="px-4 py-3">
                            {item.agent_used_ai ? (
                              <span className="text-xs text-blue-600 font-medium">✓ AI</span>
                            ) : (
                              <span className="text-xs text-gray-300">-</span>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <Badge resolved={item.is_resolved} transferred={item.is_transferred} />
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>

              {/* 페이지네이션 */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
                  <p className="text-xs text-gray-400">총 {total}건</p>
                  <div className="flex gap-1">
                    <button
                      onClick={() => loadItems(page - 1)}
                      disabled={page === 1}
                      className="px-3 py-1.5 rounded text-xs border border-gray-200 disabled:opacity-40 hover:bg-gray-50 transition-colors"
                    >
                      이전
                    </button>
                    {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                      const start = Math.max(1, Math.min(page - 2, totalPages - 4));
                      const p = start + i;
                      return (
                        <button
                          key={p}
                          onClick={() => loadItems(p)}
                          className={`px-3 py-1.5 rounded text-xs border transition-colors ${
                            p === page
                              ? 'bg-blue-600 text-white border-blue-600'
                              : 'border-gray-200 hover:bg-gray-50'
                          }`}
                        >
                          {p}
                        </button>
                      );
                    })}
                    <button
                      onClick={() => loadItems(page + 1)}
                      disabled={page === totalPages}
                      className="px-3 py-1.5 rounded text-xs border border-gray-200 disabled:opacity-40 hover:bg-gray-50 transition-colors"
                    >
                      다음
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 상세 패널 */}
        {selectedCallId && (
          <DetailPanel callId={selectedCallId} onClose={() => setSelectedCallId(null)} />
        )}
      </div>
    </div>
  );
};

export default History;

import { useState, useEffect } from 'react';
import SourceCarousel from './SourceCarousel';
import SimilarCasesCard from './SimilarCasesCard';
import TransferCard from './TransferCard';

// ── 공통 배지 ─────────────────────────────────────────────────────────
const StatusBadge = ({ category }) => {
  if (!category) return null;
  return (
    <span className="inline-block px-2 py-0.5 bg-blue-100 text-blue-700 text-[13px] font-semibold rounded-full">
      {category}
    </span>
  );
};

// ── OOS 타입별 카드 ───────────────────────────────────────────────────

/** action_required: 시스템·행정 접수 처리 */
const OosActionRequired = ({ query }) => (
  <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-3">
    <div className="flex items-center gap-2">
      <span className="text-lg">⚙️</span>
      <p className="text-[15px] font-semibold text-amber-800">시스템·행정 문의</p>
    </div>
    {query && (
      <p className="text-[13px] text-gray-600 bg-white rounded-lg px-3 py-2 border border-amber-100">
        "{query}"
      </p>
    )}
    <div className="text-[14px] text-gray-700 space-y-1">
      <p className="font-medium text-gray-500 text-[12px] uppercase tracking-wide mb-1">담당 연결</p>
      <div className="flex items-center gap-2">
        <span className="text-amber-600">☎</span>
        <span>질병보건통합관리시스템 헬프데스크</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-amber-600">→</span>
        <span className="font-semibold">1339 → 시스템 문의</span>
      </div>
    </div>
    <button
      className="w-full mt-1 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-[14px] font-medium transition-colors"
      onClick={() => alert('이관 처리 — 실제 연동 필요')}
    >
      이관하기
    </button>
  </div>
);

/** realtime_local: 실시간·위치 기반 정보 */
const OosRealtimeLocal = ({ query }) => (
  <div className="bg-sky-50 border border-sky-200 rounded-xl p-4 space-y-3">
    <div className="flex items-center gap-2">
      <span className="text-lg">📍</span>
      <p className="text-[15px] font-semibold text-sky-800">실시간·위치 정보 문의</p>
    </div>
    {query && (
      <p className="text-[13px] text-gray-600 bg-white rounded-lg px-3 py-2 border border-sky-100">
        "{query}"
      </p>
    )}
    <p className="text-[14px] text-gray-600">실시간·위치 정보는 외부에서 직접 확인이 필요합니다.</p>
    <div className="space-y-2">
      <p className="font-medium text-gray-500 text-[12px] uppercase tracking-wide">관련 바로가기</p>
      {[
        { label: '동네 진료소 찾기', url: 'https://www.hira.or.kr/ra/hosp/getHealthMap.do?tabgbn=03&WT.ac=HIRA%EA%B1%B4%EA%B0%95%EC%A7%80%EB%8F%84%EB%B0%94%EB%A1%9C%EA%B0%80%EA%B8%B0', desc: '건강보험심사평가원 건강지도' },
        { label: '질병관리청 감염병 현황', url: 'https://www.kdca.go.kr', desc: 'kdca.go.kr' },
        { label: '공공보건포털', url: 'https://www.g-health.kr', desc: '보건소·예방접종 기관 검색' },
      ].map(({ label, url, desc }) => (
        <a
          key={url}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-between px-3 py-2 bg-white rounded-lg border border-sky-100 hover:border-sky-300 hover:bg-sky-50 transition-colors group"
        >
          <div>
            <span className="text-[14px] font-medium text-sky-700 group-hover:underline">{label}</span>
            <p className="text-[12px] text-gray-400">{desc}</p>
          </div>
          <span className="text-sky-400 text-[12px]">↗</span>
        </a>
      ))}
    </div>
    <p className="text-[13px] text-gray-500">☎ 1339 (질병관리청 콜센터)</p>
  </div>
);

/** unrelated: 완전 범위 외 */
const OosUnrelated = ({ query }) => (
  <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-2">
    <div className="flex items-center gap-2">
      <span className="text-lg">ℹ️</span>
      <p className="text-[15px] font-semibold text-gray-700">업무 범위 외 문의</p>
    </div>
    {query && (
      <p className="text-[13px] text-gray-500 bg-white rounded-lg px-3 py-2 border border-gray-200">
        "{query}"
      </p>
    )}
    <p className="text-[14px] text-gray-600">
      해당 문의는 질병관리청 콜센터 업무 범위 외 내용입니다.
    </p>
    <p className="text-[13px] text-gray-500">관련 기관으로 안내해 주세요.</p>
  </div>
);

/** transfer: 타 기관·부서 이관 */
const OosTransfer = ({ query }) => (
  <div className="bg-purple-50 border border-purple-200 rounded-xl p-4 space-y-3">
    <div className="flex items-center gap-2">
      <span className="text-lg">📞</span>
      <p className="text-[15px] font-semibold text-purple-800">타 기관 이관 안내</p>
    </div>
    {query && (
      <p className="text-[13px] text-gray-600 bg-white rounded-lg px-3 py-2 border border-purple-100">
        "{query}"
      </p>
    )}
    <p className="text-[14px] text-gray-700">담당 기관·부서로 연결이 필요합니다.</p>
    <div className="text-[14px] text-gray-600 space-y-1">
      <div className="flex items-center gap-2">
        <span className="text-purple-500">☎</span>
        <span>1339 (질병관리청 콜센터)</span>
      </div>
    </div>
  </div>
);

// ── 검역 정보 카드 (API 연동) ─────────────────────────────────────────
const MOCK_QUARANTINE = {
  success: true,
  country: "베트남",
  data: [
    { disease: "콜레라",  start_date: "2024-09-02", end_date: "" },
    { disease: "뎅기열",  start_date: "2024-03-15", end_date: "" },
    { disease: "지카바이러스", start_date: "2023-11-01", end_date: "" },
  ],
};

const QuarantineCard = ({ query }) => {
  const [state, setState] = useState('loading');
  const [data, setData]   = useState(null);

  useEffect(() => {
    if (!query) return;
    setState('loading');
    fetch(`/api/quarantine/search?query=${encodeURIComponent(query)}`)
      .then(r => r.json())
      .then(json => { setData(json); setState(json.matched === false ? 'no_match' : 'success'); })
      .catch(() => setState('error'));
  }, [query]);

  return (
    <div className="bg-teal-50 border border-teal-200 rounded-xl p-4 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-lg">✈️</span>
        <p className="text-[15px] font-semibold text-teal-800">해외/검역 정보</p>
      </div>

      {query && (
        <p className="text-[13px] text-gray-600 bg-white rounded-lg px-3 py-2 border border-teal-100">
          "{query}"
        </p>
      )}

      {state === 'loading' && (
        <div className="flex items-center gap-2 py-2">
          <div className="w-4 h-4 border-2 border-teal-300 border-t-teal-600 rounded-full animate-spin" />
          <span className="text-[13px] text-gray-500">검역 정보 조회 중...</span>
        </div>
      )}

      {state === 'success' && data?.country && (
        <div className="space-y-2">
          <p className="text-[13px] font-semibold text-teal-700">
            {data.country} 검역관리 감염병
          </p>
          {data.data?.length > 0 ? (
            <div className="space-y-1.5">
              {data.data.map((item, i) => (
                <div key={i} className="flex items-center justify-between bg-white rounded-lg px-3 py-2 border border-teal-100">
                  <span className="text-[14px] font-medium text-gray-800">⚠️ {item.disease}</span>
                  <span className="text-[12px] text-gray-400">{item.start_date} ~</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[14px] text-gray-500">현재 {data.country}에 대한 검역관리 지정 없음</p>
          )}
        </div>
      )}

      {state === 'success' && data?.icd && (
        <div className="space-y-2">
          {data.data?.length > 0 ? (
            data.data.slice(0, 3).map((item, i) => (
              <div key={i} className="bg-white rounded-lg px-3 py-2 border border-teal-100">
                <p className="text-[13px] font-medium text-gray-700">{item.group_name}</p>
                <p className="text-[12px] text-gray-500 mt-0.5">
                  감시기간 {item.watch_days}일 · {item.nations.slice(0, 5).join(', ')}
                  {item.nations.length > 5 ? ` 외 ${item.nations.length - 5}개국` : ''}
                </p>
              </div>
            ))
          ) : (
            <p className="text-[14px] text-gray-500">해당 감염병 검역관리지역 없음</p>
          )}
        </div>
      )}

      {(state === 'no_match' || state === 'error') && (
        <p className="text-[14px] text-gray-600">
          {data?.message ?? '검역 정보를 찾지 못했습니다. 아래 사이트에서 확인해 주세요.'}
        </p>
      )}

      {/* 외부 링크 */}
      <div className="space-y-1.5 pt-1">
        {[
          { label: '해외감염병 NOW',  url: 'https://해외감염병now.kr' },
          { label: '검역정보 포털',   url: 'https://quarantine.kdca.go.kr' },
        ].map(({ label, url }) => (
          <a key={url} href={url} target="_blank" rel="noopener noreferrer"
            className="flex items-center justify-between px-3 py-2 bg-white rounded-lg border border-teal-100 hover:border-teal-300 hover:bg-teal-50 transition-colors group">
            <span className="text-[14px] text-teal-700 font-medium group-hover:underline">🔗 {label}</span>
            <span className="text-teal-400 text-[11px]">↗</span>
          </a>
        ))}
      </div>
    </div>
  );
};

// ── 예방접종 정보 카드 (API + LLM 캐싱) ─────────────────────────────
const VaccineCard = ({ query }) => {
  const [state, setState] = useState('loading');
  const [data, setData]   = useState(null);

  useEffect(() => {
    if (!query) return;
    setState('loading');
    fetch(`/api/vaccine/search?query=${encodeURIComponent(query)}`)
      .then(r => r.json())
      .then(json => { setData(json); setState(json.matched === false ? 'no_match' : 'success'); })
      .catch(() => setState('error'));
  }, [query]);

  return (
    <div className="bg-green-50 border border-green-200 rounded-xl p-4 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-lg">💉</span>
        <p className="text-[15px] font-semibold text-green-800">예방접종 문의</p>
        {data?.cached && (
          <span className="ml-auto text-[11px] px-2 py-0.5 bg-green-100 text-green-600 rounded-full">캐시</span>
        )}
      </div>

      {query && (
        <p className="text-[13px] text-gray-600 bg-white rounded-lg px-3 py-2 border border-green-100">
          "{query}"
        </p>
      )}

      {state === 'loading' && (
        <div className="flex items-center gap-2 py-2">
          <div className="w-4 h-4 border-2 border-green-300 border-t-green-600 rounded-full animate-spin" />
          <span className="text-[13px] text-gray-500">예방접종 정보 조회 중...</span>
        </div>
      )}

      {state === 'success' && data && (
        <div className="space-y-2">
          {data.title && <p className="text-[13px] font-semibold text-green-700">{data.title}</p>}
          {data.summary && <p className="text-[14px] text-gray-600">{data.summary}</p>}
          <div className="space-y-1.5">
            {data.schedule    && <InfoRow icon="📅" label="접종 시기" value={data.schedule} />}
            {data.target      && <InfoRow icon="👥" label="접종 대상" value={data.target} />}
            {data.side_effects && <InfoRow icon="⚠️" label="이상반응" value={data.side_effects} />}
          </div>
        </div>
      )}

      {(state === 'no_match' || state === 'error') && (
        <p className="text-[14px] text-gray-600">
          {data?.message ?? '접종 정보를 찾지 못했습니다. 예방접종도우미에서 확인해 주세요.'}
        </p>
      )}

      <div className="space-y-1.5 pt-1">
        {[
          { label: '예방접종도우미', url: 'https://nip.kdca.go.kr' },
          { label: '이상반응 신고',  url: 'https://nip.kdca.go.kr/irhp/' },
        ].map(({ label, url }) => (
          <a key={url} href={url} target="_blank" rel="noopener noreferrer"
            className="flex items-center justify-between px-3 py-2 bg-white rounded-lg border border-green-100 hover:border-green-300 hover:bg-green-50 transition-colors group">
            <span className="text-[14px] text-green-700 font-medium group-hover:underline">🔗 {label}</span>
            <span className="text-green-400 text-[11px]">↗</span>
          </a>
        ))}
      </div>
    </div>
  );
};

const InfoRow = ({ icon, label, value }) => (
  <div className="flex gap-2 bg-white rounded-lg px-3 py-2 border border-green-100">
    <span className="text-[13px] flex-shrink-0">{icon}</span>
    <div className="min-w-0">
      <span className="text-[11px] text-gray-400 font-medium block">{label}</span>
      <span className="text-[13px] text-gray-700 leading-snug">{value}</span>
    </div>
  </div>
);

// ── api_pending: 카테고리별 분기 ──────────────────────────────────────
const ApiPendingCard = ({ query, category }) => {
  if (category === '해외/검역 정보 문의') return <QuarantineCard query={query} />;
  if (category === '예방접종')            return <VaccineCard query={query} />;

  // 감염병 통계·현황 → 링크만
  return (
    <div className="bg-green-50 border border-green-200 rounded-xl p-4 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-lg">📊</span>
        <p className="text-[15px] font-semibold text-green-800">{category} 문의</p>
      </div>
      {query && (
        <p className="text-[13px] text-gray-600 bg-white rounded-lg px-3 py-2 border border-green-100">
          "{query}"
        </p>
      )}
      <p className="text-[14px] text-gray-600">아래 공식 사이트에서 최신 정보를 확인해 주세요.</p>
      <a href="https://www.kdca.go.kr/npt/biz/npp/portal/nppPblctDtaView.do"
        target="_blank" rel="noopener noreferrer"
        className="flex items-center justify-between px-3 py-2 bg-white rounded-lg border border-green-100 hover:border-green-300 hover:bg-green-50 transition-colors group">
        <span className="text-[14px] text-green-700 font-medium group-hover:underline">🔗 질병관리청 감염병 현황</span>
        <span className="text-green-400 text-[11px]">↗</span>
      </a>
    </div>
  );
};

// ── 메인 AICard ───────────────────────────────────────────────────────
const AICard = ({ aiState, similarCases, transferData }) => {
  const renderAIContent = () => {
    if (!aiState || aiState.status === 'idle') {
      return (
        <div className="flex flex-col items-center justify-center h-48 text-gray-300">
          <svg className="w-12 h-12 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.347.347a.5.5 0 01-.638.058L12 17l-1.95 1.95a.5.5 0 01-.638-.058l-.347-.347z"
            />
          </svg>
          <p className="text-[15px]">상담을 시작하면 AI 분석이 시작됩니다</p>
        </div>
      );
    }

    if (aiState.status === 'loading') {
      return (
        <div className="flex flex-col items-center justify-center h-48 gap-3">
          <div className="w-8 h-8 border-3 border-blue-200 border-t-[#1E40AF] rounded-full animate-spin" />
          <p className="text-[15px] text-gray-500">⏳ AI 분석 중...</p>
        </div>
      );
    }

    // ── OOS: 타입별 분기 ──────────────────────────────────────────────
    if (aiState.status === 'oos') {
      const { oos_type, query } = aiState;

      if (oos_type === 'action_required') return <OosActionRequired query={query} />;
      if (oos_type === 'realtime_local')  return <OosRealtimeLocal query={query} />;
      if (oos_type === 'transfer')        return <OosTransfer query={query} />;
      // unrelated (기본)
      return <OosUnrelated query={query} />;
    }

    // ── api_pending: 링크 안내 ───────────────────────────────────────
    if (aiState.status === 'api_pending') {
      return <ApiPendingCard query={aiState.query} category={aiState.category} />;
    }

    if (aiState.status === 'no_result') {
      return (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 flex items-center gap-3">
          <svg className="w-5 h-5 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <p className="text-[15px] text-gray-500">관련 정보를 찾을 수 없습니다.</p>
        </div>
      );
    }

    if (aiState.status === 'success') {
      return (
        <div>
          {aiState.category && (
            <div className="mb-2">
              <StatusBadge category={aiState.category} />
            </div>
          )}
          {aiState.query && (
            <div className="mb-3">
              <p className="text-[13px] text-gray-400 font-medium mb-1">인식된 문의</p>
              <p className="text-[15px] text-gray-800 font-medium leading-relaxed bg-gray-50 rounded-lg px-3 py-2">
                {aiState.query}
              </p>
            </div>
          )}
          {aiState.answer && (
            <div className="mb-2">
              <p className="text-[13px] text-gray-400 font-medium mb-1">AI 답변</p>
              <p className="text-[15px] text-gray-700 leading-relaxed">{aiState.answer}</p>
            </div>
          )}
          {aiState.references && aiState.references.length > 0 && (
            <SourceCarousel references={aiState.references} />
          )}
        </div>
      );
    }

    return null;
  };

  // OOS이거나 api_pending일 때는 유사사례/이관카드 숨김
  const isOosLike = aiState?.status === 'oos' || aiState?.status === 'api_pending';

  return (
    <div className="flex flex-col gap-3 h-full overflow-y-auto">
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-7 h-7 bg-gradient-to-br from-blue-500 to-blue-700 rounded-lg flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M13 10V3L4 14h7v7l9-11h-7z"
              />
            </svg>
          </div>
          <h3 className="text-[15px] font-semibold text-gray-700">AI 분석</h3>
        </div>
        {renderAIContent()}
      </div>

      {/* OOS/api_pending일 때 유사사례 숨김 */}
      {!isOosLike && similarCases && similarCases.length > 0 && (
        <SimilarCasesCard cases={similarCases} />
      )}

      {/* action_required일 때만 이관카드 표시, 나머지는 숨김 */}
      {(!isOosLike || aiState?.oos_type === 'action_required') &&
        transferData && transferData.length > 0 && (
          <TransferCard institutions={transferData} />
      )}
    </div>
  );
};

export default AICard;

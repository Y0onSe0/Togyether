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
        { label: '선별진료소 찾기', url: 'https://www.hira.or.kr/rd/hosp/getHospList.do', desc: '건강보험심사평가원' },
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

// ── api_pending: 예방접종 링크 안내 카드 ─────────────────────────────
const ApiPendingCard = ({ query, category }) => {
  const LINKS = {
    '예방접종': [
      { label: '예방접종도우미', url: 'https://nip.kdca.go.kr' },
      { label: '이상반응 신고',  url: 'https://nip.kdca.go.kr/irhp/' },
    ],
    '감염병 통계·현황': [
      { label: '질병관리청 감염병 현황', url: 'https://www.kdca.go.kr/npt/biz/npp/portal/nppPblctDtaView.do' },
    ],
    '해외/검역 정보 문의': [
      { label: '해외감염병 NOW',   url: 'https://해외감염병now.kr' },
      { label: '검역정보 포털',    url: 'https://quarantine.kdca.go.kr' },
    ],
  };

  const ICONS = { '예방접종': '💉', '감염병 통계·현황': '📊', '해외/검역 정보 문의': '✈️' };

  const links = LINKS[category] ?? LINKS['예방접종'];
  const icon  = ICONS[category] ?? '💉';

  return (
    <div className="bg-green-50 border border-green-200 rounded-xl p-4 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-lg">{icon}</span>
        <p className="text-[15px] font-semibold text-green-800">{category ?? '예방접종'} 문의</p>
      </div>

      {query && (
        <p className="text-[13px] text-gray-600 bg-white rounded-lg px-3 py-2 border border-green-100">
          "{query}"
        </p>
      )}

      <p className="text-[14px] text-gray-600">
        아래 공식 사이트에서 최신 정보를 확인해 주세요.
      </p>

      <div className="space-y-1.5">
        {links.map(({ label, url }) => (
          <a
            key={url}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-between px-3 py-2 bg-white rounded-lg border border-green-100 hover:border-green-300 hover:bg-green-50 transition-colors group"
          >
            <span className="text-[14px] text-green-700 font-medium group-hover:underline">🔗 {label}</span>
            <span className="text-green-400 text-[11px]">↗</span>
          </a>
        ))}
      </div>
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

import SourceCarousel from './SourceCarousel';
import SimilarCasesCard from './SimilarCasesCard';
import TransferCard from './TransferCard';

const StatusBadge = ({ category }) => {
  if (!category) return null;
  return (
    <span className="inline-block px-2 py-0.5 bg-blue-100 text-blue-700 text-[13px] font-semibold rounded-full">
      {category}
    </span>
  );
};

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

    if (aiState.status === 'oos') {
      return (
        <div className="bg-orange-50 border border-orange-200 rounded-xl p-4">
          <div className="flex items-start gap-2">
            <span className="text-lg">⚠️</span>
            <div>
              <p className="text-[15px] font-semibold text-orange-700 mb-1">범위 외 질의</p>
              <p className="text-[15px] text-gray-700 leading-relaxed">{aiState.answer}</p>
            </div>
          </div>
        </div>
      );
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

      {similarCases && similarCases.length > 0 && (
        <SimilarCasesCard cases={similarCases} />
      )}

      {transferData && transferData.length > 0 && (
        <TransferCard institutions={transferData} />
      )}
    </div>
  );
};

export default AICard;

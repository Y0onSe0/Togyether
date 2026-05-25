import { useState } from 'react';

const CaseItem = ({ item, index }) => {
  const [open, setOpen] = useState(false);
  // qa_summary: [{q: "...", a: "..."}] 배열 (백엔드에서 파싱됨)
  const qaPairs = Array.isArray(item.qa_summary) ? item.qa_summary : [];

  return (
    <div className="border border-gray-100 rounded-lg overflow-hidden mb-2">
      <button
        className="w-full text-left px-3 py-2.5 bg-gray-50 hover:bg-gray-100 transition-colors"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="flex items-center justify-between gap-2">
          <p className="text-[14px] font-medium text-gray-700 flex-1 truncate">
            사례 {index + 1}. {item.title || '제목 없음'}
          </p>
          <svg
            className={`w-3.5 h-3.5 text-gray-400 flex-shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {open && (
        <div className="px-3 py-2 bg-white space-y-2">
          {qaPairs.length > 0 ? (
            qaPairs.map((qa, qi) => (
              <div key={qi} className={qi > 0 ? 'border-t border-gray-50 pt-2' : ''}>
                <p className="text-[14px] font-semibold text-gray-700 mb-0.5">
                  Q. {qa.q || qa.question || '질문 없음'}
                </p>
                <p className="text-[13px] text-gray-600 leading-relaxed">
                  A. {qa.a || qa.answer || '답변 없음'}
                </p>
              </div>
            ))
          ) : (
            <p className="text-[13px] text-gray-400 py-1">내용 없음</p>
          )}
        </div>
      )}
    </div>
  );
};

const SimilarCasesCard = ({ cases = [] }) => {
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 3;
  const totalPages = Math.ceil(cases.length / PAGE_SIZE);
  const currentItems = cases.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  if (!cases || cases.length === 0) return null;

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
            />
          </svg>
          <h4 className="text-[15px] font-semibold text-gray-700">유사 사례</h4>
          <span className="text-[13px] text-gray-400">({cases.length}건)</span>
        </div>
        {totalPages > 1 && (
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="w-6 h-6 flex items-center justify-center rounded-full hover:bg-gray-100 disabled:opacity-30 text-gray-500 text-[13px]"
            >◀</button>
            <span className="text-[13px] text-gray-500">{page + 1}/{totalPages}</span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page === totalPages - 1}
              className="w-6 h-6 flex items-center justify-center rounded-full hover:bg-gray-100 disabled:opacity-30 text-gray-500 text-[13px]"
            >▶</button>
          </div>
        )}
      </div>

      <div>
        {currentItems.map((item, i) => (
          <CaseItem key={item.acw_id ?? (page * PAGE_SIZE + i)} item={item} index={page * PAGE_SIZE + i} />
        ))}
      </div>
    </div>
  );
};

export default SimilarCasesCard;

import { useState } from 'react';
import { createPortal } from 'react-dom';

const ChunkModal = ({ source, onClose }) => {
  const label = [
    source.document_title || source.title || source.source || '출처 문서',
    source.disease_name,
    source.section_title || source.section,
  ].filter(Boolean).join(' > ');
  const content = source.chunk_text || source.content || '';

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4"
      onClick={onClose}
    >
      {/* 배경 딤 */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />

      {/* 모달 본체 */}
      <div
        className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col z-10"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="flex items-start justify-between gap-3 px-5 pt-5 pb-4 border-b border-gray-100">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="inline-block w-2 h-2 rounded-full bg-[#1D4ED8] flex-shrink-0" />
              <p className="text-[14px] font-semibold text-gray-800 leading-snug">
                {label}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 w-7 h-7 flex items-center justify-center rounded-full hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* 청크 전문 */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {content ? (
            <p className="text-[14px] text-gray-700 leading-relaxed whitespace-pre-wrap">
              {content}
            </p>
          ) : (
            <p className="text-[14px] text-gray-400 text-center py-8">내용이 없습니다.</p>
          )}
        </div>

        {/* 푸터 */}
        <div className="px-5 py-3 border-t border-gray-100 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-600 text-[14px] font-medium rounded-lg transition-colors"
          >
            닫기
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
};

const SourceCarousel = ({ references = [] }) => {
  const [current, setCurrent] = useState(0);
  const [modalOpen, setModalOpen] = useState(false);

  if (!references || references.length === 0) return null;

  const total = references.length;
  const ref = references[current];

  const buildLabel = (ref) => [
    ref.document_title || ref.title || ref.source || '출처 문서',
    ref.disease_name,
    ref.section_title || ref.section,
  ].filter(Boolean).join(' > ');

  const title = buildLabel(ref);

  const handlePageChange = (next) => {
    setCurrent(next);
    setModalOpen(false);
  };

  return (
    <div className="mt-3">
      <p className="text-[13px] font-semibold text-gray-500 mb-1.5">
        출처 ({total}건)
      </p>

      <div className="bg-blue-50 border border-blue-100 rounded-xl px-3 py-2">
        <p className="text-[12px] text-blue-700 font-medium leading-snug truncate">{title}</p>
      </div>

      {/* 페이지네이션 */}
      {total > 1 && (
        <div className="flex items-center justify-center gap-3 mt-2">
          <button
            onClick={() => handlePageChange(Math.max(0, current - 1))}
            disabled={current === 0}
            className="text-gray-400 hover:text-gray-600 disabled:opacity-30 text-base leading-none"
          >
            ‹
          </button>
          <span className="text-[13px] text-gray-500">{current + 1} / {total}</span>
          <button
            onClick={() => handlePageChange(Math.min(total - 1, current + 1))}
            disabled={current === total - 1}
            className="text-gray-400 hover:text-gray-600 disabled:opacity-30 text-base leading-none"
          >
            ›
          </button>
        </div>
      )}

      {/* 팝업 모달 */}
      {modalOpen && (
        <ChunkModal source={ref} onClose={() => setModalOpen(false)} />
      )}
    </div>
  );
};

export default SourceCarousel;

const TransferCard = ({ institutions = [] }) => {
  if (!institutions || institutions.length === 0) return null;

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <svg className="w-4 h-4 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
        </svg>
        <h4 className="text-[15px] font-semibold text-amber-800">이관 기관 추천</h4>
        <span className="text-[13px] text-amber-600">({institutions.length}건)</span>
      </div>

      <div className="space-y-2">
        {institutions.map((inst, i) => (
          <div key={i} className="bg-white rounded-lg border border-amber-100 px-3 py-2.5">
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                {/* org_name: 기관명, dept_name: 부서명 */}
                <p className="text-[14px] font-semibold text-gray-800 truncate">
                  {inst.org_name || inst.institution_name || inst.name || '기관명'}
                </p>
                {(inst.dept_name || inst.department) && (
                  <p className="text-[13px] text-gray-500 mt-0.5">
                    {inst.dept_name || inst.department}
                  </p>
                )}
                {inst.description_summary && (
                  <p className="text-[13px] text-gray-400 mt-1 leading-relaxed line-clamp-2">
                    {inst.description_summary}
                  </p>
                )}
              </div>
              <div className="text-right flex-shrink-0">
                <p className="text-[14px] font-bold text-[#1E40AF]">
                  {inst.phone || inst.phone_number || '-'}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default TransferCard;

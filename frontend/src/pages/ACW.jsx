import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import GNB from '../components/GNB';
import { getCall } from '../api/calls';
import { initACW, generateACW, saveACW, getCategories } from '../api/acw';

const CUSTOMER_TYPES = [
  { value: 'citizen', label: '일반시민' },
  { value: 'medical', label: '의료기관' },
  { value: 'other',   label: '기타' },
];

const AI_USED_OPTIONS = [
  { value: 'yes',     label: 'AI 주도' },
  { value: 'partial', label: '부분 활용' },
  { value: 'no',      label: '미활용' },
];

const StarRating = ({ value, onChange }) => (
  <div className="flex gap-1">
    {[1, 2, 3, 4, 5].map((star) => (
      <button
        key={star}
        type="button"
        onClick={() => onChange(star)}
        className={`text-2xl transition-colors ${star <= value ? 'text-yellow-400' : 'text-gray-200 hover:text-yellow-300'}`}
      >
        ★
      </button>
    ))}
  </div>
);

const SectionTitle = ({ number, title }) => (
  <div className="flex items-center gap-2 mb-3">
    <span className="w-6 h-6 rounded-full bg-[#1E40AF] text-white text-[13px] flex items-center justify-center font-bold flex-shrink-0">
      {number}
    </span>
    <h3 className="text-[15px] font-semibold text-gray-700">{title}</h3>
  </div>
);

const ACWTimer = () => {
  const [seconds, setSeconds] = useState(0);
  const intervalRef = useRef(null);

  useEffect(() => {
    intervalRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(intervalRef.current);
  }, []);

  const format = (s) => {
    const m = Math.floor(s / 60).toString().padStart(2, '0');
    const sec = (s % 60).toString().padStart(2, '0');
    return `${m}:${sec}`;
  };

  return (
    <div className="flex items-center gap-2 bg-orange-50 border border-orange-200 rounded-lg px-3 py-1.5">
      <div className="w-2 h-2 bg-orange-500 rounded-full animate-pulse" />
      <span className="text-[13px] text-orange-600 font-medium">ACW</span>
      <span className="font-mono text-[15px] font-bold text-orange-700">{format(seconds)}</span>
    </div>
  );
};

// 중분류 멀티셀렉트 태그 컴포넌트
const MultiSelectDropdown = ({ options, selected, onChange, placeholder }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const toggle = (val) => {
    if (selected.includes(val)) {
      onChange(selected.filter((v) => v !== val));
    } else {
      onChange([...selected, val]);
    }
  };

  const remove = (val, e) => {
    e.stopPropagation();
    onChange(selected.filter((v) => v !== val));
  };

  return (
    <div className="relative" ref={ref}>
      <div
        onClick={() => setOpen((v) => !v)}
        className="w-full min-h-[38px] px-3 py-2 border border-gray-200 rounded-lg text-[15px] bg-white cursor-pointer flex flex-wrap gap-1 items-center focus:outline-none"
      >
        {selected.length === 0 ? (
          <span className="text-gray-400">{placeholder}</span>
        ) : (
          selected.map((val) => (
            <span
              key={val}
              className="inline-flex items-center gap-1 bg-blue-100 text-blue-700 text-[13px] px-2 py-0.5 rounded-full"
            >
              {val}
              <button type="button" onClick={(e) => remove(val, e)} className="hover:text-red-500">×</button>
            </span>
          ))
        )}
      </div>
      {open && options.length > 0 && (
        <div className="absolute z-20 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
          {options.map((opt) => (
            <label
              key={opt}
              className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 cursor-pointer text-[15px]"
            >
              <input
                type="checkbox"
                checked={selected.includes(opt)}
                onChange={() => toggle(opt)}
                className="accent-[#1E40AF]"
              />
              {opt}
            </label>
          ))}
        </div>
      )}
    </div>
  );
};

const ACW = () => {
  const { callId } = useParams();
  const navigate = useNavigate();
  const [callData, setCallData] = useState(null);
  const [initData, setInitData] = useState(null);   // Step A: ai_guidance, transcript
  const [genData,  setGenData]  = useState(null);   // Step B: LLM 자동 생성 필드
  const [generating, setGenerating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // 카테고리 마스터 데이터
  const [categoryMaster, setCategoryMaster] = useState([]);

  const [form, setForm] = useState({
    title: '',
    customerType: 'citizen',
    customerTypeCustom: '',
    categoryType: '',        // 감염병 | 접수처리 | 범위외
    categoryMajor: '',       // 대분류
    categoryMidList: [],     // 중분류 (복수 선택)
    diseaseName: '',
    isTransferred: false,    // false = 없음, true = 있음
    transferTarget: '',
    question: '',
    answer: '',
    resolved: true,
    agentUsedAi: 'yes',      // yes | partial | no
    satisfaction: 0,
    memo: '',
  });

  // 카테고리 마스터 로드
  useEffect(() => {
    getCategories()
      .then((data) => setCategoryMaster(data.categories || []))
      .catch(() => {
        // API 실패 시 DB 설계서 기반 기본값 사용
        setCategoryMaster([
          { category: '감염병', major: '감염병 정보 문의', mid: '감염병기본정보' },
          { category: '감염병', major: '감염병 정보 문의', mid: '증상·건강상태' },
          { category: '감염병', major: '감염병 정보 문의', mid: '소독·위생' },
          { category: '감염병', major: '감염병 정보 문의', mid: '독감·계절질환' },
          { category: '감염병', major: '감염병 정보 문의', mid: '백신' },
          { category: '감염병', major: '감염병 정보 문의', mid: '치료제·의약품' },
          { category: '감염병', major: '감염병 정보 문의', mid: '예방수칙·거리두기' },
          { category: '감염병', major: '감염병 정보 문의', mid: '항균·방역용품' },
          { category: '감염병', major: '감염병 지침 문의', mid: '감염병신고안내' },
          { category: '감염병', major: '해외/검역 정보 문의', mid: '여행·입국' },
          { category: '감염병', major: '감염병 통계·현황', mid: '국내외발생현황' },
          { category: '접수처리', major: '행정처리', mid: '권한관리' },
          { category: '접수처리', major: '행정처리', mid: '시스템오류 처리' },
          { category: '접수처리', major: '행정처리', mid: '환자정보확인' },
          { category: '접수처리', major: '행정처리', mid: '감염병신고 접수' },
          { category: '접수처리', major: '행정처리', mid: '기타행정처리' },
          { category: '범위외', major: '범위외', mid: '범위외' },
        ]);
      });
  }, []);

  // 통화 정보 로드 + ACW init (Step A) + generate (Step B)
  useEffect(() => {
    const load = async () => {
      // ① Step A: init — transcript + ai_guidance 확보
      let initRes = null;
      try {
        initRes = await initACW(callId);
        setInitData(initRes);
      } catch (err) {
        console.error('[ACW init 실패]', err?.response?.status, err?.response?.data);
      }

      // ② 통화 정보 조회 (메타데이터 + conversation_history)
      try {
        const data = await getCall(callId);
        setCallData(data);
      } catch (err) {
        console.error('[통화 정보 조회 실패]', err?.response?.status, err?.response?.data);
      }

      setLoading(false);

      // ③ Step B: generate — LLM으로 ACW 필드 자동 생성 (비동기, 로딩 별도 표시)
      if (initRes) {
        setGenerating(true);
        try {
          const gen = await generateACW(callId);
          setGenData(gen);

          // generate 결과로 폼 자동 채우기
          const firstQA = gen.qa_summary?.[0];
          setForm((prev) => ({
            ...prev,
            title:            gen.title            || prev.title,
            customerType:     gen.customer_type    || prev.customerType,
            customerTypeCustom: gen.customer_type_custom || '',
            categoryType:     gen.category         || prev.categoryType,
            categoryMajor:    gen.category_major   || prev.categoryMajor,
            categoryMidList:  gen.category_mid_list?.length ? gen.category_mid_list : prev.categoryMidList,
            diseaseName:      gen.disease_name     || prev.diseaseName,
            isTransferred:    gen.is_transferred   ?? prev.isTransferred,
            transferTarget:   gen.transfer_target  || prev.transferTarget,
            question:         firstQA?.q           || prev.question,
            answer:           firstQA?.a           || prev.answer,
          }));
        } catch (err) {
          console.error('[ACW generate 실패]', err?.response?.status, err?.response?.data);
        } finally {
          setGenerating(false);
        }
      }
    };
    load();
  }, [callId]);

  // 카테고리 연동 계산
  const categoryTypes = [...new Set(categoryMaster.map((r) => r.category))];

  const majorOptions = form.categoryType
    ? [...new Set(categoryMaster.filter((r) => r.category === form.categoryType).map((r) => r.major))]
    : [];

  const midOptions = form.categoryMajor
    ? [...new Set(categoryMaster.filter((r) => r.category === form.categoryType && r.major === form.categoryMajor).map((r) => r.mid))]
    : [];

  const handleChange = (field, value) => {
    setForm((prev) => {
      const next = { ...prev, [field]: value };
      // 카테고리 변경 시 하위 초기화
      if (field === 'categoryType') {
        next.categoryMajor = '';
        next.categoryMidList = [];
      }
      if (field === 'categoryMajor') {
        next.categoryMidList = [];
      }
      return next;
    });
  };

  const buildPayload = () => {
    // qa_summary: 폼에 입력된 Q/A가 있으면 우선 사용, 없으면 genData 전체 사용
    let qaSummary = [];
    if (form.question || form.answer) {
      qaSummary = [{ q: form.question, a: form.answer }];
    } else if (genData?.qa_summary?.length) {
      qaSummary = genData.qa_summary;
    }

    return {
      title: form.title,
      customer_type: form.customerType,
      customer_type_custom: form.customerType === 'other' ? form.customerTypeCustom : null,
      category: form.categoryType,
      category_major: form.categoryMajor,
      category_mid: form.categoryMidList[0] || null,
      category_mid_list: form.categoryMidList,
      disease_name: form.diseaseName,
      is_transferred: form.isTransferred,
      transfer_target: form.isTransferred ? form.transferTarget : null,
      qa_summary: qaSummary,
      ai_response_summary: genData?.ai_response_summary || null,
      is_resolved: form.resolved,
      agent_used_ai: form.agentUsedAi,
      satisfaction: form.satisfaction || null,
      agent_memo: form.memo,
      keywords: genData?.keywords || [],
      // ★ ai_guidance 저장 (통화 중 AI가 처리한 내역)
      ai_guidance: initData?.ai_guidance || null,
    };
  };

  const handleSubmit = async () => {
    if (!form.title.trim()) {
      alert('제목을 입력해주세요.');
      return;
    }
    setSaving(true);
    try {
      await saveACW(callId, buildPayload());
      navigate('/main');
    } catch (err) {
      console.error('ACW 저장 실패:', err);
      alert('저장에 실패했습니다. 다시 시도해주세요.');
    } finally {
      setSaving(false);
    }
  };

  const conversation = callData?.conversation_history || [];
  const meta        = callData;
  const aiGuidance  = initData?.ai_guidance || null;   // initACW에서 가져옴

  const formatDuration = (secs) => {
    if (!secs) return '-';
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}분 ${s}초`;
  };

  // 공통 input 스타일
  const inputCls = 'w-full px-3 py-2 border border-gray-200 rounded-lg text-[15px] focus:outline-none focus:ring-2 focus:ring-blue-300';
  const selectCls = 'w-full px-3 py-2 border border-gray-200 rounded-lg text-[15px] focus:outline-none focus:ring-2 focus:ring-blue-300 bg-white';
  const labelCls = 'text-[13px] text-gray-500 font-medium mb-1 block';

  return (
    <div className="min-h-screen bg-gray-50">
      <GNB />

      {/* ACW 전용 헤더 */}
      <div className="fixed top-[52px] left-0 right-0 bg-white border-b border-gray-200 z-40 px-6 py-3 flex items-center gap-4">
        <div>
          <h2 className="text-[18px] font-bold text-gray-800">ACW 카드 작성</h2>
          <p className="text-[13px] text-gray-400">통화 ID: {callId}</p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <ACWTimer />
          <button
            onClick={handleSubmit}
            disabled={saving}
            className="px-5 py-2 bg-[#1E40AF] hover:bg-blue-800 text-white text-[15px] font-semibold rounded-xl transition-colors disabled:opacity-60"
          >
            {saving ? '저장 중...' : '완료'}
          </button>
        </div>
      </div>

      {/* 본문 */}
      <div className="pt-28 flex h-screen overflow-hidden">
        {/* 좌측: 대화 전문 */}
        <div className="w-[42%] border-r border-gray-200 bg-white overflow-y-auto p-5">
          <h3 className="text-[15px] font-semibold text-gray-700 mb-4 flex items-center gap-2">
            <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
              />
            </svg>
            대화 전문
          </h3>
          {loading ? (
            <div className="flex items-center justify-center h-32 text-gray-400 text-[15px]">불러오는 중...</div>
          ) : conversation.length === 0 ? (
            <div className="text-[15px] text-gray-400 text-center py-12">대화 내역이 없습니다.</div>
          ) : (
            <div className="space-y-3">
              {conversation.map((msg, i) => {
                const isAgent = msg.role === 'agent' || msg.speaker === '상담사';
                return (
                  <div key={i} className={`flex gap-2 ${isAgent ? 'flex-row-reverse' : ''}`}>
                    <div className={`text-[13px] flex-shrink-0 mt-1 ${isAgent ? 'text-blue-500' : 'text-gray-400'}`}>
                      {isAgent ? '🎧' : '👤'}
                    </div>
                    <div className={`px-3 py-2 rounded-xl text-[14px] leading-relaxed max-w-[80%] ${
                      isAgent ? 'bg-blue-50 text-blue-900' : 'bg-gray-50 text-gray-700'
                    }`}>
                      {msg.content || msg.text || msg.message}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 우측: ACW 폼 */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">

          {/* Section 1: 통화 메타데이터 */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
            <SectionTitle number="1" title="통화 메타데이터" />
            <div className="grid grid-cols-2 gap-3">
              {[
                ['통화 ID',  meta?.call_id || callId],
                ['상담사',   meta?.agent_name || '-'],
                ['시작 시각', meta?.started_at ? new Date(meta.started_at).toLocaleString('ko-KR') : '-'],
                ['종료 시각', meta?.ended_at   ? new Date(meta.ended_at).toLocaleString('ko-KR')   : '-'],
                ['통화 시간', formatDuration(meta?.duration_sec)],
                ['상태',     meta?.status || '-'],
              ].map(([label, value]) => (
                <div key={label} className="bg-gray-50 rounded-lg px-3 py-2">
                  <p className="text-[13px] text-gray-400 mb-0.5">{label}</p>
                  <p className="text-[15px] text-gray-700 font-medium">{value}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Section 2: 통화 기본 정보 */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
            <SectionTitle number="2" title="통화 기본 정보" />
            <div className="space-y-4">

              {/* 제목 */}
              <div>
                <label className={labelCls}>제목 *</label>
                <input
                  type="text"
                  value={form.title}
                  onChange={(e) => handleChange('title', e.target.value)}
                  placeholder="상담 제목 입력"
                  className={inputCls}
                />
              </div>

              {/* 고객 유형 */}
              <div>
                <label className={labelCls}>고객 유형</label>
                <div className="flex gap-4 flex-wrap">
                  {CUSTOMER_TYPES.map((type) => (
                    <label key={type.value} className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        name="customerType"
                        value={type.value}
                        checked={form.customerType === type.value}
                        onChange={() => handleChange('customerType', type.value)}
                        className="accent-[#1E40AF]"
                      />
                      <span className="text-[15px] text-gray-700">{type.label}</span>
                    </label>
                  ))}
                </div>
                {form.customerType === 'other' && (
                  <input
                    type="text"
                    value={form.customerTypeCustom}
                    onChange={(e) => handleChange('customerTypeCustom', e.target.value)}
                    placeholder="고객 유형 직접 입력"
                    className={`mt-2 ${inputCls}`}
                  />
                )}
              </div>

              {/* 카테고리 → 대분류 → 중분류 3단계 */}
              <div className="grid grid-cols-3 gap-3">
                {/* 카테고리 */}
                <div>
                  <label className={labelCls}>카테고리</label>
                  <select
                    value={form.categoryType}
                    onChange={(e) => handleChange('categoryType', e.target.value)}
                    className={selectCls}
                  >
                    <option value="">선택</option>
                    {categoryTypes.map((cat) => (
                      <option key={cat} value={cat}>{cat}</option>
                    ))}
                  </select>
                </div>

                {/* 대분류 */}
                <div>
                  <label className={labelCls}>대분류</label>
                  <select
                    value={form.categoryMajor}
                    onChange={(e) => handleChange('categoryMajor', e.target.value)}
                    disabled={!form.categoryType}
                    className={`${selectCls} disabled:bg-gray-50 disabled:text-gray-400`}
                  >
                    <option value="">선택</option>
                    {majorOptions.map((maj) => (
                      <option key={maj} value={maj}>{maj}</option>
                    ))}
                  </select>
                </div>

                {/* 중분류 (멀티셀렉트) */}
                <div>
                  <label className={labelCls}>
                    중분류 <span className="text-gray-400">(복수 선택)</span>
                  </label>
                  <MultiSelectDropdown
                    options={midOptions}
                    selected={form.categoryMidList}
                    onChange={(val) => handleChange('categoryMidList', val)}
                    placeholder={form.categoryMajor ? '선택' : '대분류 먼저 선택'}
                  />
                </div>
              </div>

              {/* 질병명 */}
              <div>
                <label className={labelCls}>질병명</label>
                <input
                  type="text"
                  value={form.diseaseName}
                  onChange={(e) => handleChange('diseaseName', e.target.value)}
                  placeholder="질병명 입력"
                  className={inputCls}
                />
              </div>

              {/* 이관 여부 */}
              <div>
                <label className={labelCls}>이관 여부</label>
                <div className="flex gap-4">
                  {[['있음', true], ['없음', false]].map(([label, val]) => (
                    <label key={label} className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        checked={form.isTransferred === val}
                        onChange={() => handleChange('isTransferred', val)}
                        className="accent-[#1E40AF]"
                      />
                      <span className="text-[15px] text-gray-700">{label}</span>
                    </label>
                  ))}
                </div>
                {form.isTransferred && (
                  <input
                    type="text"
                    value={form.transferTarget}
                    onChange={(e) => handleChange('transferTarget', e.target.value)}
                    placeholder="이관 기관명 입력"
                    className={`mt-2 ${inputCls}`}
                  />
                )}
              </div>
            </div>
          </div>

          {/* Section 3: AI 상담 요약 (generate 결과 — 읽기 전용) */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
            <SectionTitle number="3" title="AI 상담 요약" />
            {generating ? (
              <div className="flex items-center gap-2 text-[15px] text-gray-400 py-2">
                <div className="w-4 h-4 border-2 border-blue-200 border-t-[#1E40AF] rounded-full animate-spin" />
                AI 요약 생성 중...
              </div>
            ) : genData?.ai_response_summary ? (
              <div className="bg-gray-50 rounded-lg px-3 py-3">
                <p className="text-[13px] text-gray-400 mb-1">AI 활용 요약 (읽기 전용)</p>
                <p className="text-[15px] text-gray-700 leading-relaxed">{genData.ai_response_summary}</p>
              </div>
            ) : (
              <p className="text-[15px] text-gray-400">AI 요약이 없습니다. (통화 중 AI 안내 미사용)</p>
            )}
          </div>

          {/* Section 4: AI 처리 내역 */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
            <SectionTitle number="4" title="AI 처리 내역" />
            {aiGuidance ? (
              <div className="space-y-3">

                {/* 상태 + 질병명 뱃지 */}
                <div className="flex items-center gap-2">
                  <span className={`text-[12px] font-semibold px-2 py-0.5 rounded-full ${
                    aiGuidance.is_oos
                      ? 'bg-orange-100 text-orange-700'
                      : aiGuidance.answer
                        ? 'bg-green-100 text-green-700'
                        : 'bg-gray-100 text-gray-500'
                  }`}>
                    {aiGuidance.is_oos ? '범위 외' : aiGuidance.answer ? 'AI 안내 완료' : '결과 없음'}
                  </span>
                  {aiGuidance.disease_name && (
                    <span className="text-[12px] bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-semibold">
                      {aiGuidance.disease_name}
                    </span>
                  )}
                </div>

                {/* 인식된 문의 */}
                {aiGuidance.query && (
                  <div className="bg-gray-50 rounded-lg px-3 py-2.5">
                    <p className="text-[12px] text-gray-400 mb-1">인식된 문의</p>
                    <p className="text-[14px] text-gray-700 font-medium leading-relaxed">
                      {aiGuidance.query}
                    </p>
                  </div>
                )}

                {/* AI 안내 내용 */}
                {(aiGuidance.answer || aiGuidance.oos_reason) && (
                  <div className="bg-blue-50 rounded-lg px-3 py-2.5 border-l-2 border-[#1E40AF]">
                    <p className="text-[12px] text-blue-500 mb-1">
                      {aiGuidance.is_oos ? 'OOS 사유' : 'AI 안내 내용'}
                    </p>
                    <p className="text-[14px] text-blue-900 leading-relaxed">
                      {aiGuidance.is_oos ? aiGuidance.oos_reason : aiGuidance.answer}
                    </p>
                  </div>
                )}

                {/* 참조 문서 출처 */}
                {aiGuidance.sources && aiGuidance.sources.length > 0 && (
                  <div>
                    <p className="text-[12px] text-gray-400 mb-1.5">참조 문서 ({aiGuidance.sources.length}건)</p>
                    <div className="space-y-1.5">
                      {aiGuidance.sources.map((src, i) => (
                        <div
                          key={i}
                          className="flex items-start gap-2 bg-gray-50 rounded-lg px-3 py-2 border border-gray-100"
                        >
                          <span className="text-[12px] text-gray-400 mt-0.5 flex-shrink-0">
                            [{i + 1}]
                          </span>
                          <div className="min-w-0">
                            <p className="text-[13px] font-medium text-gray-700 truncate">
                              {src.document_title || '문서 제목 없음'}
                            </p>
                            {src.section_title && (
                              <p className="text-[12px] text-gray-400 truncate mt-0.5">
                                {src.section_title}
                              </p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-[15px] text-gray-400">AI 처리 내역이 없습니다.</p>
            )}
          </div>

          {/* Section 5: Q/A */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
            <SectionTitle number="5" title="핵심 발화 추출" />
            <div className="space-y-3">
              <div>
                <label className={labelCls}>Q (고객 질문)</label>
                <textarea
                  value={form.question}
                  onChange={(e) => handleChange('question', e.target.value)}
                  placeholder="고객 핵심 질문 입력"
                  rows={3}
                  className={`${inputCls} resize-none`}
                />
              </div>
              <div>
                <label className={labelCls}>A (제공한 답변)</label>
                <textarea
                  value={form.answer}
                  onChange={(e) => handleChange('answer', e.target.value)}
                  placeholder="제공한 답변 내용 입력"
                  rows={3}
                  className={`${inputCls} resize-none`}
                />
              </div>
            </div>
          </div>

          {/* Section 6: 처리 결과 */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
            <SectionTitle number="6" title="처리 결과" />
            <div className="grid grid-cols-3 gap-4">
              {/* 해결 여부 */}
              <div>
                <label className={labelCls}>해결 여부 *</label>
                <div className="flex gap-3">
                  {[['해결', true], ['미해결', false]].map(([label, val]) => (
                    <label key={label} className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        checked={form.resolved === val}
                        onChange={() => handleChange('resolved', val)}
                        className="accent-[#1E40AF]"
                      />
                      <span className="text-[14px] text-gray-700">{label}</span>
                    </label>
                  ))}
                </div>
              </div>

              {/* AI 활용 여부 */}
              <div>
                <label className={labelCls}>AI 활용 여부 *</label>
                <div className="flex flex-col gap-1">
                  {AI_USED_OPTIONS.map((opt) => (
                    <label key={opt.value} className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        checked={form.agentUsedAi === opt.value}
                        onChange={() => handleChange('agentUsedAi', opt.value)}
                        className="accent-[#1E40AF]"
                      />
                      <span className="text-[14px] text-gray-700">{opt.label}</span>
                    </label>
                  ))}
                </div>
              </div>

              {/* 만족도 */}
              <div>
                <label className={labelCls}>AI 답변 만족도</label>
                <StarRating value={form.satisfaction} onChange={(v) => handleChange('satisfaction', v)} />
              </div>
            </div>
          </div>

          {/* Section 7: 메모 */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 mb-6">
            <SectionTitle number="7" title="상담사 메모" />
            <textarea
              value={form.memo}
              onChange={(e) => handleChange('memo', e.target.value)}
              placeholder="추가 메모 사항을 입력하세요"
              rows={4}
              className={`${inputCls} resize-none`}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default ACW;

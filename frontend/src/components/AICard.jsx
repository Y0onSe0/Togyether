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
        <span className="text-amber-600">📞</span>
        <span className="font-semibold">1644-1407</span>
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
  </div>
);

/** unrelated: 완전 범위 외 */
const GOV_KEYWORDS = ['정부', '민원', '행정', '공공', '국가', '지자체', '지방자치', '시청', '구청', '군청', '동사무소', '주민센터', '세금', '복지', '연금', '건강보험', '국민'];
const OosUnrelated = ({ query, oos_reason }) => {
  const combined = `${query || ''} ${oos_reason || ''}`;
  const isGovRelated = GOV_KEYWORDS.some(kw => combined.includes(kw));
  return (
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
      {isGovRelated && (
        <p className="text-[13px] text-gray-500">→ ☎ 110 (정부민원안내 콜센터)</p>
      )}
    </div>
  );
};

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
    <p className="text-[14px] text-gray-700">담당 기관·부서로 연결이 필요합니다. 아래 추천 기관을 확인하세요.</p>
  </div>
);

// ── 검역 감염병 정보 사전 ─────────────────────────────────────────────
const DISEASE_INFO = {
  '뎅기열':       { symptoms: '고열, 두통, 근육통, 발진', prevention: '모기 기피제·긴소매 착용, 모기장 사용', action: '귀국 후 증상 시 의료기관 방문 및 해외 여행력 고지' },
  '콜레라':       { symptoms: '심한 수양성 설사, 구토, 탈수', prevention: '안전한 음식·물 섭취, 손 위생 철저', action: '경구수액 보충, 즉시 의료기관 방문' },
  '황열':         { symptoms: '발열, 황달, 출혈', prevention: '황열 예방접종 필수 (입국 요건 국가 있음), 모기 차단', action: '귀국 후 증상 시 즉시 의료기관 방문' },
  '말라리아':     { symptoms: '오한, 발열, 발한이 주기적으로 반복', prevention: '예방약 복용, 모기 차단', action: '귀국 후 발열 시 의료기관 방문 및 여행력 고지' },
  '지카바이러스': { symptoms: '발열, 발진, 관절통, 결막염 (대부분 경미)', prevention: '모기 차단, 임산부 유행지역 여행 자제', action: '임신 중이거나 임신 예정이면 의사 상담 필수' },
  '지카':         { symptoms: '발열, 발진, 관절통, 결막염 (대부분 경미)', prevention: '모기 차단, 임산부 유행지역 여행 자제', action: '임신 중이거나 임신 예정이면 의사 상담 필수' },
  '에볼라':       { symptoms: '갑작스러운 고열, 심한 두통, 출혈', prevention: '감염자 접촉 금지, 야생동물 접촉 주의', action: '귀국 후 21일 이내 증상 시 즉시 격리·신고' },
  '에볼라바이러스': { symptoms: '갑작스러운 고열, 심한 두통, 출혈', prevention: '감염자 접촉 금지, 야생동물 접촉 주의', action: '귀국 후 21일 이내 증상 시 즉시 격리·신고' },
  '엠폭스':       { symptoms: '발열, 림프절 부종, 특징적 수포성 발진', prevention: '피부 병변 있는 사람과 밀접 접촉 금지', action: '귀국 후 21일 이내 증상 시 의료기관 방문 및 해외력 고지' },
  '원숭이두창':   { symptoms: '발열, 림프절 부종, 특징적 수포성 발진', prevention: '피부 병변 있는 사람과 밀접 접촉 금지', action: '귀국 후 21일 이내 증상 시 의료기관 방문 및 해외력 고지' },
  '메르스':       { symptoms: '발열, 기침, 호흡곤란', prevention: '낙타 접촉 금지, 손 위생', action: '귀국 후 14일 이내 발열·호흡기 증상 시 1339 신고 후 이동' },
  '중동호흡기증후군': { symptoms: '발열, 기침, 호흡곤란', prevention: '낙타 접촉 금지, 손 위생', action: '귀국 후 14일 이내 발열·호흡기 증상 시 1339 신고 후 이동' },
  '사스':         { symptoms: '발열, 기침, 호흡곤란', prevention: '마스크 착용, 환자 접촉 금지', action: '귀국 후 증상 시 즉시 1339 신고' },
  '페스트':       { symptoms: '갑작스러운 고열, 림프절 비대(가래톳)', prevention: '쥐·벼룩 접촉 금지', action: '즉시 의료기관 방문, 치료 시 항생제 사용' },
  '폴리오':       { symptoms: '발열, 팔다리 마비 (불현성 감염 多)', prevention: '폴리오 예방접종 확인', action: '예방접종 미완료자 귀국 후 추가 접종 권고' },
  '소아마비':     { symptoms: '발열, 팔다리 마비 (불현성 감염 多)', prevention: '폴리오 예방접종 확인', action: '예방접종 미완료자 귀국 후 추가 접종 권고' },
  '홍역':         { symptoms: '고열, 콧물, 결막염, 특징적 발진', prevention: 'MMR 예방접종 2회 완료 확인', action: '귀국 후 21일 이내 증상 시 마스크 착용 후 의료기관 방문' },
  '라싸열':       { symptoms: '발열, 두통, 인후통, 출혈', prevention: '설치류 접촉 금지, 위생 철저', action: '귀국 후 21일 이내 증상 시 즉시 격리·신고' },
  '치쿤구니야':   { symptoms: '갑작스러운 고열, 심한 관절통', prevention: '모기 기피제·긴소매 착용', action: '귀국 후 증상 시 의료기관 방문 및 해외 여행력 고지' },
  '치쿤구니아열': { symptoms: '갑작스러운 고열, 심한 관절통·관절염, 두통, 근육통, 발진', prevention: '모기 기피제·긴소매 착용, 모기장 사용', action: '귀국 후 증상 시 의료기관 방문 및 해외 여행력 고지, 관절통은 수주~수개월 지속 가능' },
  '동물인플루엔자인체감염증': { symptoms: '발열, 기침, 호흡곤란, 결막염 (조류 접촉 후 수일 내 발생)', prevention: '가금류·야생조류 접촉 금지, 조류 분변 근처 접근 자제, 손 위생 철저', action: '귀국 후 10일 이내 발열·호흡기 증상 시 1339 신고 후 이동, 항바이러스제 조기 투여 필요' },
  '코로나':       { symptoms: '발열, 기침, 호흡곤란, 후각·미각 이상', prevention: '마스크 착용, 손 위생, 예방접종', action: '증상 시 자가격리 후 의료기관 방문' },
  '코로나19':     { symptoms: '발열, 기침, 호흡곤란, 후각·미각 이상', prevention: '마스크 착용, 손 위생, 예방접종', action: '증상 시 자가격리 후 의료기관 방문' },
};

const DEFAULT_DISEASE_INFO = {
  symptoms: '발열, 소화기·호흡기 증상 등 (병명에 따라 다름)',
  prevention: '현지 음식·물 위생 관리, 모기 등 매개체 차단, 손 위생 철저',
  action: '귀국 후 증상 발생 시 의료기관 방문 및 해외 여행력 반드시 고지',
};

/** 병명 클릭 시 펼쳐지는 상세 정보 */
const DiseaseDetail = ({ disease }) => {
  const info = DISEASE_INFO[disease] || DEFAULT_DISEASE_INFO;
  return (
    <div className="mt-1.5 bg-teal-50 rounded-lg px-3 py-2 space-y-1 text-[12px]">
      <p><span className="font-semibold text-teal-700">증상</span> <span className="text-gray-600">{info.symptoms}</span></p>
      <p><span className="font-semibold text-teal-700">예방</span> <span className="text-gray-600">{info.prevention}</span></p>
      <p><span className="font-semibold text-teal-700">조치</span> <span className="text-gray-600">{info.action}</span></p>
    </div>
  );
};

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
  const [state, setState]       = useState('loading');
  const [data, setData]         = useState(null);
  const [expanded, setExpanded] = useState(null); // 펼쳐진 병명

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
                <div key={i}>
                  <button
                    onClick={() => setExpanded(expanded === i ? null : i)}
                    className="w-full flex items-center justify-between bg-white rounded-lg px-3 py-2 border border-teal-100 hover:border-teal-300 hover:bg-teal-50 transition-colors text-left"
                  >
                    <span className="text-[14px] font-medium text-gray-800">⚠️ {item.disease}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-[12px] text-gray-400">{item.start_date} ~</span>
                      <span className="text-teal-400 text-[11px]">{expanded === i ? '▲' : '▼'}</span>
                    </div>
                  </button>
                  {expanded === i && <DiseaseDetail disease={item.disease} />}
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

// ── 히스토리 캐러셀 ────────────────────────────────────────────────────
const STATUS_LABEL = {
  success:     { text: '답변', color: 'bg-blue-100 text-blue-700' },
  oos:         { text: 'OOS',  color: 'bg-amber-100 text-amber-700' },
  api_pending: { text: 'API',  color: 'bg-green-100 text-green-700' },
  no_result:   { text: '미검색', color: 'bg-gray-100 text-gray-500' },
};

const PAGE_SIZE = 3;

const HistoryCarousel = ({ history }) => {
  const [page, setPage]     = useState(0);
  const [openIdx, setOpenIdx] = useState(null);

  if (!history || history.length === 0) return null;

  const totalPages = Math.ceil(history.length / PAGE_SIZE);
  const items = history.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  const handlePage = (dir) => {
    setPage(p => Math.min(Math.max(p + dir, 0), totalPages - 1));
    setOpenIdx(null);
  };

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
      <div className="flex items-center justify-between mb-2">
        <p className="text-[13px] font-semibold text-gray-500">
          이전 분석 ({history.length}건)
        </p>
        {totalPages > 1 && (
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => handlePage(-1)}
              disabled={page === 0}
              className="w-6 h-6 flex items-center justify-center rounded text-gray-400 hover:text-gray-600 disabled:opacity-30 text-[16px]"
            >‹</button>
            <span className="text-[12px] text-gray-400">{page + 1} / {totalPages}</span>
            <button
              onClick={() => handlePage(1)}
              disabled={page === totalPages - 1}
              className="w-6 h-6 flex items-center justify-center rounded text-gray-400 hover:text-gray-600 disabled:opacity-30 text-[16px]"
            >›</button>
          </div>
        )}
      </div>

      <div className="space-y-1.5">
        {items.map((item, i) => {
          const absIdx = page * PAGE_SIZE + i;
          const label  = STATUS_LABEL[item.status] ?? STATUS_LABEL.no_result;
          const isOpen = openIdx === absIdx;
          return (
            <div key={absIdx} className="border border-gray-100 rounded-lg overflow-hidden">
              <button
                className="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-50 transition-colors text-left"
                onClick={() => setOpenIdx(isOpen ? null : absIdx)}
              >
                <span className={`text-[11px] px-1.5 py-0.5 rounded font-medium flex-shrink-0 ${label.color}`}>
                  {label.text}
                </span>
                <span className="text-[13px] text-gray-700 truncate flex-1">
                  {item.query || item.category || '-'}
                </span>
                <span className="text-gray-300 text-[11px] flex-shrink-0">{isOpen ? '▲' : '▼'}</span>
              </button>
              {isOpen && (
                <div className="px-3 pb-3 pt-1.5 border-t border-gray-100 bg-gray-50 space-y-1.5">
                  {item.answer && (
                    <p className="text-[13px] text-gray-700 leading-relaxed">{item.answer}</p>
                  )}
                  {item.message && (
                    <p className="text-[13px] text-gray-500 italic">{item.message}</p>
                  )}
                  {item.status === 'oos' && (
                    <p className="text-[12px] text-amber-600">{item.oos_type} 유형</p>
                  )}
                  {item.references?.length > 0 && (
                    <p className="text-[12px] text-blue-500">출처 {item.references.length}건</p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ── 메인 AICard ───────────────────────────────────────────────────────
const AICard = ({ aiState, aiHistory = [], similarCases, transferData }) => {
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
      const { oos_type, oos_reason, query } = aiState;

      if (oos_type === 'action_required') return <OosActionRequired query={query} />;
      if (oos_type === 'realtime_local')  return <OosRealtimeLocal query={query} />;
      if (oos_type === 'transfer')        return <OosTransfer query={query} />;
      // unrelated (기본)
      return <OosUnrelated query={query} oos_reason={oos_reason} />;
    }

    // ── api_pending: 링크 안내 ───────────────────────────────────────
    if (aiState.status === 'api_pending') {
      return <ApiPendingCard query={aiState.query} category={aiState.category} />;
    }

    if (aiState.status === 'no_result') {
      return (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <p className="text-[15px] text-gray-500">{aiState.message || '관련 지침을 찾지 못했습니다.'}</p>
          </div>
          {aiState.category && (
            <div><StatusBadge category={aiState.category} /></div>
          )}
          {aiState.query && (
            <div>
              <p className="text-[12px] text-gray-400 font-medium mb-1">인식된 문의</p>
              <p className="text-[14px] text-gray-600 bg-white rounded-lg px-3 py-2 border border-gray-200">
                {aiState.query}
              </p>
            </div>
          )}
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

      {/* 키워드 매칭 시 이관카드 표시 (접수처리·범위외 제외) */}
      {transferData && transferData.length > 0
        && aiState?.oos_type !== 'action_required'
        && aiState?.oos_type !== 'unrelated'
        && (
        <TransferCard institutions={transferData} />
      )}

      {/* 이전 분석 히스토리 */}
      <HistoryCarousel history={aiHistory} />
    </div>
  );
};

export default AICard;

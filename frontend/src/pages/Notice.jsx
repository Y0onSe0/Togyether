import { useState, useEffect, useRef } from 'react';
import GNB from '../components/GNB';
import LNB from '../components/LNB';
import { getPressReleases, triggerCrawl, getStats } from '../api/notice';

const TABS = ['보도자료'];

const formatDate = (val) => {
  if (!val) return '-';
  return new Date(val).toLocaleDateString('ko-KR', {
    year: 'numeric', month: '2-digit', day: '2-digit',
  });
};

const formatDuration = (sec) => {
  if (!sec) return '-';
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}분 ${s}초`;
};

// ── 보도자료 탭 ──────────────────────────────────────────────
const PressTab = () => {
  const [items, setItems]   = useState([]);
  const [total, setTotal]   = useState(0);
  const [page, setPage]     = useState(1);
  const [loading, setLoading] = useState(false);
  const [crawling, setCrawling] = useState(false);
  const SIZE = 20;

  const load = async (p = 1) => {
    setLoading(true);
    try {
      const data = await getPressReleases(p, SIZE);
      setItems(data.items);
      setTotal(data.total);
      setPage(p);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(1); }, []);

  const handleCrawl = async () => {
    setCrawling(true);
    try {
      await triggerCrawl();
      setTimeout(() => { load(1); setCrawling(false); }, 3000);
    } catch {
      setCrawling(false);
    }
  };

  const totalPages = Math.ceil(total / SIZE);

  return (
    <div className="space-y-4">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <p className="text-[13px] text-gray-400">총 {total.toLocaleString()}건 · 6시간마다 자동 업데이트</p>
        <button
          onClick={handleCrawl}
          disabled={crawling}
          className="flex items-center gap-1.5 text-[13px] px-3 py-1.5 rounded-lg bg-blue-50 text-blue-600 hover:bg-blue-100 disabled:opacity-50 transition-colors"
        >
          <svg className={`w-3.5 h-3.5 ${crawling ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          {crawling ? '업데이트 중...' : '지금 업데이트'}
        </button>
      </div>

      {/* 목록 */}
      {loading ? (
        <div className="flex justify-center py-16">
          <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100">
                <th className="text-left text-[13px] font-semibold text-gray-500 px-5 py-3 w-16">번호</th>
                <th className="text-left text-[13px] font-semibold text-gray-500 px-5 py-3">제목</th>
                <th className="text-left text-[13px] font-semibold text-gray-500 px-5 py-3 w-32">담당부서</th>
                <th className="text-left text-[13px] font-semibold text-gray-500 px-5 py-3 w-28">작성일</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td colSpan={4} className="text-center text-[13px] text-gray-400 py-12">
                    데이터가 없습니다. 업데이트 버튼을 눌러보세요.
                  </td>
                </tr>
              ) : items.map((item, i) => (
                <tr key={item.id} className="border-b border-gray-50 hover:bg-blue-50/30 transition-colors">
                  <td className="text-[13px] text-gray-400 px-5 py-3.5">
                    {total - (page - 1) * SIZE - i}
                  </td>
                  <td className="px-5 py-3.5">
                    <a
                      href={item.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[14px] text-gray-800 hover:text-blue-600 hover:underline line-clamp-1 transition-colors"
                    >
                      {item.title}
                    </a>
                    {item.description && (
                      <p className="text-[12px] text-gray-400 mt-0.5 line-clamp-1">{item.description}</p>
                    )}
                  </td>
                  <td className="text-[13px] text-gray-500 px-5 py-3.5">{item.author || '-'}</td>
                  <td className="text-[13px] text-gray-500 px-5 py-3.5">{formatDate(item.published_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 페이지네이션 */}
      {totalPages > 1 && (
        <div className="flex justify-center gap-1">
          <button onClick={() => load(1)} disabled={page === 1}
            className="px-2 py-1 text-[13px] rounded text-gray-400 hover:bg-gray-100 disabled:opacity-30">처음</button>
          <button onClick={() => load(page - 1)} disabled={page === 1}
            className="px-2 py-1 text-[13px] rounded text-gray-400 hover:bg-gray-100 disabled:opacity-30">‹</button>
          {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
            const p = Math.max(1, Math.min(page - 2, totalPages - 4)) + i;
            return (
              <button key={p} onClick={() => load(p)}
                className={`px-3 py-1 text-[13px] rounded transition-colors ${p === page ? 'bg-blue-600 text-white' : 'text-gray-500 hover:bg-gray-100'}`}>
                {p}
              </button>
            );
          })}
          <button onClick={() => load(page + 1)} disabled={page === totalPages}
            className="px-2 py-1 text-[13px] rounded text-gray-400 hover:bg-gray-100 disabled:opacity-30">›</button>
          <button onClick={() => load(totalPages)} disabled={page === totalPages}
            className="px-2 py-1 text-[13px] rounded text-gray-400 hover:bg-gray-100 disabled:opacity-30">끝</button>
        </div>
      )}
    </div>
  );
};

// ── 유사 상담 사례 탭 ────────────────────────────────────────
const SimilarTab = () => {
  const [items, setItems]   = useState([]);
  const [total, setTotal]   = useState(0);
  const [page, setPage]     = useState(1);
  const [loading, setLoading] = useState(false);
  const SIZE = 20;

  const load = async (p = 1) => {
    setLoading(true);
    try {
      const data = await getSimilarCases(p, SIZE);
      setItems(data.items);
      setTotal(data.total);
      setPage(p);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(1); }, []);

  const totalPages = Math.ceil(total / SIZE);

  const categoryColor = (cat) => {
    if (!cat) return 'bg-gray-100 text-gray-500';
    if (cat.includes('감염병')) return 'bg-blue-100 text-blue-700';
    if (cat.includes('예방')) return 'bg-green-100 text-green-700';
    if (cat.includes('통계')) return 'bg-purple-100 text-purple-700';
    if (cat.includes('검역')) return 'bg-orange-100 text-orange-700';
    return 'bg-gray-100 text-gray-500';
  };

  return (
    <div className="space-y-4">
      <p className="text-[13px] text-gray-400">총 {total.toLocaleString()}건</p>

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100">
                <th className="text-left text-[13px] font-semibold text-gray-500 px-5 py-3 w-28">상담일시</th>
                <th className="text-left text-[13px] font-semibold text-gray-500 px-5 py-3 w-28">분류</th>
                <th className="text-left text-[13px] font-semibold text-gray-500 px-5 py-3 w-32">질환명</th>
                <th className="text-left text-[13px] font-semibold text-gray-500 px-5 py-3">상담 요약</th>
                <th className="text-left text-[13px] font-semibold text-gray-500 px-5 py-3 w-24">상담시간</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-center text-[13px] text-gray-400 py-12">
                    완료된 상담 데이터가 없습니다.
                  </td>
                </tr>
              ) : items.map((item) => (
                <tr key={item.call_id} className="border-b border-gray-50 hover:bg-gray-50/60 transition-colors">
                  <td className="text-[13px] text-gray-500 px-5 py-3.5">{formatDate(item.started_at)}</td>
                  <td className="px-5 py-3.5">
                    <span className={`text-[12px] font-medium px-2 py-0.5 rounded-full ${categoryColor(item.category)}`}>
                      {item.category || item.oos_type || '-'}
                    </span>
                  </td>
                  <td className="text-[13px] text-gray-700 px-5 py-3.5 font-medium">{item.disease_name || '-'}</td>
                  <td className="text-[13px] text-gray-600 px-5 py-3.5 line-clamp-1">{item.summary || '-'}</td>
                  <td className="text-[13px] text-gray-500 px-5 py-3.5">{formatDuration(item.duration_sec)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex justify-center gap-1">
          <button onClick={() => load(1)} disabled={page === 1}
            className="px-2 py-1 text-[13px] rounded text-gray-400 hover:bg-gray-100 disabled:opacity-30">처음</button>
          <button onClick={() => load(page - 1)} disabled={page === 1}
            className="px-2 py-1 text-[13px] rounded text-gray-400 hover:bg-gray-100 disabled:opacity-30">‹</button>
          {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
            const p = Math.max(1, Math.min(page - 2, totalPages - 4)) + i;
            return (
              <button key={p} onClick={() => load(p)}
                className={`px-3 py-1 text-[13px] rounded transition-colors ${p === page ? 'bg-blue-600 text-white' : 'text-gray-500 hover:bg-gray-100'}`}>
                {p}
              </button>
            );
          })}
          <button onClick={() => load(page + 1)} disabled={page === totalPages}
            className="px-2 py-1 text-[13px] rounded text-gray-400 hover:bg-gray-100 disabled:opacity-30">›</button>
          <button onClick={() => load(totalPages)} disabled={page === totalPages}
            className="px-2 py-1 text-[13px] rounded text-gray-400 hover:bg-gray-100 disabled:opacity-30">끝</button>
        </div>
      )}
    </div>
  );
};

// ── 공지 배너 컴포넌트 (하드코딩) ──────────────────────────
const BANNERS = [
  { level: 'danger',  message: '인플루엔자 유행주의보 발령 (2026.06.04) — 관련 문의 응대 지침 숙지 필수' },
  { level: 'warning', message: '에볼라바이러스병 관련 문의 급증 — 검역 절차 및 대응 매뉴얼 재확인 바랍니다' },
  { level: 'info',    message: '2026년 하반기 감염병 신고 지침이 업데이트되었습니다. 변경사항을 확인하세요' },
];

const levelStyle = {
  info:    'bg-blue-50 border-blue-200 text-blue-800',
  warning: 'bg-yellow-50 border-yellow-200 text-yellow-800',
  danger:  'bg-red-50 border-red-200 text-red-800',
};
const levelIcon  = { info: '📢', warning: '⚠️', danger: '🚨' };
const levelLabel = { info: '일반', warning: '주의', danger: '긴급' };

const BannerSection = () => (
  <div className="mb-6 space-y-2">
    {BANNERS.map((b, i) => (
      <div key={i} className={`flex items-start gap-3 px-4 py-3 rounded-xl border ${levelStyle[b.level]}`}>
        <span className="text-base mt-0.5">{levelIcon[b.level]}</span>
        <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border flex-shrink-0 ${levelStyle[b.level]}`}>
          {levelLabel[b.level]}
        </span>
        <p className="flex-1 text-[14px] font-medium">{b.message}</p>
      </div>
    ))}
  </div>
);

// ── 실시간 현황 위젯 ─────────────────────────────────────────
const StatsSection = () => {
  const [stats, setStats] = useState(null);
  const intervalRef = useRef(null);

  const load = async () => {
    try { setStats(await getStats()); } catch {}
  };

  useEffect(() => {
    load();
    intervalRef.current = setInterval(load, 30000); // 30초마다 갱신
    return () => clearInterval(intervalRef.current);
  }, []);

  const formatDur = (sec) => {
    if (!sec) return '-';
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}분 ${s}초`;
  };

  const cards = stats ? [
    { label: '오늘 인입 콜', value: stats.today_calls, unit: '건', color: 'blue', icon: '📞' },
    { label: '현재 상담 중', value: stats.active_calls, unit: '건', color: stats.active_calls > 0 ? 'green' : 'gray', icon: '🟢' },
    { label: '오늘 완료', value: stats.today_ended, unit: '건', color: 'purple', icon: '✅' },
    { label: '평균 상담 시간', value: formatDur(stats.avg_duration_sec), unit: '', color: 'orange', icon: '⏱' },
    { label: '해결률', value: stats.resolution_rate, unit: '%', color: 'teal', icon: '🎯' },
    { label: '활성 상담사', value: stats.active_agents, unit: '명', color: 'indigo', icon: '👤' },
  ] : Array(6).fill(null);

  const colorMap = {
    blue:   'bg-blue-50 text-blue-700',
    green:  'bg-green-50 text-green-700',
    gray:   'bg-gray-50 text-gray-500',
    purple: 'bg-purple-50 text-purple-700',
    orange: 'bg-orange-50 text-orange-700',
    teal:   'bg-teal-50 text-teal-700',
    indigo: 'bg-indigo-50 text-indigo-700',
  };

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[15px] font-semibold text-gray-700">콜센터 현황</h2>
        <span className="text-[12px] text-gray-400">30초마다 자동 갱신</span>
      </div>
      <div className="grid grid-cols-3 lg:grid-cols-6 gap-3">
        {cards.map((card, i) => (
          <div key={i} className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
            {card ? (
              <>
                <div className={`text-[11px] font-medium px-2 py-0.5 rounded-full w-fit mb-2 ${colorMap[card.color]}`}>
                  {card.icon} {card.label}
                </div>
                <p className="text-[22px] font-bold text-gray-800">
                  {card.value}<span className="text-[13px] font-normal text-gray-400 ml-1">{card.unit}</span>
                </p>
              </>
            ) : (
              <div className="animate-pulse space-y-2">
                <div className="h-4 bg-gray-100 rounded w-3/4" />
                <div className="h-6 bg-gray-100 rounded w-1/2" />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

// ── 메인 페이지 ──────────────────────────────────────────────
const Notice = () => {
  const [activeTab, setActiveTab] = useState(0);

  return (
    <div className="min-h-screen bg-gray-50">
      <GNB />
      <LNB />
      <div className="pt-[52px] pl-[7%] min-w-[64px]">
        <div className="p-6">
          {/* 페이지 제목 */}
          <div className="mb-5">
            <h1 className="text-[20px] font-bold text-gray-800">공지사항</h1>
            <p className="text-[13px] text-gray-400 mt-1">질병관리청 보도자료 및 콜센터 현황</p>
          </div>

          {/* 공지 배너 */}
          <BannerSection />

          {/* 실시간 현황 */}
          <StatsSection />

          {/* 탭 */}
          <div className="flex gap-1 mb-6 bg-gray-100 rounded-xl p-1 w-fit">
            {TABS.map((tab, i) => (
              <button
                key={tab}
                onClick={() => setActiveTab(i)}
                className={`px-5 py-2 rounded-lg text-[14px] font-medium transition-all ${
                  activeTab === i
                    ? 'bg-white text-[#1E40AF] shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>

          {/* 탭 콘텐츠 */}
          {activeTab === 0 && <PressTab />}
        </div>
      </div>
    </div>
  );
};

export default Notice;

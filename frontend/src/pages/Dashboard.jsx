import { useState, useEffect } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, Legend, ComposedChart, Area,
  PieChart, Pie, Cell,
} from 'recharts';
import GNB from '../components/GNB';
import LNB from '../components/LNB';
import {
  getDashboard,
  getDiseaseByDisease,
  getDiseaseTrendWithCalls,
  getDiseaseByGender,
  getDiseaseByAge,
  getWeeklyAlert,
} from '../api/dashboard';

const MetricCard = ({ title, value, subtitle, icon, color = 'blue' }) => {
  const colorMap = {
    blue: 'bg-blue-50 text-blue-600',
    green: 'bg-green-50 text-green-600',
    purple: 'bg-purple-50 text-purple-600',
    orange: 'bg-orange-50 text-orange-600',
  };
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[14px] text-gray-400 font-medium mb-1">{title}</p>
          <p className="text-2xl font-bold text-gray-800">{value}</p>
          {subtitle && <p className="text-[13px] text-gray-400 mt-0.5">{subtitle}</p>}
        </div>
        <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${colorMap[color]}`}>
          {icon}
        </div>
      </div>
    </div>
  );
};

// 파이 차트 색상
const PIE_COLORS = ['#1E40AF', '#3B82F6', '#60A5FA', '#93C5FD', '#BFDBFE'];

// 커스텀 툴팁 (ComposedChart용)
const DualAxisTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-lg px-4 py-3 text-[13px]">
      <p className="font-semibold text-gray-700 mb-1.5">{label}</p>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: p.color }} />
          <span className="text-gray-600">{p.name}:</span>
          <span className="font-semibold text-gray-800">{p.value?.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
};

// ── 감염병 조기경보 컴포넌트 ─────────────────────────────────────────
const LEVEL_STYLE = {
  급증: { badge: 'bg-red-500 text-white',   card: 'bg-red-50 border-red-100',   text: 'text-red-500',   bar: '#EF4444' },
  주의: { badge: 'bg-amber-400 text-white', card: 'bg-amber-50 border-amber-100', text: 'text-amber-500', bar: '#F59E0B' },
  정상: { badge: 'bg-green-500 text-white', card: 'bg-green-50 border-green-100', text: 'text-green-500', bar: '#22C55E' },
};

const MiniBar = ({ trend, color }) => {
  const max = Math.max(...trend);
  return (
    <div className="flex items-end gap-0.5 h-8">
      {trend.map((v, i) => (
        <div
          key={i}
          className="flex-1 rounded-sm opacity-80"
          style={{ height: `${(v / max) * 100}%`, backgroundColor: color, minHeight: 3 }}
        />
      ))}
    </div>
  );
};

const DiseaseAlertBanner = () => {
  const [alertData, setAlertData] = useState(null);

  useEffect(() => {
    getWeeklyAlert().then(setAlertData).catch(console.error);
  }, []);

  if (!alertData) return null;

  return (
    <div className="mb-5 bg-white rounded-xl border border-gray-100 shadow-sm p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
          <p className="text-[15px] font-semibold text-gray-800">감염병 조기경보</p>
        </div>
        <div className="flex items-center gap-2 text-[12px] text-gray-400">
          <span>오늘 기준 ({alertData.date})</span>
          <span className="px-2 py-0.5 bg-gray-100 rounded-full">자동 집계</span>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {alertData.items.map((item) => {
          const style = LEVEL_STYLE[item.level] ?? LEVEL_STYLE['정상'];
          const isUp = item.change_pct >= 0;
          return (
            <div key={item.disease} className={`rounded-xl border p-3 space-y-2 ${style.card}`}>
              <div className="flex items-center justify-between">
                <p className="text-[13px] font-semibold text-gray-700 truncate">{item.disease}</p>
                <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold flex-shrink-0 ml-1 ${style.badge}`}>
                  {item.level}
                </span>
              </div>
              <p className={`text-2xl font-bold ${style.text}`}>
                {isUp ? '↑' : '↓'} {Math.abs(item.change_pct)}%
              </p>
              <MiniBar trend={item.trend} color={style.bar} />
              <p className="text-[11px] text-gray-400">전주 대비</p>
            </div>
          );
        })}
      </div>
    </div>
  );
};


const Dashboard = () => {
  const [activeTab, setActiveTab] = useState('my');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [bannerVisible, setBannerVisible] = useState(true);

  // 감염병 현황 탭 상태
  const [diseaseData, setDiseaseData] = useState(null);
  const [diseaseLoading, setDiseaseLoading] = useState(false);
  const [diseaseLoaded, setDiseaseLoaded] = useState(false);
  const [isMock, setIsMock] = useState(false);

  useEffect(() => {
    const fetch = async () => {
      try {
        const result = await getDashboard();
        setData(result);
      } catch (err) {
        console.error('대시보드 조회 실패:', err);
      } finally {
        setLoading(false);
      }
    };
    fetch();
  }, []);

  // 감염병 현황 탭 진입 시 1회 로드
  useEffect(() => {
    if (activeTab !== 'disease' || diseaseLoaded) return;
    const fetchDisease = async () => {
      setDiseaseLoading(true);
      try {
        const year = String(new Date().getFullYear());

        const [byDisease, trend, byGender, byAge] = await Promise.all([
          getDiseaseByDisease(),          // 이번 달 기준 (파라미터 불필요)
          getDiseaseTrendWithCalls(7),
          getDiseaseByGender(year),
          getDiseaseByAge(year),
        ]);

        setDiseaseData({ byDisease, trend, byGender, byAge });
        setIsMock(byDisease.is_mock || trend.is_mock);
      } catch (err) {
        console.error('감염병 현황 조회 실패:', err);
      } finally {
        setDiseaseLoading(false);
        setDiseaseLoaded(true);
      }
    };
    fetchDisease();
  }, [activeTab, diseaseLoaded]);

  const myStats = data?.my_stats || {};
  const allStats = data?.all_stats || {};

  // 샘플 데이터 (API 데이터가 없을 경우 fallback)
  const majorCategoryData = myStats.major_category_chart || [
    { name: '감염병', count: 45 },
    { name: '예방접종', count: 38 },
    { name: '만성질환', count: 29 },
    { name: '정신건강', count: 17 },
    { name: '암', count: 12 },
    { name: '기타', count: 8 },
  ];

  const subCategoryData = myStats.sub_category_chart || [
    { name: '코로나19', count: 22 },
    { name: '독감', count: 15 },
    { name: '결핵', count: 8 },
    { name: '당뇨', count: 12 },
    { name: '고혈압', count: 10 },
  ];

  const weeklyTrend = myStats.weekly_trend || [
    { day: '월', count: 18 },
    { day: '화', count: 24 },
    { day: '수', count: 21 },
    { day: '목', count: 28 },
    { day: '금', count: 32 },
    { day: '토', count: 15 },
    { day: '일', count: 9 },
  ];

  const keywords = myStats.top_keywords || [
    { keyword: '코로나19', count: 34 },
    { keyword: '독감 예방접종', count: 28 },
    { keyword: '마스크 착용', count: 21 },
    { keyword: '격리 기간', count: 18 },
    { keyword: '항원검사', count: 15 },
    { keyword: '집중치료', count: 12 },
    { keyword: '발열', count: 11 },
    { keyword: '호흡기 증상', count: 9 },
    { keyword: '당뇨 관리', count: 8 },
    { keyword: '혈압약', count: 7 },
  ];

  const hourlyData = allStats.hourly_chart || Array.from({ length: 24 }, (_, i) => ({
    hour: `${i}시`,
    count: Math.floor(Math.random() * 30 + 5),
  }));

  const diseaseLineData = allStats.disease_trend || [
    { month: '1월', 코로나19: 120, 독감: 80, 결핵: 30 },
    { month: '2월', 코로나19: 98, 독감: 110, 결핵: 28 },
    { month: '3월', 코로나19: 87, 독감: 95, 결핵: 32 },
    { month: '4월', 코로나19: 74, 독감: 70, 결핵: 27 },
    { month: '5월', 코로나19: 93, 독감: 45, 결핵: 30 },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      <GNB />
      <LNB />

      <div className="pt-[52px] pl-[7%] min-w-[64px]">
        <div className="p-6">
          {/* 감염병 조기경보 */}
          <DiseaseAlertBanner />

          {/* 알림 배너 */}
          {bannerVisible && (
            <div className="mb-5 bg-blue-600 text-white rounded-xl px-5 py-3 flex items-center justify-between shadow">
              <div className="flex items-center gap-3">
                <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
                <p className="text-[15px] font-medium">
                  질병관리청 AI 상담 시스템 v2.0이 업데이트되었습니다. 새로운 기능을 확인해보세요.
                </p>
              </div>
              <button
                onClick={() => setBannerVisible(false)}
                className="ml-4 hover:opacity-70 transition-opacity flex-shrink-0"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}

          {/* 탭 */}
          <div className="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit mb-6">
            {[
              { key: 'my', label: '내 통계' },
              { key: 'all', label: '전체 통계' },
              { key: 'disease', label: '감염병 현황' },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`px-5 py-2 rounded-lg text-[15px] font-medium transition-all ${
                  activeTab === tab.key
                    ? 'bg-white text-[#1E40AF] shadow-sm font-semibold'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {loading ? (
            <div className="flex items-center justify-center h-64 text-gray-400">
              <div className="text-center">
                <div className="w-8 h-8 border-2 border-blue-200 border-t-[#1E40AF] rounded-full animate-spin mx-auto mb-3" />
                <p className="text-[15px]">데이터를 불러오는 중...</p>
              </div>
            </div>
          ) : (
            <>
              {/* 내 통계 탭 */}
              {activeTab === 'my' && (
                <div className="space-y-6">
                  {/* Metric 카드 */}
                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    <MetricCard
                      title="총 상담 건수"
                      value={myStats.total_calls ?? 149}
                      subtitle="이번 달"
                      color="blue"
                      icon={
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"
                          />
                        </svg>
                      }
                    />
                    <MetricCard
                      title="평균 통화 시간"
                      value={myStats.avg_duration ?? '4분 32초'}
                      subtitle="전월 대비 -18초"
                      color="green"
                      icon={
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                          />
                        </svg>
                      }
                    />
                    <MetricCard
                      title="해결률"
                      value={myStats.resolution_rate ? `${myStats.resolution_rate}%` : '87%'}
                      subtitle="전월 대비 +2%"
                      color="purple"
                      icon={
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                          />
                        </svg>
                      }
                    />
                    <MetricCard
                      title="AI 활용률"
                      value={myStats.ai_usage_rate ? `${myStats.ai_usage_rate}%` : '93%'}
                      subtitle="평균 만족도 4.2"
                      color="orange"
                      icon={
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M13 10V3L4 14h7v7l9-11h-7z"
                          />
                        </svg>
                      }
                    />
                  </div>

                  {/* 차트 영역 */}
                  <div className="grid grid-cols-2 gap-5">
                    {/* 대분류 Bar Chart */}
                    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                      <h3 className="text-[15px] font-semibold text-gray-700 mb-4">대분류별 상담 건수</h3>
                      <ResponsiveContainer width="100%" height={220}>
                        <BarChart data={majorCategoryData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                          <XAxis dataKey="name" tick={{ fontSize: 13 }} />
                          <YAxis tick={{ fontSize: 13 }} />
                          <Tooltip contentStyle={{ fontSize: 14 }} />
                          <Bar dataKey="count" fill="#1E40AF" radius={[4, 4, 0, 0]} name="건수" />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>

                    {/* 중분류 Bar Chart */}
                    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                      <h3 className="text-[15px] font-semibold text-gray-700 mb-4">중분류별 상담 건수</h3>
                      <ResponsiveContainer width="100%" height={220}>
                        <BarChart data={subCategoryData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                          <XAxis dataKey="name" tick={{ fontSize: 13 }} />
                          <YAxis tick={{ fontSize: 13 }} />
                          <Tooltip contentStyle={{ fontSize: 14 }} />
                          <Bar dataKey="count" fill="#3B82F6" radius={[4, 4, 0, 0]} name="건수" />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-5">
                    {/* Top 10 키워드 */}
                    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                      <h3 className="text-[15px] font-semibold text-gray-700 mb-4">Top 10 키워드</h3>
                      <div className="space-y-2">
                        {keywords.slice(0, 10).map((kw, i) => {
                          const maxCount = keywords[0]?.count || 1;
                          const width = Math.round((kw.count / maxCount) * 100);
                          return (
                            <div key={i} className="flex items-center gap-2">
                              <span className="text-[13px] text-gray-400 w-4 text-right flex-shrink-0">{i + 1}</span>
                              <span className="text-[13px] text-gray-700 w-24 flex-shrink-0 truncate">{kw.keyword || kw.word}</span>
                              <div className="flex-1 bg-gray-100 rounded-full h-1.5">
                                <div
                                  className="bg-[#1E40AF] h-1.5 rounded-full transition-all"
                                  style={{ width: `${width}%` }}
                                />
                              </div>
                              <span className="text-[13px] text-gray-400 w-6 text-right flex-shrink-0">{kw.count}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    {/* 주간 트렌드 */}
                    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                      <h3 className="text-[15px] font-semibold text-gray-700 mb-4">주간 상담 트렌드</h3>
                      <ResponsiveContainer width="100%" height={220}>
                        <LineChart data={weeklyTrend} margin={{ top: 0, right: 10, left: -20, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                          <XAxis dataKey="day" tick={{ fontSize: 13 }} />
                          <YAxis tick={{ fontSize: 13 }} />
                          <Tooltip contentStyle={{ fontSize: 14 }} />
                          <Line type="monotone" dataKey="count" stroke="#1E40AF" strokeWidth={2} dot={{ r: 4 }} name="건수" />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                </div>
              )}

              {/* 감염병 현황 탭 */}
              {activeTab === 'disease' && (
                <div className="space-y-6">
                  {diseaseLoading ? (
                    <div className="flex items-center justify-center h-64 text-gray-400">
                      <div className="text-center">
                        <div className="w-8 h-8 border-2 border-blue-200 border-t-[#1E40AF] rounded-full animate-spin mx-auto mb-3" />
                        <p className="text-[15px]">감염병 데이터를 불러오는 중...</p>
                      </div>
                    </div>
                  ) : diseaseData ? (
                    <>
                      {/* Mock 안내 배너 */}
                      {isMock && (
                        <div className="flex items-center gap-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-[14px] text-amber-700">
                          <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                          </svg>
                          <span>
                            <b>샘플 데이터</b> 표시 중 — .env 의 <code className="bg-amber-100 px-1 rounded">DATA_GO_KR_API_KEY</code>를 설정하면 실제 전수신고 감염병 발생현황이 표시됩니다.
                          </span>
                        </div>
                      )}

                      {/* 상단 요약 카드 */}
                      <div className="grid grid-cols-4 gap-4">
                        {(diseaseData.byDisease?.items || []).slice(0, 4).map((item, i) => {
                          const colors = ['blue', 'green', 'purple', 'orange'];
                          const colorClass = {
                            blue:   'bg-blue-50 text-blue-600 border-blue-100',
                            green:  'bg-green-50 text-green-600 border-green-100',
                            purple: 'bg-purple-50 text-purple-600 border-purple-100',
                            orange: 'bg-orange-50 text-orange-600 border-orange-100',
                          }[colors[i]];
                          return (
                            <div key={i} className={`rounded-xl border p-4 ${colorClass}`}>
                              <p className="text-[13px] font-medium opacity-80 mb-1 truncate">{item.diseaseName}</p>
                              <p className="text-2xl font-bold">{item.cnt.toLocaleString()}</p>
                              <p className="text-[12px] opacity-70 mt-0.5">이번 달 확진자</p>
                            </div>
                          );
                        })}
                      </div>

                      {/* 메인 차트 영역 */}
                      <div className="grid grid-cols-2 gap-5">
                        {/* 감염병별 TOP10 수평 바차트 */}
                        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                          <h3 className="text-[15px] font-semibold text-gray-700 mb-1">감염병별 발생현황 TOP 10</h3>
                          <p className="text-[12px] text-gray-400 mb-4">이번 달 전수신고 확진자 수</p>
                          <ResponsiveContainer width="100%" height={280}>
                            <BarChart
                              layout="vertical"
                              data={(diseaseData.byDisease?.items || []).slice(0, 10)}
                              margin={{ top: 0, right: 40, left: 0, bottom: 0 }}
                            >
                              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" horizontal={false} />
                              <XAxis type="number" tick={{ fontSize: 12 }} tickFormatter={(v) => v.toLocaleString()} />
                              <YAxis
                                type="category"
                                dataKey="diseaseName"
                                tick={{ fontSize: 12 }}
                                width={120}
                                tickFormatter={(v) => v.length > 10 ? v.slice(0, 10) + '…' : v}
                              />
                              <Tooltip
                                contentStyle={{ fontSize: 13 }}
                                formatter={(v) => [v.toLocaleString() + '명', '확진자']}
                              />
                              <Bar dataKey="cnt" fill="#1E40AF" radius={[0, 4, 4, 0]} name="확진자" />
                            </BarChart>
                          </ResponsiveContainer>
                        </div>

                        {/* 성별 + 연령별 */}
                        <div className="flex flex-col gap-5">
                          {/* 성별 파이 차트 */}
                          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 flex-1">
                            <h3 className="text-[15px] font-semibold text-gray-700 mb-1">성별 발생현황</h3>
                            <p className="text-[12px] text-gray-400 mb-2">올해 누적</p>
                            <div className="flex items-center gap-4">
                              <PieChart width={120} height={120}>
                                <Pie
                                  data={diseaseData.byGender?.items || []}
                                  dataKey="cnt"
                                  nameKey="sex"
                                  cx="50%"
                                  cy="50%"
                                  innerRadius={30}
                                  outerRadius={55}
                                >
                                  {(diseaseData.byGender?.items || []).map((_, i) => (
                                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                                  ))}
                                </Pie>
                                <Tooltip formatter={(v) => v.toLocaleString()} />
                              </PieChart>
                              <div className="space-y-2">
                                {(diseaseData.byGender?.items || []).map((g, i) => (
                                  <div key={i} className="flex items-center gap-2">
                                    <span className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                                      style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />
                                    <span className="text-[13px] text-gray-700">{g.sex}</span>
                                    <span className="text-[13px] font-semibold text-gray-800 ml-auto">
                                      {g.cnt.toLocaleString()}명
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>

                          {/* 연령별 바 차트 */}
                          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 flex-1">
                            <h3 className="text-[15px] font-semibold text-gray-700 mb-1">연령별 발생현황</h3>
                            <p className="text-[12px] text-gray-400 mb-2">올해 누적</p>
                            <ResponsiveContainer width="100%" height={120}>
                              <BarChart data={diseaseData.byAge?.items || []} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                                <XAxis dataKey="ageGroup" tick={{ fontSize: 11 }} />
                                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => (v / 1000).toFixed(0) + 'k'} />
                                <Tooltip
                                  contentStyle={{ fontSize: 13 }}
                                  formatter={(v) => [v.toLocaleString() + '명', '확진자']}
                                />
                                <Bar dataKey="cnt" fill="#3B82F6" radius={[3, 3, 0, 0]} name="확진자" />
                              </BarChart>
                            </ResponsiveContainer>
                          </div>
                        </div>
                      </div>

                      {/* 월별 추이: 확진자 + 1339 콜 상관관계 (핵심 차트) */}
                      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                        <div className="flex items-start justify-between mb-4">
                          <div>
                            <h3 className="text-[15px] font-semibold text-gray-700">전수신고 확진자 수 vs 1339 콜 건수</h3>
                            <p className="text-[12px] text-gray-400 mt-0.5">감염병 발생과 콜센터 수요의 상관관계 — 월별 추이</p>
                          </div>
                          <div className="flex items-center gap-4 text-[13px]">
                            <div className="flex items-center gap-1.5">
                              <span className="w-6 h-0.5 bg-[#1E40AF] inline-block" />
                              <span className="text-gray-500">확진자 (명)</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                              <span className="w-6 h-0.5 bg-[#10B981] inline-block border-dashed" style={{ borderTop: '2px dashed #10B981', height: 0 }} />
                              <span className="text-gray-500">1339 콜 (건)</span>
                            </div>
                          </div>
                        </div>
                        <ResponsiveContainer width="100%" height={260}>
                          <ComposedChart
                            data={diseaseData.trend?.trend || []}
                            margin={{ top: 10, right: 60, left: 0, bottom: 0 }}
                          >
                            <defs>
                              <linearGradient id="covidGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%"  stopColor="#1E40AF" stopOpacity={0.15} />
                                <stop offset="95%" stopColor="#1E40AF" stopOpacity={0} />
                              </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                            <XAxis dataKey="label" tick={{ fontSize: 13 }} />
                            {/* 왼쪽 Y축: 확진자 수 */}
                            <YAxis
                              yAxisId="left"
                              orientation="left"
                              tick={{ fontSize: 12 }}
                              tickFormatter={(v) => (v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v)}
                              label={{ value: '확진자 (명)', angle: -90, position: 'insideLeft', offset: 15, style: { fontSize: 12, fill: '#1E40AF' } }}
                            />
                            {/* 오른쪽 Y축: 콜 건수 */}
                            <YAxis
                              yAxisId="right"
                              orientation="right"
                              tick={{ fontSize: 12 }}
                              tickFormatter={(v) => (v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v)}
                              label={{ value: '콜 건수 (건)', angle: 90, position: 'insideRight', offset: 15, style: { fontSize: 12, fill: '#10B981' } }}
                            />
                            <Tooltip content={<DualAxisTooltip />} />
                            {/* 코로나19 면적 라인 */}
                            <Area
                              yAxisId="left"
                              type="monotone"
                              dataKey="코로나19"
                              stroke="#1E40AF"
                              strokeWidth={2}
                              fill="url(#covidGrad)"
                              dot={{ r: 4, fill: '#1E40AF' }}
                              name="코로나19 확진자"
                            />
                            {/* 독감 라인 */}
                            <Line
                              yAxisId="left"
                              type="monotone"
                              dataKey="독감"
                              stroke="#F59E0B"
                              strokeWidth={1.5}
                              dot={{ r: 3 }}
                              name="독감 확진자"
                              strokeDasharray="4 2"
                            />
                            {/* 1339 콜 건수 (오른쪽 축) */}
                            <Line
                              yAxisId="right"
                              type="monotone"
                              dataKey="calls"
                              stroke="#10B981"
                              strokeWidth={2.5}
                              dot={{ r: 5, fill: '#10B981' }}
                              name="1339 콜 건수"
                            />
                            <Legend iconSize={10} wrapperStyle={{ fontSize: 13, paddingTop: 12 }} />
                          </ComposedChart>
                        </ResponsiveContainer>
                        <p className="text-[12px] text-gray-400 mt-3 text-center">
                          * 확진자 수: 질병관리청 전수신고 감염병 발생현황 | 콜 건수: 내부 ACW 카드 기준
                        </p>
                      </div>
                    </>
                  ) : (
                    <div className="text-center py-16 text-gray-400 text-[15px]">데이터를 불러올 수 없습니다.</div>
                  )}
                </div>
              )}

              {/* 전체 통계 탭 */}
              {activeTab === 'all' && (
                <div className="space-y-6">
                  {/* 기간별 건수 카드 */}
                  <div className="grid grid-cols-3 gap-4">
                    {[
                      { label: '오늘', value: allStats.today_count ?? 847, sub: '전일 대비 +12%' },
                      { label: '이번 주', value: allStats.week_count ?? 4238, sub: '전주 대비 +5%' },
                      { label: '이번 달', value: allStats.month_count ?? 18492, sub: '전월 대비 +8%' },
                    ].map((item) => (
                      <div key={item.label} className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                        <p className="text-[14px] text-gray-400 font-medium mb-1">{item.label} 상담 건수</p>
                        <p className="text-3xl font-bold text-gray-800">{typeof item.value === 'number' ? item.value.toLocaleString() : item.value}</p>
                        <p className="text-[13px] text-green-600 mt-1 font-medium">{item.sub}</p>
                      </div>
                    ))}
                  </div>

                  <div className="grid grid-cols-2 gap-5">
                    {/* 시간대별 Bar Chart */}
                    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                      <h3 className="text-[15px] font-semibold text-gray-700 mb-4">시간대별 상담 건수</h3>
                      <ResponsiveContainer width="100%" height={240}>
                        <BarChart data={hourlyData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                          <XAxis dataKey="hour" tick={{ fontSize: 11 }} interval={2} />
                          <YAxis tick={{ fontSize: 13 }} />
                          <Tooltip contentStyle={{ fontSize: 14 }} />
                          <Bar dataKey="count" fill="#1E40AF" radius={[3, 3, 0, 0]} name="건수" />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>

                    {/* 질병별 추이 Line Chart */}
                    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                      <h3 className="text-[15px] font-semibold text-gray-700 mb-4">질병별 월간 추이</h3>
                      <ResponsiveContainer width="100%" height={240}>
                        <LineChart data={diseaseLineData} margin={{ top: 0, right: 10, left: -20, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                          <XAxis dataKey="month" tick={{ fontSize: 13 }} />
                          <YAxis tick={{ fontSize: 13 }} />
                          <Tooltip contentStyle={{ fontSize: 14 }} />
                          <Legend iconSize={10} wrapperStyle={{ fontSize: 13 }} />
                          <Line type="monotone" dataKey="코로나19" stroke="#1E40AF" strokeWidth={2} dot={{ r: 3 }} />
                          <Line type="monotone" dataKey="독감" stroke="#10B981" strokeWidth={2} dot={{ r: 3 }} />
                          <Line type="monotone" dataKey="결핵" stroke="#F59E0B" strokeWidth={2} dot={{ r: 3 }} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;

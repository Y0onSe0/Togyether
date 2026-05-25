import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { login } from '../api/auth';

const Login = () => {
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleChange = (e) => {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
    setError('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.username.trim() || !form.password.trim()) {
      setError('입력한 정보가 올바르지 않습니다.');
      return;
    }
    setLoading(true);
    try {
      await login(form.username, form.password);
      navigate('/main');
    } catch (err) {
      const msg = err.response?.data?.detail || err.response?.data?.message || '입력한 정보가 올바르지 않습니다.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">

      {/* 좌측 브랜드 패널 */}
      <div className="hidden lg:flex w-1/2 bg-[#1D4ED8] flex-col items-center justify-center p-16 text-white">
        <div className="max-w-sm text-center">
          <div className="w-20 h-20 bg-white/20 rounded-2xl flex items-center justify-center mx-auto mb-8">
            <svg className="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
                d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"
              />
            </svg>
          </div>
          <h1 className="text-4xl font-bold mb-3 tracking-tight">질병관리청<br />AI 상담시스템</h1>
          <p className="text-blue-200 text-[18px] leading-relaxed">
            1339 콜센터 AI 상담 지원 시스템<br />
            실시간 AI 분석으로 상담 품질을 높이세요
          </p>
          <div className="mt-12 grid grid-cols-3 gap-4 text-center">
            {[['RAG', '지식 검색'], ['실시간', 'AI 분석'], ['ACW', '후처리']].map(([t, d]) => (
              <div key={t} className="bg-white/10 rounded-xl py-4 px-2">
                <p className="text-xl font-bold">{t}</p>
                <p className="text-[14px] text-blue-200 mt-1">{d}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 우측 로그인 폼 */}
      <div className="flex-1 bg-[#F8FAFC] flex items-center justify-center p-8">
        <div className="w-full max-w-[420px]">

          {/* 모바일용 타이틀 (lg 이상에서는 숨김) */}
          <div className="lg:hidden text-center mb-8">
            <h1 className="text-2xl font-bold text-[#1D4ED8]">질병관리청 AI 상담시스템</h1>
            <p className="text-[15px] text-[#64748B] mt-1">1339 콜센터 AI 상담 지원 시스템</p>
          </div>

          <div className="bg-white rounded-[12px] border border-[#E2E8F0] shadow-[0_1px_3px_rgba(0,0,0,0.06)] p-10">
            <h2 className="text-[24px] font-semibold text-[#1D4ED8] mb-1">로그인</h2>
            <p className="text-[15px] text-[#64748B] mb-8">계정 정보를 입력해주세요</p>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label className="block text-[15px] font-medium text-[#334155] mb-2">아이디</label>
                <input
                  type="text"
                  name="username"
                  value={form.username}
                  onChange={handleChange}
                  autoComplete="username"
                  placeholder="아이디를 입력하세요"
                  className="w-full h-[46px] px-4 border border-[#CBD5E1] rounded-[8px] bg-white text-[16px] text-[#334155] placeholder-[#CBD5E1] focus:outline-none focus:border-[#1D4ED8] transition-colors"
                />
              </div>

              <div>
                <label className="block text-[15px] font-medium text-[#334155] mb-2">비밀번호</label>
                <input
                  type="password"
                  name="password"
                  value={form.password}
                  onChange={handleChange}
                  autoComplete="current-password"
                  placeholder="비밀번호를 입력하세요"
                  className="w-full h-[46px] px-4 border border-[#CBD5E1] rounded-[8px] bg-white text-[16px] text-[#334155] placeholder-[#CBD5E1] focus:outline-none focus:border-[#1D4ED8] transition-colors"
                />
              </div>

              {error && (
                <p className="text-[#DC2626] text-[15px] text-center">{error}</p>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full h-[46px] bg-[#1D4ED8] text-white text-[16px] font-semibold rounded-[8px] hover:bg-[#1e40af] transition-colors disabled:opacity-60 disabled:cursor-not-allowed mt-2"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    로그인 중...
                  </span>
                ) : '로그인'}
              </button>
            </form>

            <div className="h-px bg-[#F1F5F9] my-6" />

            <p className="text-[15px] text-[#64748B] text-center">
              계정이 없으신가요?{' '}
              <Link to="/register" className="text-[#1D4ED8] font-semibold hover:underline">
                계정 생성
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Login;

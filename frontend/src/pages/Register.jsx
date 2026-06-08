import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { register } from '../api/auth';
import api from '../api/auth';

const Register = () => {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    username: '',
    name: '',
    password: '',
    passwordConfirm: '',
  });
  const [usernameChecked, setUsernameChecked] = useState(null); // null | true | false
  const [checkLoading, setCheckLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm((prev) => ({ ...prev, [name]: value }));
    if (name === 'username') setUsernameChecked(null);
    setError('');
  };

  const handleCheckUsername = async () => {
    if (!form.username.trim()) {
      setError('아이디를 입력해주세요.');
      return;
    }
    setCheckLoading(true);
    try {
      const res = await api.get(`/api/agents/check-name?username=${encodeURIComponent(form.username)}`);
      const available = res.data?.available ?? !res.data?.exists;
      setUsernameChecked(available);
      if (!available) setError('이미 사용 중인 아이디입니다.');
    } catch (err) {
      if (err.response?.status === 409) {
        setUsernameChecked(false);
        setError('이미 사용 중인 아이디입니다.');
      } else {
        setUsernameChecked(true);
      }
    } finally {
      setCheckLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!form.username.trim() || !form.name.trim() || !form.password.trim()) {
      setError('모든 항목을 입력해주세요.');
      return;
    }
    if (form.password !== form.passwordConfirm) {
      setError('비밀번호가 일치하지 않습니다.');
      return;
    }
    if (form.password.length < 6) {
      setError('비밀번호는 6자 이상이어야 합니다.');
      return;
    }
    if (usernameChecked === false) {
      setError('이미 사용 중인 아이디입니다.');
      return;
    }

    setLoading(true);
    try {
      await register({
        username: form.username,
        name: form.name,
        password: form.password,
        password_confirm: form.passwordConfirm,
      });
      setSuccess('계정이 생성되었습니다. 로그인 페이지로 이동합니다...');
      setTimeout(() => navigate('/'), 1200);
    } catch (err) {
      const msg = err.response?.data?.detail || err.response?.data?.message || '계정 생성에 실패했습니다.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const usernameBorderCls =
    usernameChecked === true
      ? 'border-[#22C55E]'
      : usernameChecked === false
      ? 'border-[#DC2626]'
      : 'border-[#CBD5E1]';

  const pwConfirmBorderCls =
    form.passwordConfirm && form.password !== form.passwordConfirm
      ? 'border-[#DC2626]'
      : 'border-[#CBD5E1]';

  const inputBase =
    'w-full h-11 px-4 border rounded-[8px] bg-white text-[16px] text-[#334155] placeholder-[#CBD5E1] focus:outline-none focus:border-[#0054A6] transition-colors';

  return (
    <div className="min-h-screen flex">

      {/* 좌측 브랜드 패널 */}
      <div className="hidden lg:flex w-1/2 bg-[#0054A6] flex-col items-center justify-center p-16 text-white">
        <div className="max-w-sm text-center">
          <div className="w-20 h-20 bg-white/20 rounded flex items-center justify-center mx-auto mb-8">
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
              <div key={t} className="bg-white/10 rounded-lg py-4 px-2">
                <p className="text-xl font-bold">{t}</p>
                <p className="text-[14px] text-blue-200 mt-1">{d}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 우측 회원가입 폼 */}
      <div className="flex-1 bg-[#F8FAFC] flex items-center justify-center p-8">
        <div className="w-full max-w-[420px]">

          {/* 모바일용 타이틀 */}
          <div className="lg:hidden text-center mb-8">
            <h1 className="text-2xl font-bold text-[#0054A6]">질병관리청 AI 상담시스템</h1>
            <p className="text-[15px] text-[#64748B] mt-1">1339 콜센터 AI 상담 지원 시스템</p>
          </div>

          <div className="bg-white rounded-[12px] border border-[#E2E8F0] shadow-[0_1px_3px_rgba(0,0,0,0.06)] p-10">
            <h2 className="text-[24px] font-semibold text-[#0054A6] mb-1">신규 계정 생성</h2>
            <p className="text-[15px] text-[#64748B] mb-8">새 계정 정보를 입력해주세요</p>

            <form onSubmit={handleSubmit} className="space-y-5">

              {/* 아이디 + 중복확인 */}
              <div>
                <label className="block text-[15px] font-medium text-[#334155] mb-2">아이디</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    name="username"
                    value={form.username}
                    onChange={handleChange}
                    autoComplete="username"
                    placeholder="아이디를 입력하세요"
                    className={`${inputBase} flex-1 ${usernameBorderCls}`}
                  />
                  <button
                    type="button"
                    onClick={handleCheckUsername}
                    disabled={checkLoading}
                    className="h-11 px-4 bg-[#F1F5F9] hover:bg-[#E2E8F0] text-[#334155] text-[15px] font-medium rounded-[8px] transition-colors disabled:opacity-60 whitespace-nowrap"
                  >
                    {checkLoading ? '확인 중' : '중복확인'}
                  </button>
                </div>
                {usernameChecked === true && (
                  <p className="text-[13px] text-[#22C55E] mt-1">사용 가능한 아이디입니다.</p>
                )}
                {usernameChecked === false && (
                  <p className="text-[13px] text-[#DC2626] mt-1">이미 사용 중인 아이디입니다.</p>
                )}
              </div>

              {/* 이름 */}
              <div>
                <label className="block text-[15px] font-medium text-[#334155] mb-2">이름</label>
                <input
                  type="text"
                  name="name"
                  value={form.name}
                  onChange={handleChange}
                  autoComplete="name"
                  placeholder="이름을 입력하세요"
                  className={`${inputBase} border-[#CBD5E1]`}
                />
              </div>

              {/* 비밀번호 */}
              <div>
                <label className="block text-[15px] font-medium text-[#334155] mb-2">비밀번호</label>
                <input
                  type="password"
                  name="password"
                  value={form.password}
                  onChange={handleChange}
                  autoComplete="new-password"
                  placeholder="비밀번호를 입력하세요 (6자 이상)"
                  className={`${inputBase} border-[#CBD5E1]`}
                />
              </div>

              {/* 비밀번호 확인 */}
              <div>
                <label className="block text-[15px] font-medium text-[#334155] mb-2">비밀번호 확인</label>
                <input
                  type="password"
                  name="passwordConfirm"
                  value={form.passwordConfirm}
                  onChange={handleChange}
                  autoComplete="new-password"
                  placeholder="비밀번호를 다시 입력하세요"
                  className={`${inputBase} ${pwConfirmBorderCls}`}
                />
                {form.passwordConfirm && form.password !== form.passwordConfirm && (
                  <p className="text-[13px] text-[#DC2626] mt-1">비밀번호가 일치하지 않습니다.</p>
                )}
              </div>

              {/* 에러 / 성공 메시지 */}
              {error && (
                <p className="text-[#DC2626] text-[15px] text-center">{error}</p>
              )}
              {success && (
                <p className="text-[#22C55E] text-[15px] text-center">{success}</p>
              )}

              {/* 계정 생성 버튼 */}
              <button
                type="submit"
                disabled={loading}
                className="w-full h-11 bg-[#0054A6] text-white text-[16px] font-semibold rounded-[8px] hover:bg-[#003F7D] transition-colors disabled:opacity-60 disabled:cursor-not-allowed mt-2"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    처리 중...
                  </span>
                ) : '계정 생성'}
              </button>
            </form>

            <div className="h-px bg-[#F1F5F9] my-6" />

            <p className="text-[15px] text-[#64748B] text-center">
              이미 계정이 있으신가요?{' '}
              <Link to="/" className="text-[#0054A6] font-semibold hover:underline">
                로그인
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Register;

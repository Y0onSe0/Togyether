import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronDown, LogOut, User } from 'lucide-react';
import { logout as apiLogout } from '../api/auth';

const GNB = () => {
  const navigate = useNavigate();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const menuRef = useRef(null);

  // localStorage에서 로그인된 상담사 정보 읽기
  const agentRaw = localStorage.getItem('agent');
  let agent = null;
  try {
    agent = agentRaw ? JSON.parse(agentRaw) : null;
  } catch {
    agent = null;
  }
  const agentName = agent?.name || agent?.username || '상담사';
  const agentId   = agent?.username || '-';

  // 메뉴 바깥 클릭 시 닫기
  useEffect(() => {
    const handler = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setShowUserMenu(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleLogout = async () => {
    try {
      await apiLogout();
    } catch {
      localStorage.removeItem('access_token');
      localStorage.removeItem('agent');
    }
    navigate('/');
  };

  return (
    <div className="fixed top-0 left-0 right-0 z-50 h-[52px] bg-white border-b border-[#E2E8F0] px-6 flex items-center justify-between">
      {/* 로고 */}
      <h1 className="text-[17px] font-semibold text-[#1D4ED8]">
        질병관리청 AI 상담시스템
      </h1>

      {/* 유저 메뉴 */}
      <div className="relative" ref={menuRef}>
        <button
          onClick={() => setShowUserMenu((v) => !v)}
          className="flex items-center gap-1 text-[15px] text-[#334155] hover:text-[#1D4ED8] transition-colors"
        >
          <span>{agentName}</span>
          <ChevronDown size={14} />
        </button>

        {showUserMenu && (
          <div className="absolute top-full right-0 mt-2 bg-white rounded-[10px] shadow-[0_1px_3px_rgba(0,0,0,0.06)] border border-[#E2E8F0] w-52 p-5 z-50">
            {/* 프로필 */}
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 bg-[#EFF6FF] border border-[#BFDBFE] rounded-full flex items-center justify-center">
                <User size={20} className="text-[#1D4ED8]" />
              </div>
              <div>
                <p className="text-[15px] font-medium text-[#334155]">{agentName}</p>
                <p className="text-[13px] text-[#64748B]">{agentId}</p>
              </div>
            </div>

            <div className="h-px bg-[#F1F5F9] my-3" />

            {/* 로그아웃 */}
            <button
              onClick={handleLogout}
              className="flex items-center gap-2 text-[#DC2626] text-[14px] hover:text-[#B91C1C] w-full transition-colors"
            >
              <LogOut size={14} />
              <span>로그아웃</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default GNB;

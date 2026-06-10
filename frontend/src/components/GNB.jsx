import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronDown, LogOut, User, Shield } from 'lucide-react';
import { logout as apiLogout } from '../api/auth';

const GNB = () => {
  const navigate = useNavigate();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const menuRef = useRef(null);

  const agentRaw = localStorage.getItem('agent');
  let agent = null;
  try { agent = agentRaw ? JSON.parse(agentRaw) : null; } catch { agent = null; }
  const agentName = agent?.name || agent?.username || '상담사';
  const agentId   = agent?.username || '-';

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
    try { await apiLogout(); } catch {
      localStorage.removeItem('access_token');
      localStorage.removeItem('agent');
    }
    navigate('/');
  };

  return (
    <div className="fixed top-0 left-0 right-0 z-50 h-[52px] bg-[#0054A6] px-5 flex items-center justify-between">
      {/* 로고 */}
      <div className="flex items-center gap-2.5">
        <div className="w-7 h-7 bg-white/20 rounded flex items-center justify-center flex-shrink-0">
          <Shield size={15} className="text-white" strokeWidth={2} />
        </div>
        <span className="text-[16px] font-semibold text-white tracking-tight leading-none">
          질병관리청 AI 상담시스템
        </span>
      </div>

      {/* 유저 메뉴 */}
      <div className="relative" ref={menuRef}>
        <button
          onClick={() => setShowUserMenu((v) => !v)}
          className="flex items-center gap-2 h-8 pl-2.5 pr-2 rounded hover:bg-white/15 transition-colors"
        >
          <div className="w-6 h-6 bg-white/25 rounded-full flex items-center justify-center">
            <User size={13} className="text-white" strokeWidth={2} />
          </div>
          <span className="text-[14px] text-white font-medium">{agentName}</span>
          <ChevronDown
            size={13}
            className={`text-white/80 transition-transform duration-150 ${showUserMenu ? 'rotate-180' : ''}`}
          />
        </button>

        {showUserMenu && (
          <div className="absolute top-full right-0 mt-1.5 bg-white rounded border border-[#D9D9D9] shadow-[0_4px_12px_rgba(0,0,0,0.12)] w-52 overflow-hidden z-50">
            <div className="flex items-center gap-3 px-4 py-3.5 bg-[#F8FAFC] border-b border-[#E2E8F0]">
              <div className="w-9 h-9 bg-[#EAF0FA] border border-[#B3CCE8] rounded-full flex items-center justify-center flex-shrink-0">
                <User size={18} className="text-[#0054A6]" />
              </div>
              <div className="min-w-0">
                <p className="text-[14px] font-semibold text-[#1A1A1A] truncate">{agentName}</p>
                <p className="text-[12px] text-[#6B7280] truncate">{agentId}</p>
              </div>
            </div>
            <button
              onClick={handleLogout}
              className="flex items-center gap-2 text-[#DC2626] text-[13px] hover:bg-[#FEF2F2] w-full px-4 py-3 transition-colors"
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

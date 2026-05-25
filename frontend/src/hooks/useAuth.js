import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { logout as apiLogout } from '../api/auth';

export const useAuth = () => {
  const navigate = useNavigate();
  const [agent, setAgent] = useState(null);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    const storedAgent = localStorage.getItem('agent');
    if (!token) {
      navigate('/');
      return;
    }
    if (storedAgent) {
      try {
        setAgent(JSON.parse(storedAgent));
      } catch {
        setAgent(null);
      }
    }
  }, [navigate]);

  const handleLogout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      localStorage.removeItem('access_token');
      localStorage.removeItem('agent');
    }
    navigate('/');
  }, [navigate]);

  return { agent, handleLogout };
};

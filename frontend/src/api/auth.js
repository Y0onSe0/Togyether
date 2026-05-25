import axios from 'axios';

const BASE_URL = 'http://127.0.0.1:8000';

const api = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const login = async (username, password) => {
  const response = await api.post('/api/auth/login', { username, password });
  const { access_token } = response.data;
  localStorage.setItem('access_token', access_token);
  if (response.data.agent) {
    localStorage.setItem('agent', JSON.stringify(response.data.agent));
  }
  return response.data;
};

export const logout = async () => {
  try {
    await api.post('/api/auth/logout');
  } finally {
    localStorage.removeItem('access_token');
    localStorage.removeItem('agent');
  }
};

export const register = async (userData) => {
  const response = await api.post('/api/agents', userData);
  return response.data;
};

export default api;

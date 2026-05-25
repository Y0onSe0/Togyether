import api from './auth';

export const initACW = async (callId) => {
  const response = await api.get(`/api/acw/${callId}/init`);
  return response.data;
};

// Step B: transcript + ai_guidance → LLM 자동 ACW 필드 생성
export const generateACW = async (callId) => {
  const response = await api.post(`/api/acw/${callId}/generate`);
  return response.data;
};

export const saveACW = async (callId, acwData) => {
  const response = await api.put(`/api/acw/${callId}`, acwData);
  return response.data;
};

export const getCategories = async () => {
  const response = await api.get('/api/categories');
  return response.data;
};

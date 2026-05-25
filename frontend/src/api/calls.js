import api from './auth';

export const startCall = async () => {
  const response = await api.post('/api/calls');
  return response.data;
};

export const endCall = async (callId) => {
  const response = await api.patch(`/api/calls/${callId}/end`);
  return response.data;
};

export const getCall = async (callId) => {
  const response = await api.get(`/api/calls/${callId}`);
  return response.data;
};

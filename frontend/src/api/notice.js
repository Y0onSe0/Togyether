import axios from 'axios';

const API = axios.create({ baseURL: 'http://127.0.0.1:8000' });

API.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export const getPressReleases = (page = 1, size = 20) =>
  API.get('/api/notice/press', { params: { page, size } }).then(r => r.data);

export const getSimilarCases = (page = 1, size = 20) =>
  API.get('/api/notice/similar', { params: { page, size } }).then(r => r.data);

export const triggerCrawl = () =>
  API.post('/api/notice/crawl').then(r => r.data);

export const getStats = () =>
  API.get('/api/notice/stats').then(r => r.data);

export const getBanner = () =>
  API.get('/api/notice/banner').then(r => r.data);

export const postBanner = (message, level = 'info') =>
  API.post('/api/notice/banner', { message, level }).then(r => r.data);

export const deleteBanner = (id) =>
  API.delete(`/api/notice/banner/${id}`);

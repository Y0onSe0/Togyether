import api from './auth';

export const getDashboard = async () => {
  const response = await api.get('/api/dashboard');
  return response.data;
};

// 감염병별 발생현황 TOP 10
export const getDiseaseByDisease = async (year = '2025', searchType = '1', patntType = '1') => {
  const response = await api.get('/api/disease-stats/by-disease', {
    params: { year, search_type: searchType, patnt_type: patntType },
  });
  return response.data;
};

// 월별 확진자 + 1339 콜 건수 상관 데이터
export const getDiseaseTrendWithCalls = async (months = 7) => {
  const response = await api.get('/api/disease-stats/trend-with-calls', {
    params: { months },
  });
  return response.data;
};

// 성별 발생현황
export const getDiseaseByGender = async (year = '2025') => {
  const response = await api.get('/api/disease-stats/by-gender', {
    params: { year },
  });
  return response.data;
};

// 연령별 발생현황
export const getDiseaseByAge = async (year = '2025') => {
  const response = await api.get('/api/disease-stats/by-age', {
    params: { year },
  });
  return response.data;
};

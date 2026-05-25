import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  // StrictMode는 배포 시에만 활성화 (개발 중 WS 이중 연결 방지)
  // <StrictMode>
    <App />
  // </StrictMode>
)

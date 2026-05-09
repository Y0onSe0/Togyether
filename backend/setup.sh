#!/bin/bash
echo "[1/4] Python 버전 확인 중..."
python3 --version

echo "[2/4] 가상환경 생성 중..."
python3 -m venv venv

echo "[3/4] 가상환경 활성화 중..."
source venv/bin/activate

echo "[4/4] 패키지 설치 중..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "===================================="
echo "세팅 완료!"
echo ".env.example 복사해서 .env 만들고"
echo "OPENAI_API_KEY 넣으면 됩니다."
echo "===================================="
echo ""
echo "실행: uvicorn app.main:app --reload"

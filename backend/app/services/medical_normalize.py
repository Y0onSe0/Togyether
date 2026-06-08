"""
의료 도메인 텍스트 정규화 유틸리티
- STT 오인식 치환 (_MEDICAL_REPLACE)
- disease_name 정규화 (normalize_disease_name)
"""
import re

# 긴 패턴 우선 적용
_MEDICAL_REPLACE = [
    # E형간염
    ("이형 간염",     "E형간염"),
    ("이형간염",      "E형간염"),
    ("e형 간염",      "E형간염"),
    ("e형간염",       "E형간염"),
    ("2형 간염",      "E형간염"),
    ("2형감염",       "E형간염"),
    # C형간염
    ("시험관염",      "C형간염"),
    ("씨형 간염",     "C형간염"),
    ("씨형간염",      "C형간염"),
    ("씨 형 간염",    "C형간염"),
    ("c형 간염",      "C형간염"),
    ("c형간염",       "C형간염"),
    # A형간염
    ("에이형 간염",   "A형간염"),
    ("에이형간염",    "A형간염"),
    ("a형 간염",      "A형간염"),
    # B형간염
    ("비형 간염",     "B형간염"),
    ("비형간염",      "B형간염"),
    ("b형 간염",      "B형간염"),
    # 결핵
    ("혈액이요",      "결핵이요"),
    ("혈액요",        "결핵이요"),
    ("혈 액이요",     "결핵이요"),
    # 임질
    ("인지를",        "임질을"),
    ("인질을",        "임질을"),
    ("인질이",        "임질이"),
    ("인질에",        "임질에"),
    ("인질의",        "임질의"),
    ("인질로",        "임질로"),
    ("인질은",        "임질은"),
    ("인질이요",      "임질이요"),
    # 기타
    ("에이즈",        "후천성면역결핍증"),
    ("에이 즈",       "후천성면역결핍증"),
    ("코로나 19",     "코로나19"),
    ("코로나nineteen", "코로나19"),
]

# disease_name 전용 정규화 매핑 (STT 오인식 외에 표기 통일)
_DISEASE_NAME_MAP = [
    # 간염 계열 표기 통일
    ("A형 간염",      "A형간염"),
    ("B형 간염",      "B형간염"),
    ("C형 간염",      "C형간염"),
    ("E형 간염",      "E형간염"),
    # 코로나
    ("코로나 19",     "코로나19"),
    ("COVID-19",      "코로나19"),
    ("covid-19",      "코로나19"),
    ("covid19",       "코로나19"),
    # 결핵
    ("TB",            "결핵"),
    # 후천성면역결핍증
    ("HIV/AIDS",      "후천성면역결핍증"),
    ("AIDS",          "후천성면역결핍증"),
    ("에이즈",        "후천성면역결핍증"),
]


def normalize_medical_text(text: str) -> str:
    """STT 오인식 치환 (문장 전체용)"""
    if not text:
        return text
    lower = text.lower()
    for wrong, correct in _MEDICAL_REPLACE:
        if wrong.lower() in lower:
            text = re.sub(re.escape(wrong), correct, text, flags=re.IGNORECASE)
            lower = text.lower()
    return text


def normalize_disease_name(name: str) -> str:
    """
    ACW 저장 시 disease_name 정규화
    1) STT 오인식 치환
    2) 표기 통일 (공백 제거, 대소문자 등)
    3) 앞뒤 공백 제거
    """
    if not name:
        return name

    # 1) STT 오인식 치환
    result = normalize_medical_text(name)

    # 2) 표기 통일 매핑
    lower = result.lower()
    for wrong, correct in _DISEASE_NAME_MAP:
        if wrong.lower() == lower:
            return correct

    # 3) 정리
    return result.strip()

"""
transfer_agencies 테이블 재구축 스크립트

기존 123건 → 30건으로 정리
- 일반 고객 대상 기관 + 의료진 전문 문의 부서 추가
- 오염된 description_summary 제거 및 재작성
- 임베딩 재생성
- 실행: python rebuild_transfer_agencies.py
"""
import asyncio
import asyncpg
import os
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

DB_URL = (
    "postgresql://postgres.yjmzvzjlwpvijijlgcnp:Togyether%21%21"
    "@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres"
)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# ── 새 이관 기관 데이터 ─────────────────────────────────────────
# category: 헬프데스크 | 복지·의료 | 감염병대응 | 지역의료 | 응급 | 행정
AGENCIES = [
    # ── 헬프데스크 ────────────────────────────────────────────
    {
        "category": "헬프데스크",
        "org_name": "결핵관리 HelpDesk",
        "dept_name": None,
        "phone": "043-719-7312",
        "description_summary": "결핵 환자 치료·검진·관리, 결핵 예방 정책 및 국가 결핵관리 전문 문의 창구",
    },
    {
        "category": "헬프데스크",
        "org_name": "에이즈상담센터",
        "dept_name": None,
        "phone": "02-861-4114",
        "description_summary": "HIV/AIDS 감염인 및 가족 대상 전문 심리 상담, 의료기관 연계, 복지 서비스 안내",
    },
    {
        "category": "헬프데스크",
        "org_name": "대한에이즈예방협회",
        "dept_name": None,
        "phone": "043-719-7155",
        "description_summary": "HIV/AIDS 예방 교육·홍보, 검사 지원, 청소년 및 취약계층 성매개감염병 예방 사업",
    },
    {
        "category": "헬프데스크",
        "org_name": "한국에이즈퇴치연맹",
        "dept_name": None,
        "phone": "1551-8105",
        "description_summary": "에이즈 예방 캠페인, 감염인 권익 증진, 전문 인력 양성, 국제 기구 협력 사업",
    },
    {
        "category": "헬프데스크",
        "org_name": "한국한센복지협회",
        "dept_name": None,
        "phone": "02-753-2037",
        "description_summary": "한센병 조기 발견, 환자 진료, 이동 진료 및 상담, 정착 마을 복지 지원 사업",
    },

    # ── 복지·의료 ─────────────────────────────────────────────
    {
        "category": "복지·의료",
        "org_name": "보건복지부",
        "dept_name": None,
        "phone": "129",
        "description_summary": "보건의료·사회복지 정책 총괄, 건강보험, 복지 급여, 장애인 지원 등 보건복지 전반 안내",
    },
    {
        "category": "복지·의료",
        "org_name": "건강보험공단",
        "dept_name": None,
        "phone": "1577-1000",
        "description_summary": "건강보험 자격·보험료 관리, 국가 건강검진 대상자 확인, 노인장기요양보험 신청 및 등급 판정",
    },
    {
        "category": "복지·의료",
        "org_name": "건강보험심사평가원",
        "dept_name": None,
        "phone": "1644-2000",
        "description_summary": "진료비 적정성 심사 및 평가, 비급여 진료비 가격 공개, 의약품 안심 서비스, 보건의료 자원 현황",
    },
    {
        "category": "복지·의료",
        "org_name": "복지로",
        "dept_name": None,
        "phone": "129",
        "description_summary": "주요 복지 서비스 온라인 신청, 맞춤형 복지 급여 안내, 민간·공공 복지 자원 통합 정보 제공",
    },
    {
        "category": "복지·의료",
        "org_name": "국민연금공단",
        "dept_name": None,
        "phone": "1355",
        "description_summary": "국민연금 가입·수급 이력 관리, 노령·장애·유족연금, 기초연금 신청 대행 및 장애인 복지 지원",
    },

    # ── 감염병대응 ────────────────────────────────────────────
    {
        "category": "감염병대응",
        "org_name": "수도권질병대응센터",
        "dept_name": None,
        "phone": "02-361-5702",
        "description_summary": "서울·경기·인천 등 수도권 감염병 발생 대비 및 대응, 역학조사 지원 총괄",
    },
    {
        "category": "감염병대응",
        "org_name": "충청권질병대응센터",
        "dept_name": None,
        "phone": "042-229-1501",
        "description_summary": "대전·세종·충남·충북 등 충청 지역 감염병 발생 대비 및 대응, 역학조사 지원 총괄",
    },
    {
        "category": "감염병대응",
        "org_name": "경남권질병대응센터",
        "dept_name": None,
        "phone": "051-260-3701",
        "description_summary": "부산·울산·경남 등 경남 지역 감염병 발생 대비 및 대응, 역학조사 지원 총괄",
    },
    {
        "category": "감염병대응",
        "org_name": "경북권질병대응센터",
        "dept_name": None,
        "phone": "053-550-0601",
        "description_summary": "대구·경북 등 경북 지역 감염병 발생 대비 및 대응, 역학조사 지원 총괄",
    },
    {
        "category": "감염병대응",
        "org_name": "호남권질병대응센터",
        "dept_name": None,
        "phone": "062-221-4101",
        "description_summary": "광주·전남·전북·제주 등 호남 지역 감염병 발생 대비 및 대응, 역학조사 지원 총괄",
    },

    # ── 지역의료 ──────────────────────────────────────────────
    {
        "category": "지역의료",
        "org_name": "지역 보건소",
        "dept_name": None,
        "phone": "지역별 번호",
        "description_summary": "감염병 예방접종 및 지역 역학조사, 결핵·성병 진료 및 관리, 정신건강 상담, 영유아 건강검진 등 지역 보건 서비스",
    },
    {
        "category": "지역의료",
        "org_name": "국립마산병원",
        "dept_name": None,
        "phone": "055-249-5001",
        "description_summary": "결핵 입원 치료 전문 국립병원. 결핵 입원 문의, 결핵 검사 신청, 내성결핵 전문 치료",
    },
    {
        "category": "지역의료",
        "org_name": "국립목포병원",
        "dept_name": None,
        "phone": "061-280-1100",
        "description_summary": "결핵 입원 치료 전문 국립병원. 결핵 입원 문의, 결핵 검사 신청, 내성결핵 치료센터 운영",
    },

    # ── 응급 ─────────────────────────────────────────────────
    {
        "category": "응급",
        "org_name": "소방청 (119)",
        "dept_name": None,
        "phone": "119",
        "description_summary": "생명이 위급한 응급 상황에서 신속한 응급처치 및 병원 이송, 감염병 의심 증상 응급 신고",
    },

    # ── 행정 ─────────────────────────────────────────────────
    {
        "category": "행정",
        "org_name": "주민센터",
        "dept_name": None,
        "phone": "110",
        "description_summary": "주민등록 신고, 복지급여 신청, 긴급복지 지원, 재난지원금 신청 등 지역 행정 민원 처리",
    },
    {
        "category": "행정",
        "org_name": "정부24",
        "dept_name": None,
        "phone": "110",
        "description_summary": "민원 서류 온라인 신청 및 발급, 국가 보조금 혜택 확인, 생애주기별 통합 서비스 신청",
    },
    {
        "category": "행정",
        "org_name": "외국인종합안내센터",
        "dept_name": None,
        "phone": "1345",
        "description_summary": "외국인 비자 발급 및 체류 자격 변경 안내, 20개국 다국어 통역 서비스 지원",
    },

    # ── 질병관리청 전문 부서 (의료진·기관 대상) ─────────────────
    {
        "category": "전문부서",
        "org_name": "진단분석국 세균분석과",
        "dept_name": "세균분석과",
        "phone": "043-719-8110",
        "description_summary": "결핵·성매개·호흡기세균 감염병 진단, 감시, 분석 및 교육. 미생물 검사 및 병원체 분석 문의",
    },
    {
        "category": "전문부서",
        "org_name": "진단분석국 진단관리총괄과",
        "dept_name": "진단관리총괄과",
        "phone": "043-719-7840",
        "description_summary": "감염병 진단검사 체계 구축, 지자체 감염병 진단역량 강화, 감염병 검사기관 관리 문의",
    },
    {
        "category": "전문부서",
        "org_name": "의료안전예방국 의료감염관리과",
        "dept_name": "의료감염관리과",
        "phone": "043-719-7580",
        "description_summary": "의료관련감염병 예방·관리 총괄, 병원감염 관리 지침, 의료기관 감염관리 문의",
    },
    {
        "category": "전문부서",
        "org_name": "의료안전예방국 항생제내성관리과",
        "dept_name": "항생제내성관리과",
        "phone": "043-719-7530",
        "description_summary": "국가 항생제 내성 관리 대책, 내성균 감시 조사사업, CRE·VRSA·MRAB 등 내성균 관리 문의",
    },
    {
        "category": "전문부서",
        "org_name": "감염병위기관리국 검역정책과",
        "dept_name": "검역정책과",
        "phone": "043-719-9200",
        "description_summary": "검역 정책 총괄, 출입국 검역감염병 대응, 국립검역소 운영 및 해외 유입 감염병 관리 문의",
    },
    {
        "category": "전문부서",
        "org_name": "감염병정책국 감염병관리과",
        "dept_name": "감염병관리과",
        "phone": "043-719-7140",
        "description_summary": "B형·C형 바이러스 간염, 수인성·식품매개감염병 관리 총괄 문의",
    },
    {
        "category": "전문부서",
        "org_name": "감염병정책국 인수공통감염병관리과",
        "dept_name": "인수공통감염병관리과",
        "phone": "043-719-7160",
        "description_summary": "말라리아, 진드기 매개 감염병 관리, 인수공통감염병 예방대책 수립 문의",
    },

    # ── 지역 보건환경연구원 (검사 의뢰) ──────────────────────────
    {
        "category": "검사기관",
        "org_name": "지역 보건환경연구원",
        "dept_name": None,
        "phone": "지역별 번호",
        "description_summary": "각 시도별 감염병 검사 및 연구 수행. 미생물 검사, 수인성 감염병, 항생제 내성균, 바이러스, 매개체 감염병 등 지역 검사 의뢰 창구",
    },
]


async def embed_text(client: AsyncOpenAI, text: str) -> list[float]:
    resp = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return resp.data[0].embedding


def vec_to_pg(vec: list[float]) -> str:
    return "[" + ",".join(map(str, vec)) + "]"


async def main():
    print("DB 연결 중...")
    conn = await asyncpg.connect(DB_URL)
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    try:
        # 기존 데이터 전체 삭제
        await conn.execute("DELETE FROM transfer_agencies")
        print("기존 데이터 삭제 완료")

        # agency_id 시퀀스 리셋
        await conn.execute("ALTER SEQUENCE IF EXISTS transfer_agencies_agency_id_seq RESTART WITH 1")

        print(f"\n총 {len(AGENCIES)}개 기관 삽입 시작...")

        for i, agency in enumerate(AGENCIES, 1):
            # 임베딩 생성
            embed_text_input = f"{agency['org_name']} {agency.get('dept_name') or ''} {agency['description_summary']}"
            embedding = await embed_text(client, embed_text_input)
            vec_str = vec_to_pg(embedding)

            await conn.execute("""
                INSERT INTO transfer_agencies
                    (category, org_name, dept_name, phone, description, description_summary, description_embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7::vector)
            """,
                agency["category"],
                agency["org_name"],
                agency.get("dept_name"),
                agency["phone"],
                agency["description_summary"],   # description 컬럼도 같은 값으로
                agency["description_summary"],
                vec_str,
            )

            print(f"  [{i:2d}/{len(AGENCIES)}] {agency['category']} | {agency['org_name']} ✓")

        # 결과 확인
        count = await conn.fetchval("SELECT COUNT(*) FROM transfer_agencies")
        embed_count = await conn.fetchval("SELECT COUNT(*) FROM transfer_agencies WHERE description_embedding IS NOT NULL")
        print(f"\n완료: 총 {count}건 / 임베딩 {embed_count}건")

    finally:
        await conn.close()
        print("DB 연결 종료")


if __name__ == "__main__":
    asyncio.run(main())

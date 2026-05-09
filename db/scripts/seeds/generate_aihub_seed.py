"""
generate_aihub_seed.py
AI Hub 상담 데이터(merged_all_QA.json) → agents / calls / acw_cards 시드 SQL 생성

출력: db/scripts/seeds/aihub_seed.sql
  - agents   10명  (가짜 상담사, bcrypt 해시)
  - calls    63건  (세션당 1통화, 가짜 날짜/시간)
  - acw_cards 63건 (source='ai_hub', 모든 필드 임의 배정)

실행:
    python generate_aihub_seed.py
    python generate_aihub_seed.py --limit 30    # 상위 N개 세션만
    python generate_aihub_seed.py --output custom.sql
"""

import json
import random
import re
import argparse
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

# ──────────────────────────────────────────────────────────────
#  경로 설정
# ──────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent   # Togyether/Project
AIHUB_FILE   = PROJECT_ROOT / "data" / "merged_all_QA.json"
OUTPUT_FILE  = SCRIPT_DIR / "aihub_seed.sql"

# ──────────────────────────────────────────────────────────────
#  가짜 상담사 10명
# ──────────────────────────────────────────────────────────────
FAKE_AGENTS = [
    {"agent_id": 1,  "name": "김민지"},
    {"agent_id": 2,  "name": "이서연"},
    {"agent_id": 3,  "name": "박지현"},
    {"agent_id": 4,  "name": "최수아"},
    {"agent_id": 5,  "name": "정다은"},
    {"agent_id": 6,  "name": "한소희"},
    {"agent_id": 7,  "name": "오예진"},
    {"agent_id": 8,  "name": "임채원"},
    {"agent_id": 9,  "name": "송미래"},
    {"agent_id": 10, "name": "윤지수"},
]

# bcrypt("kdca1234!") — 사전 계산값, 공통 사용
# 실제 운영에서는 개별 해시 사용
BCRYPT_HASH = "$2b$12$LH7vWkuPGAFjTGN71KWu0.qFJETAfEFBCZ3e8kCzAq9DJgOAkqhsi"

# ──────────────────────────────────────────────────────────────
#  카테고리 매핑 (AI Hub 카테고리 → acw_cards 분류 필드)
# ──────────────────────────────────────────────────────────────
CATEGORY_MAP = {
    "기타문의": {
        "category": "기타",
        "category_major": "기타 문의",
        "category_mid": None,
        "disease_name": None,
        "customer_type": "citizen",
        "is_oos_prob": 0.6,          # is_oos 확률 (기타는 높게)
    },
    "의약품": {
        "category": "감염병",
        "category_major": "의약품",
        "category_mid": "치료제/의약품",
        "disease_name": None,
        "customer_type": "medical",
        "is_oos_prob": 0.3,
    },
    "증상/징후": {
        "category": "감염병",
        "category_major": "증상 및 징후",
        "category_mid": "임상 증상",
        "disease_name": None,
        "customer_type": "citizen",
        "is_oos_prob": 0.1,
    },
    "의료": {
        "category": "감염병",
        "category_major": "의료기관 문의",
        "category_mid": "의료기관 이용",
        "disease_name": None,
        "customer_type": "medical",
        "is_oos_prob": 0.2,
    },
    "신종플루": {
        "category": "감염병",
        "category_major": "감염병 현황",
        "category_mid": "신종인플루엔자",
        "disease_name": "신종인플루엔자",
        "customer_type": "citizen",
        "is_oos_prob": 0.05,
    },
    "신종인플루엔자": {
        "category": "감염병",
        "category_major": "감염병",
        "category_mid": "신종인플루엔자",
        "disease_name": "신종인플루엔자",
        "customer_type": "citizen",
        "is_oos_prob": 0.05,
    },
}

DEFAULT_CAT = {
    "category": "기타",
    "category_major": "기타 문의",
    "category_mid": None,
    "disease_name": None,
    "customer_type": "citizen",
    "is_oos_prob": 0.3,
}

OOS_REASONS = [
    "처방·진료 문의는 1339 범위 외입니다.",
    "해당 내용은 담당 의료기관에 직접 문의해 주시기 바랍니다.",
    "법률 해석이 필요한 사안으로 1339 답변 범위를 벗어납니다.",
    "개인 처방 관련 문의는 의사 또는 약사에게 문의해 주세요.",
]


# ──────────────────────────────────────────────────────────────
#  SQL 헬퍼 함수
# ──────────────────────────────────────────────────────────────
def sq(s):
    """문자열 → SQL 단일 인용 (None → NULL)"""
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def sq_jsonb(obj):
    """dict/list → SQL JSONB 리터럴 (None → NULL)"""
    if obj is None:
        return "NULL"
    raw = json.dumps(obj, ensure_ascii=False).replace("'", "''")
    return f"'{raw}'::jsonb"


def sq_ts(dt):
    """datetime → SQL TIMESTAMP 리터럴 (None → NULL)"""
    if dt is None:
        return "NULL"
    return f"'{dt.strftime('%Y-%m-%d %H:%M:%S')}'"


def sq_bool(b):
    """bool → SQL BOOLEAN (None → NULL)"""
    if b is None:
        return "NULL"
    return "TRUE" if b else "FALSE"


def sq_int(n):
    """int → SQL INT (None → NULL)"""
    if n is None:
        return "NULL"
    return str(n)


# ──────────────────────────────────────────────────────────────
#  카테고리 매칭 (부분 문자열 허용)
# ──────────────────────────────────────────────────────────────
def get_cat_info(raw_cat: str) -> dict:
    raw = raw_cat.strip()
    for key, info in CATEGORY_MAP.items():
        if key in raw or raw in key:
            return info
    return DEFAULT_CAT


# ──────────────────────────────────────────────────────────────
#  키워드 추출 (용어사전 + 지식베이스)
# ──────────────────────────────────────────────────────────────
def extract_keywords(rows: list) -> list:
    seen = set()
    result = []
    for row in rows:
        for field in ["용어사전", "지식베이스"]:
            val = row.get(field, "").strip()
            if not val:
                continue
            parts = re.split(r"[,/]", val)
            for p in parts:
                p = p.strip()
                if p and len(p) >= 2 and p not in seen:
                    seen.add(p)
                    result.append(p)
    return result[:12]


# ──────────────────────────────────────────────────────────────
#  세션 → 필드 변환
# ──────────────────────────────────────────────────────────────
def session_to_acw_fields(idx: int, rows: list, call_id: int,
                           agent_id: int, call_start: datetime,
                           call_end: datetime) -> dict:
    """하나의 AI Hub 세션을 acw_cards 행 dict로 변환"""

    cat_raw  = rows[0].get("카테고리", "기타문의")
    cat_info = get_cat_info(cat_raw)

    # Q/A 발화 분리
    q_turns = [r for r in rows
               if r["화자"] == "고객" and r.get("고객질문(요청)", "").strip()]
    a_turns = [r for r in rows
               if r["화자"] == "상담사" and r.get("상담사답변", "").strip()]

    # transcript TEXT
    lines = []
    for row in rows:
        if row["화자"] == "고객":
            q = row.get("고객질문(요청)", "").strip()
            if q:
                lines.append(f"고객: {q}")
        elif row["화자"] == "상담사":
            a = row.get("상담사답변", "").strip()
            if a:
                lines.append(f"상담사: {a}")
    transcript = "\n".join(lines) if lines else None

    # qa_summary JSONB: 최대 3 Q/A 쌍
    qa_pairs = []
    for q_row, a_row in zip(q_turns, a_turns):
        q_text = q_row.get("고객질문(요청)", "").strip()
        a_text = a_row.get("상담사답변", "").strip()
        if q_text and a_text:
            qa_pairs.append({"q": q_text, "a": a_text})
        if len(qa_pairs) >= 3:
            break

    # 고객 의도 목록
    intents = list(dict.fromkeys(
        r.get("고객의도", "").strip()
        for r in rows
        if r.get("고객의도", "").strip()
    ))

    # title
    main_intent = intents[0] if intents else cat_info["category_major"]
    title = f"{cat_info['category_major']} - {main_intent}"
    if len(title) > 195:
        title = title[:195] + "…"

    # disease_name (카테고리 기본값 우선, 없으면 키워드에서 추론)
    disease_name = cat_info["disease_name"]

    # keywords
    keywords = extract_keywords(rows)

    # is_oos (범위 외 여부)
    is_oos = random.random() < cat_info["is_oos_prob"]

    # ai_guidance JSONB
    first_q = q_turns[0].get("고객질문(요청)", "").strip() if q_turns else ""
    first_a = a_turns[0].get("상담사답변", "").strip() if a_turns else ""
    ai_guidance = {
        "query":        first_q,
        "disease_name": disease_name,
        "answer":       first_a if not is_oos and first_a else None,
        "is_oos":       is_oos,
        "oos_reason":   random.choice(OOS_REASONS) if is_oos else None,
        "sources":      [] if is_oos else [
            {
                "chunk_id":       random.randint(1, 500),
                "document_title": f"{disease_name or '감염병'} 관리지침",
                "section_title":  main_intent,
                "data_id":        "DATA-017",
            }
        ],
    }

    # ai_response_summary (단일 서술형 단락)
    if first_q and first_a and not is_oos:
        ai_response_summary = (
            f"고객은 '{first_q[:40]}' 관련 내용을 문의하였습니다. "
            f"AI 및 상담사는 '{first_a[:60]}' 라고 안내하였습니다. "
            f"상담은 정상 종료되었습니다."
        )
    elif is_oos:
        ai_response_summary = (
            f"고객이 {main_intent}에 대해 문의하였으나, 해당 내용은 "
            "1339 콜센터 답변 범위 외로 확인되어 안내 후 종료하였습니다."
        )
    else:
        ai_response_summary = None

    # ACW 시각 (통화 종료 직후)
    acw_started_at  = call_end
    acw_duration_sec = random.randint(60, 300)
    acw_ended_at    = acw_started_at + timedelta(seconds=acw_duration_sec)

    # 임의 필드
    customer_type   = cat_info.get("customer_type", "citizen")
    satisfaction    = random.choices([3, 4, 5], weights=[1, 3, 5])[0]
    is_resolved     = random.random() < 0.82
    is_transferred  = random.random() < 0.10
    transfer_target = random.choice([
        "질병관리청 감염병 담당부서", "관할 보건소", "응급의료정보센터", None
    ]) if is_transferred else None
    agent_used_ai   = random.choices(["yes", "partial", "no"], weights=[7, 2, 1])[0]

    return {
        "acw_id":               idx,
        "call_id":              call_id,
        "agent_id":             agent_id,
        "source":               "ai_hub",
        "title":                title,
        "customer_type":        customer_type,
        "customer_type_custom": None,
        "category":             cat_info["category"],
        "category_major":       cat_info["category_major"],
        "category_mid":         cat_info["category_mid"],
        "category_mid_list":    (
            [cat_info["category_mid"]] if cat_info["category_mid"] else None
        ),
        "category_mid_custom":  None,
        "disease_name":         disease_name,
        "qa_summary":           qa_pairs if qa_pairs else None,
        "transcript":           transcript,
        "ai_response_summary":  ai_response_summary,
        "is_transferred":       is_transferred,
        "transfer_target":      transfer_target,
        "keywords":             keywords if keywords else None,
        "satisfaction":         satisfaction,
        "agent_memo":           None,
        "is_resolved":          is_resolved,
        "agent_used_ai":        agent_used_ai,
        "acw_started_at":       acw_started_at,
        "acw_ended_at":         acw_ended_at,
        "acw_duration_sec":     acw_duration_sec,
        "created_at":           acw_ended_at,
        "ai_guidance":          ai_guidance,
    }


# ──────────────────────────────────────────────────────────────
#  SQL 블록 생성
# ──────────────────────────────────────────────────────────────
def build_agents_sql() -> str:
    lines = [
        "-- ============================================================",
        "--  1. agents (상담사 10명)",
        "-- ============================================================",
        "INSERT INTO agents (agent_id, name, password_hash, created_at)",
        "OVERRIDING SYSTEM VALUE VALUES",
    ]
    rows = []
    seed_dt = "2026-01-02 09:00:00"
    for a in FAKE_AGENTS:
        rows.append(
            f"  ({a['agent_id']}, {sq(a['name'])}, {sq(BCRYPT_HASH)}, '{seed_dt}')"
        )
    lines.append(",\n".join(rows) + ";")
    lines.append("SELECT setval('agents_agent_id_seq', 10, true);")
    return "\n".join(lines)


def build_calls_sql(call_records: list) -> str:
    lines = [
        "",
        "-- ============================================================",
        "--  2. calls (가짜 통화 세션)",
        "-- ============================================================",
        "INSERT INTO calls",
        "  (call_id, agent_id, status, conversation_history,",
        "   started_at, ended_at, duration_sec, created_at)",
        "OVERRIDING SYSTEM VALUE VALUES",
    ]
    rows = []
    for c in call_records:
        conv = []  # 간단한 conversation_history
        rows.append(
            f"  ({c['call_id']}, {c['agent_id']}, 'ended', '[]'::jsonb,\n"
            f"   {sq_ts(c['started_at'])}, {sq_ts(c['ended_at'])},\n"
            f"   {c['duration_sec']}, {sq_ts(c['started_at'])})"
        )
    lines.append(",\n".join(rows) + ";")
    lines.append(f"SELECT setval('calls_call_id_seq', {len(call_records)}, true);")
    return "\n".join(lines)


def build_acw_cards_sql(acw_records: list) -> str:
    col_names = (
        "acw_id, call_id, agent_id, source, title,\n"
        "    customer_type, customer_type_custom, category, category_major,\n"
        "    category_mid, category_mid_list, category_mid_custom, disease_name,\n"
        "    qa_summary, transcript, ai_response_summary,\n"
        "    is_transferred, transfer_target, keywords,\n"
        "    satisfaction, agent_memo, is_resolved, agent_used_ai,\n"
        "    acw_started_at, acw_ended_at, acw_duration_sec, created_at, ai_guidance"
    )
    lines = [
        "",
        "-- ============================================================",
        "--  3. acw_cards (source='ai_hub', 모든 필드 임의 배정)",
        "-- ============================================================",
        f"INSERT INTO acw_cards\n  ({col_names})\nOVERRIDING SYSTEM VALUE VALUES",
    ]
    rows = []
    for r in acw_records:
        row_sql = (
            f"  ({r['acw_id']}, {sq_int(r['call_id'])}, {sq_int(r['agent_id'])},\n"
            f"   {sq(r['source'])}, {sq(r['title'])},\n"
            f"   {sq(r['customer_type'])}, {sq(r['customer_type_custom'])},\n"
            f"   {sq(r['category'])}, {sq(r['category_major'])},\n"
            f"   {sq(r['category_mid'])}, {sq_jsonb(r['category_mid_list'])},\n"
            f"   {sq(r['category_mid_custom'])}, {sq(r['disease_name'])},\n"
            f"   {sq_jsonb(r['qa_summary'])},\n"
            f"   {sq(r['transcript'])},\n"
            f"   {sq(r['ai_response_summary'])},\n"
            f"   {sq_bool(r['is_transferred'])}, {sq(r['transfer_target'])},\n"
            f"   {sq_jsonb(r['keywords'])},\n"
            f"   {sq_int(r['satisfaction'])}, {sq(r['agent_memo'])},\n"
            f"   {sq_bool(r['is_resolved'])}, {sq(r['agent_used_ai'])},\n"
            f"   {sq_ts(r['acw_started_at'])}, {sq_ts(r['acw_ended_at'])},\n"
            f"   {sq_int(r['acw_duration_sec'])}, {sq_ts(r['created_at'])},\n"
            f"   {sq_jsonb(r['ai_guidance'])})"
        )
        rows.append(row_sql)
    lines.append(",\n".join(rows) + ";")
    lines.append(f"SELECT setval('acw_cards_acw_id_seq', {len(acw_records)}, true);")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
#  메인
# ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",  type=int, default=None,
                        help="상위 N개 세션만 사용 (기본: 전체)")
    parser.add_argument("--output", type=str, default=None,
                        help="출력 SQL 파일 경로")
    parser.add_argument("--seed",   type=int, default=42,
                        help="random seed (재현성용, 기본: 42)")
    args = parser.parse_args()

    random.seed(args.seed)
    out_path = Path(args.output) if args.output else OUTPUT_FILE

    # ── 데이터 로드 ───────────────────────────────────────────
    print(f"[1/4] AI Hub 데이터 로드: {AIHUB_FILE}")
    with open(AIHUB_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    sessions = defaultdict(list)
    for row in raw_data:
        sessions[row["대화셋일련번호"]].append(row)

    session_list = list(sessions.items())
    if args.limit:
        session_list = session_list[: args.limit]

    print(f"  → 세션 수: {len(session_list)}개")

    # ── 날짜 범위 설정 ────────────────────────────────────────
    # 2026-01-05 ~ 2026-05-04 (약 120일), 평일 근무 시간대
    BASE_DATE = datetime(2026, 1, 5)
    DATE_RANGE = 120  # 일수

    # ── 레코드 생성 ───────────────────────────────────────────
    print("[2/4] 통화 / ACW 레코드 생성 중…")
    call_records = []
    acw_records  = []

    for idx, (session_id, rows) in enumerate(session_list, start=1):
        # 임의 날짜/시간
        offset_days  = random.randint(0, DATE_RANGE)
        hour         = random.randint(9, 17)
        minute       = random.randint(0, 59)
        second       = random.randint(0, 59)
        call_start   = BASE_DATE + timedelta(days=offset_days,
                                             hours=hour, minutes=minute, seconds=second)
        duration_sec = random.randint(120, 600)
        call_end     = call_start + timedelta(seconds=duration_sec)

        agent_id = random.randint(1, len(FAKE_AGENTS))
        call_id  = idx

        # calls 레코드
        call_records.append({
            "call_id":      call_id,
            "agent_id":     agent_id,
            "started_at":   call_start,
            "ended_at":     call_end,
            "duration_sec": duration_sec,
        })

        # acw_cards 레코드
        acw = session_to_acw_fields(
            idx=idx,
            rows=rows,
            call_id=call_id,
            agent_id=agent_id,
            call_start=call_start,
            call_end=call_end,
        )
        acw_records.append(acw)

    # ── SQL 조립 ─────────────────────────────────────────────
    print("[3/4] SQL 파일 생성 중…")
    header = f"""\
-- ============================================================
--  AI Hub 상담 데이터 시드  (source='ai_hub')
--  생성: generate_aihub_seed.py
--  일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}
--
--  포함 테이블:
--    agents    {len(FAKE_AGENTS):>5}행
--    calls     {len(call_records):>5}행
--    acw_cards {len(acw_records):>5}행
--
--  실행 방법:
--    psql -U kdca_admin -d kdca_db -f aihub_seed.sql
-- ============================================================

BEGIN;
"""
    footer = "\nCOMMIT;\n"

    sql_body = (
        header
        + build_agents_sql()
        + build_calls_sql(call_records)
        + build_acw_cards_sql(acw_records)
        + footer
    )

    # ── 파일 저장 ────────────────────────────────────────────
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(sql_body)

    print(f"[4/4] 완료 → {out_path}")
    print(f"      agents   : {len(FAKE_AGENTS)}행")
    print(f"      calls    : {len(call_records)}행")
    print(f"      acw_cards: {len(acw_records)}행")
    print(f"\n실행: psql -U kdca_admin -d kdca_db -f {out_path.name}")


if __name__ == "__main__":
    main()

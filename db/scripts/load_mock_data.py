"""
mock_agents.json + mock_calls.json → DB 적재
- agents: agent_id 충돌 시 username/name 덮어쓰기, password = username
- calls: call_id 충돌 시 건너뜀
"""
import json
import asyncio
import asyncpg
import bcrypt
from pathlib import Path
from datetime import datetime

PARSED_DIR = Path(__file__).parent / "parsed"
DB_URL = "postgresql://kdca_admin:kdca_pwd1@localhost:5555/kdca_db"


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


async def load():
    conn = await asyncpg.connect(DB_URL)

    # ── agents ────────────────────────────────────────────
    with open(PARSED_DIR / "mock_agents.json", encoding="utf-8") as f:
        agents = json.load(f)

    print(f"[agents] {len(agents)}명 적재 중...")
    ok = skip = 0
    for a in agents:
        pw_hash = hash_pw(a["username"])  # 비밀번호 = username
        result = await conn.execute(
            """
            INSERT INTO agents (agent_id, username, name, password_hash)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (agent_id) DO UPDATE
              SET username      = EXCLUDED.username,
                  name          = EXCLUDED.name,
                  password_hash = EXCLUDED.password_hash
            """,
            a["agent_id"], a["username"], a["name"], pw_hash,
        )
        if result == "INSERT 0 1" or "UPDATE" in result:
            ok += 1
        else:
            skip += 1

    # sequence를 현재 max agent_id 이후로 맞추기
    await conn.execute(
        "SELECT setval('agents_agent_id_seq', (SELECT MAX(agent_id) FROM agents))"
    )
    print(f"  OK {ok}명 적재 완료")

    # ── calls ─────────────────────────────────────────────
    with open(PARSED_DIR / "mock_calls.json", encoding="utf-8") as f:
        calls = json.load(f)

    print(f"\n[calls] {len(calls)}건 적재 중...")
    ok = skip = 0
    for c in calls:
        started = datetime.fromisoformat(c["started_at"]) if c.get("started_at") else None
        ended = datetime.fromisoformat(c["ended_at"]) if c.get("ended_at") else None

        result = await conn.execute(
            """
            INSERT INTO calls (call_id, agent_id, status, started_at, ended_at, duration_sec)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (call_id) DO NOTHING
            """,
            c["call_id"],
            c["agent_id"],
            c["status"],
            started,
            ended,
            c.get("duration_sec"),
        )
        if result == "INSERT 0 0":
            skip += 1
        else:
            ok += 1

    # sequence 맞추기
    await conn.execute(
        "SELECT setval('calls_call_id_seq', (SELECT MAX(call_id) FROM calls))"
    )
    print(f"  OK {ok}건 적재, {skip}건 건너뜀")

    # ── 결과 확인 ──────────────────────────────────────────
    print("\n=== 최종 확인 ===")
    agent_count = await conn.fetchval("SELECT COUNT(*) FROM agents")
    call_count = await conn.fetchval("SELECT COUNT(*) FROM calls")
    print(f"  agents: {agent_count}명")
    print(f"  calls:  {call_count}건")

    rows = await conn.fetch("SELECT agent_id, username, name FROM agents ORDER BY agent_id")
    print("\n  agents 목록:")
    for r in rows:
        print(f"    [{r['agent_id']}] {r['username']} ({r['name']}) / pw: {r['username']}")

    await conn.close()
    print("\nDONE")


asyncio.run(load())

"""
의도분류 평가 — llm_session_test_30_labeled.json
Trigger Identification F1 + Category Accuracy
"""
import sys, os, json, asyncio
from pathlib import Path
from collections import defaultdict

BACKEND_ROOT = "/Users/juwon-i/2026/2026-1 캡스톤/Togyether/backend"
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

os.environ.setdefault("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@x/x")
os.environ.setdefault("JWT_SECRET_KEY", "eval-secret")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRE_MINUTES", "480")

from app.services.pipeline.llm_session import LLMSession

DATASET   = Path("/Users/juwon-i/2026/2026-1 캡스톤/프로젝트/pipeline/evaluation/chunk_driven/datasets/llm_session_test_30_labeled.json")
RESULTS   = Path("/Users/juwon-i/2026/2026-1 캡스톤/프로젝트/pipeline/evaluation/chunk_driven/results")
OUT_JSON  = RESULTS / "llm_session_eval_30.json"
OUT_TXT   = RESULTS / "llm_session_eval_30_summary.txt"
TOLERANCE = 1

OOS_MAP = {
    "action_required": "action_required",
    "transfer": "transfer",
    "realtime_local": "realtime_local",
    "unrelated": "unrelated",
}

def get_pred_category(result: dict) -> str | None:
    if result is None:
        return None
    if result.get("is_oos"):
        return OOS_MAP.get(result.get("oos_type",""), result.get("oos_type"))
    return result.get("category")


async def eval_conversation(conv: dict) -> dict:
    session = LLMSession()
    turns = conv["turns"]
    expected_events = conv.get("expected_events", [])

    # expected: {turn_idx: category}
    exp_map = {e["turn"]: (e.get("category") or e.get("oos_type")) for e in expected_events}
    exp_turns = sorted(exp_map.keys())

    fired = []  # (turn_idx, pred_category)

    for i, turn in enumerate(turns):
        if turn["role"] != "고객":
            continue
        turn_idx = i + 1
        try:
            result = await session.on_utterance(turn["text"], "고객")
            if result is not None:
                cat = get_pred_category(result)
                if cat:
                    fired.append((turn_idx, cat))
        except Exception:
            pass

    fired_turns = [t for t, _ in fired]
    fired_map   = {t: c for t, c in fired}

    # greedy 매칭
    used = set()
    matched_id  = []  # (exp_turn, fired_turn)
    matched_cls = []  # (exp_turn, fired_turn) where category also matches

    for et in exp_turns:
        best = None
        for ft in sorted(fired_turns):
            if ft in used:
                continue
            if abs(ft - et) <= TOLERANCE:
                if best is None or abs(ft - et) < abs(best - et):
                    best = ft
        if best is not None:
            matched_id.append((et, best))
            used.add(best)
            if fired_map.get(best) == exp_map[et]:
                matched_cls.append((et, best))

    return {
        "conversation_id": conv["conversation_id"],
        "n_exp":      len(exp_turns),
        "n_fired":    len(fired_turns),
        "n_matched":  len(matched_id),
        "n_cls_ok":   len(matched_cls),
        "exp_map":    exp_map,
        "fired_map":  fired_map,
    }


async def main():
    with open(DATASET) as f:
        data = json.load(f)
    print(f"[데이터] {len(data)}개 대화")

    results = []
    for i, conv in enumerate(data):
        r = await eval_conversation(conv)
        results.append(r)
        print(f"  [{i+1:2d}/{len(data)}] {conv['conversation_id']:<12} "
              f"exp={r['n_exp']} fired={r['n_fired']} match={r['n_matched']} cls={r['n_cls_ok']}")

    # 전체 집계
    n_exp     = sum(r["n_exp"]     for r in results)
    n_fired   = sum(r["n_fired"]   for r in results)
    n_matched = sum(r["n_matched"] for r in results)
    n_cls_ok  = sum(r["n_cls_ok"]  for r in results)

    prec_id  = n_matched / n_fired   if n_fired   else 0
    rec_id   = n_matched / n_exp     if n_exp     else 0
    f1_id    = 2*prec_id*rec_id / (prec_id+rec_id) if (prec_id+rec_id) else 0

    prec_cls = n_cls_ok / n_fired   if n_fired   else 0
    rec_cls  = n_cls_ok / n_exp     if n_exp     else 0
    f1_cls   = 2*prec_cls*rec_cls / (prec_cls+rec_cls) if (prec_cls+rec_cls) else 0

    cat_acc  = n_cls_ok / n_matched if n_matched else 0

    # 카테고리별 집계
    by_cat = defaultdict(lambda: {"n_exp":0,"n_matched":0,"n_cls_ok":0})
    for r in results:
        for et, pred_turn in zip(sorted(r["exp_map"]), []):
            pass
        for et, cat in r["exp_map"].items():
            by_cat[cat]["n_exp"] += 1
        for et, ft in zip(sorted(r["exp_map"]), []):
            pass
        # matched_cls 재계산
        used = set()
        exp_turns = sorted(r["exp_map"].keys())
        fired_turns = sorted(r["fired_map"].keys())
        for et in exp_turns:
            best = None
            for ft in fired_turns:
                if ft in used: continue
                if abs(ft - et) <= TOLERANCE:
                    if best is None or abs(ft-et) < abs(best-et):
                        best = ft
            cat = r["exp_map"][et]
            if best is not None:
                used.add(best)
                by_cat[cat]["n_matched"] += 1
                if r["fired_map"].get(best) == cat:
                    by_cat[cat]["n_cls_ok"] += 1

    lines = []
    lines.append("=" * 55)
    lines.append("의도분류 평가 결과 (30개 대화)")
    lines.append("=" * 55)
    lines.append(f"  대화 수        : {len(data)}개")
    lines.append(f"  총 expected    : {n_exp}개")
    lines.append(f"  총 fired       : {n_fired}개")
    lines.append(f"  matched (±1턴) : {n_matched}개")
    lines.append(f"  category 일치  : {n_cls_ok}개")
    lines.append("")
    lines.append(f"  Trigger ID  F1 : {f1_id:.4f}  (P={prec_id:.4f} R={rec_id:.4f})")
    lines.append(f"  Trigger Cls F1 : {f1_cls:.4f}  (P={prec_cls:.4f} R={rec_cls:.4f})")
    lines.append(f"  Category Acc   : {cat_acc:.4f}")
    lines.append("")
    lines.append(f"{'카테고리':<25} {'n_exp':>6} {'matched':>8} {'cls_ok':>8} {'acc':>8}")
    lines.append("-" * 58)
    for cat, v in sorted(by_cat.items()):
        acc = v["n_cls_ok"] / v["n_matched"] if v["n_matched"] else 0
        lines.append(f"  {cat:<23} {v['n_exp']:>6} {v['n_matched']:>8} {v['n_cls_ok']:>8} {acc:>8.4f}")

    summary = "\n".join(lines)
    print("\n" + summary)

    with open(OUT_TXT, "w") as f: f.write(summary)
    with open(OUT_JSON, "w") as f:
        json.dump({
            "n_conversations": len(data),
            "total": {"n_exp":n_exp,"n_fired":n_fired,"n_matched":n_matched,"n_cls_ok":n_cls_ok,
                      "trigger_id_f1":f1_id,"trigger_cls_f1":f1_cls,"category_accuracy":cat_acc},
            "by_category": {k: dict(v) for k,v in by_cat.items()},
        }, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {OUT_JSON}")

if __name__ == "__main__":
    asyncio.run(main())

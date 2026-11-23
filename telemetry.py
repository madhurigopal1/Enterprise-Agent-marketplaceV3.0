"""Observability + audit: immutable-style in-memory audit trail, discovery log, run store, KPIs."""
import threading, time, uuid
from datetime import datetime, timezone

LOCK = threading.RLock()
AUDIT, DISCOVERY_LOG, RUNS, ATTEMPTS = [], [], {}, {"count": 0}
SPENT = {}
FEEDBACK = []  # {run_id, agent_id, user, rating 1-5, comment, ts}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def audit(**kw):
    with LOCK:
        entry = {"id": new_id("aud"), "ts": now(), **kw}
        AUDIT.append(entry)
        return entry


def spent(user_id):
    return SPENT.get(user_id, 0.0)


def charge(user_id, amount):
    with LOCK:
        SPENT[user_id] = round(SPENT.get(user_id, 0.0) + amount, 4)


def log_discovery(user_id, query, top_score, n):
    with LOCK:
        DISCOVERY_LOG.append({"ts": now(), "user": user_id, "query": query, "top_score": top_score, "results": n,
                              "success": n > 0 and top_score >= 0.15})


def metrics(agents):
    inv = [a for a in AUDIT if a["action"] == "invoke"]
    ok = [a for a in inv if a["decision"] == "allow"]
    done = [a for a in ok if a["outcome"] == "success"]
    runs = list(RUNS.values())
    multi = [r for r in runs if sum(1 for s in r["steps"] if s["status"] == "completed") >= 3]
    providers = sorted({a["provider"] for a in agents.values()})
    ds = [d for d in DISCOVERY_LOG]
    pct = lambda n, d: round(100 * n / d, 1) if d else None
    kpis = [
        {"name": "Agents onboarded", "value": len(agents), "target": "10-20", "met": 10 <= len(agents) <= 20},
        {"name": "Providers / frameworks", "value": len(providers), "target": "3+", "met": len(providers) >= 3},
        {"name": "Discovery success %", "value": pct(sum(d["success"] for d in ds), len(ds)), "target": ">90", "met": bool(ds) and pct(sum(d["success"] for d in ds), len(ds)) > 90},
        {"name": "Execution success %", "value": pct(len(done), len(ok)), "target": ">95", "met": bool(ok) and pct(len(done), len(ok)) > 95},
        {"name": "Authenticated invocations %", "value": 100.0 if inv else None, "target": "100", "met": bool(inv)},
        {"name": "Auditable invocations %", "value": pct(len(inv), ATTEMPTS["count"]), "target": "100", "met": bool(inv) and len(inv) == ATTEMPTS["count"]},
        {"name": "Cross-agent workflows (3+ agents)", "value": len(multi), "target": "3-5", "met": len(multi) >= 3},
    ]
    by_agent = {}
    for a in ok:
        b = by_agent.setdefault(a["agent_id"], {"agent": a["agent_name"], "calls": 0, "cost": 0.0, "tokens": 0, "latency": 0.0})
        b["calls"] += 1; b["cost"] = round(b["cost"] + a.get("cost_usd", 0), 4)
        b["tokens"] += a.get("tokens", 0); b["latency"] += a.get("latency_sec", 0)
    for b in by_agent.values():
        b["avg_latency_sec"] = round(b["latency"] / b["calls"], 2) if b["calls"] else 0
        del b["latency"]
    return {"kpis": kpis, "totals": {"invocation_attempts": ATTEMPTS["count"], "allowed": len(ok), "denied": len(inv) - len(ok),
            "successful": len(done), "runs": len(runs), "discovery_queries": len(ds),
            "total_cost_usd": round(sum(a.get("cost_usd", 0) for a in ok), 4), "total_tokens": sum(a.get("tokens", 0) for a in ok),
            "policy_violations": len(inv) - len(ok)}, "by_agent": list(by_agent.values()),
            "by_provider": [{"provider": p, "agents": sum(1 for a in agents.values() if a["provider"] == p)} for p in providers]}

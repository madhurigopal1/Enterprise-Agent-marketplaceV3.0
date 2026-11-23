"""Agent Orchestration layer: intent -> discovery -> plan -> governed execution -> unified result."""
from . import registry, security, telemetry as T
from .adapters import get_adapter

MAX_AGENTS = 6


def plan(intent: str, agent_ids=None):
    if agent_ids:
        picks = [{"agent_id": a, "score": 1.0, "matched_terms": ["manually selected"]} for a in agent_ids if a in registry.AGENTS]
    else:
        found = registry.discover(intent)
        if not found:
            return []
        top = found[0]["score"]
        picks = [f for f in found if f["score"] >= max(0.15, 0.2 * top)][:MAX_AGENTS]
    picks.sort(key=lambda p: (registry.AGENTS[p["agent_id"]]["stage"], -p["score"]))
    steps = []
    for i, p in enumerate(picks):
        a = registry.AGENTS[p["agent_id"]]
        steps.append({"idx": i, "agent_id": a["id"], "agent_name": a["name"], "provider": a["provider"], "version": a["version"],
                      "stage": a["stage"], "relevance": p["score"], "matched_terms": p["matched_terms"], "status": "pending",
                      "approved": False, "decision": None, "output": None, "metrics": None, "delegation": None, "note": None})
    return steps


def create_run(user, intent, input_text, agent_ids=None):
    run_id = T.new_id("run")
    steps = plan(intent, agent_ids)
    run = {"id": run_id, "user": user["id"], "user_name": user["name"], "role": user["role"], "intent": intent,
           "input_text": input_text, "created": T.now(), "status": "running", "steps": steps, "result": None}
    with T.LOCK:
        T.RUNS[run_id] = run
    if not steps:
        run["status"] = "failed"
        run["result"] = {"headline": "No matching agents were found for this intent.", "sections": [], "blocked": [], "totals": {}}
        return run
    advance(run, user)
    return run


def _upstream(run):
    return {s["agent_id"]: s["output"] for s in run["steps"] if s["status"] == "completed" and s["output"]}


def _record(user, agent, run, step, decision, outcome, res=None, reason=None):
    with T.LOCK:
        T.ATTEMPTS["count"] += 1
        T.audit(action="invoke", run_id=run["id"], user=user["id"], user_name=user["name"], role=user["role"],
                agent_id=agent["id"], agent_name=agent["name"], agent_version=agent["version"], provider=agent["provider"],
                decision=decision, outcome=outcome, reason=reason, resources=agent["required_resources"],
                model=(res or {}).get("model") or agent["models"][0], tokens=((res or {}).get("tokens_in", 0) + (res or {}).get("tokens_out", 0)),
                cost_usd=(res or {}).get("cost_usd", 0.0), latency_sec=(res or {}).get("simulated_latency_sec", 0.0),
                delegation=step.get("delegation"), checks=step["decision"]["checks"] if step.get("decision") else [])


def advance(run, user):
    for step in run["steps"]:
        if step["status"] not in ("pending",):
            continue
        agent = registry.AGENTS[step["agent_id"]]
        decision = security.evaluate(user, agent, T.spent(user["id"]))
        step["decision"] = decision
        if not decision["allowed"]:
            step["status"], step["note"] = "blocked", decision["reason"]
            _record(user, agent, run, step, "deny", "blocked", reason=decision["reason"])
            continue
        if agent["requires_approval"] and not step["approved"]:
            step["status"], step["note"] = "awaiting_approval", "Human approval required before this agent runs"
            run["status"] = "awaiting_approval"
            T.audit(action="approval_requested", run_id=run["id"], user=user["id"], user_name=user["name"], role=user["role"],
                    agent_id=agent["id"], agent_name=agent["name"], decision="pending", outcome="waiting", reason=step["note"])
            return run
        step["delegation"] = security.delegation_for(user, agent, run["id"])
        try:
            res = get_adapter(agent["provider"]).invoke(agent, run["input_text"], _upstream(run))
            step["output"], step["status"] = res.pop("output"), "completed"
            step["metrics"] = res
            T.charge(user["id"], res["cost_usd"])
            _record(user, agent, run, step, "allow", "success", res)
        except Exception as e:  # pragma: no cover
            step["status"], step["note"] = "failed", str(e)
            _record(user, agent, run, step, "allow", "failure", reason=str(e))
    _finalize(run)
    return run


def decide(run, user, agent_id, approve: bool, comment: str = ""):
    if not security.can_approve(user, run):
        raise PermissionError("Only the requester, a Platform Admin or a Compliance Officer can decide on this approval")
    step = next((s for s in run["steps"] if s["agent_id"] == agent_id and s["status"] == "awaiting_approval"), None)
    if not step:
        raise ValueError("No pending approval for that agent in this run")
    T.audit(action="approval", run_id=run["id"], user=user["id"], user_name=user["name"], role=user["role"], agent_id=agent_id,
            agent_name=step["agent_name"], decision="approve" if approve else "reject", outcome="recorded", reason=comment or None)
    step["approval"] = {"by": user["name"], "role": user["role"], "approve": approve, "comment": comment or None, "ts": T.now()}
    run["status"] = "running"
    if approve:
        step["approved"], step["status"], step["note"] = True, "pending", None
    else:
        step["status"], step["note"] = "rejected", f"Rejected by {user['name']}" + (f": {comment}" if comment else "")
    owner = security.USERS[run["user"]]
    return advance(run, owner)


def _finalize(run):
    steps = run["steps"]
    done = [s for s in steps if s["status"] == "completed"]
    run["status"] = ("completed" if len(done) == len(steps) else "partial" if done else "failed")
    verdicts = [s["output"].get("verdict", "") for s in done if s["output"]]
    if any(v == "Not ready" for v in verdicts): headline = "Not ready - significant gaps need to be resolved."
    elif any(v == "Needs refinement" for v in verdicts): headline = "Needs refinement before proceeding."
    elif done and any(v == "Ready" for v in verdicts):
        headline = "Ready for development" + (" - security controls must be applied." if any("High risk" in v for v in verdicts) else ".")
    elif done: headline = "Assessment completed successfully."
    else: headline = "No agent could be executed under your permissions."
    recs, seen = [], set()
    for s in done:
        for r in (s["output"].get("recommendations") or []):
            if r not in seen:
                seen.add(r); recs.append({"agent": s["agent_name"], "text": r})
    blocked = [{"agent": s["agent_name"], "status": s["status"], "reason": s["note"]} for s in steps if s["status"] in ("blocked", "rejected", "failed")]
    totals = {"agents_run": len(done), "cost_usd": round(sum(s["metrics"]["cost_usd"] for s in done), 4),
              "tokens": sum(s["metrics"]["tokens_in"] + s["metrics"]["tokens_out"] for s in done),
              "simulated_latency_sec": round(sum(s["metrics"]["simulated_latency_sec"] for s in done), 2)}
    run["result"] = {"headline": headline,
                     "sections": [{"agent": s["agent_name"], "provider": s["provider"], "verdict": s["output"].get("verdict"),
                                   "summary": s["output"].get("summary"), "findings": s["output"].get("findings", [])[:6],
                                   "data": s["output"].get("data", {})} for s in done],
                     "recommendations": recs[:10], "blocked": blocked, "totals": totals}


def pending_approvals(user):
    """Approval inbox: every step waiting for a human decision that this user may decide."""
    items = []
    for run in list(T.RUNS.values()):
        if run["status"] != "awaiting_approval" or not security.can_approve(user, run):
            continue
        for s in run["steps"]:
            if s["status"] == "awaiting_approval":
                a = registry.AGENTS[s["agent_id"]]
                items.append({"run_id": run["id"], "intent": run["intent"], "requested_by": run["user_name"],
                              "requester_role": run["role"], "created": run["created"], "agent_id": s["agent_id"],
                              "agent_name": s["agent_name"], "provider": s["provider"],
                              "data_classification": a["data_classification"], "cost_per_call": a["cost_per_call"],
                              "required_resources": a["required_resources"], "reason": s["note"],
                              "input_preview": (run["input_text"] or "")[:240]})
    return sorted(items, key=lambda x: x["created"], reverse=True)

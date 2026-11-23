"""Enterprise Agentic Web - POC API (FastAPI). Run: python run.py  -> http://localhost:8000"""
from pathlib import Path
import os, time, uuid
from typing import List, Optional
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
import csv, io
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import orchestrator, registry, security, telemetry as T

APP_VERSION = "1.1.0-features"
app = FastAPI(title="Enterprise Agentic Web POC", version=APP_VERSION,
              description="Unified, governed marketplace for AI agents (simulated providers).")
STATIC = Path(__file__).parent / "static"

app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    cid = request.headers.get("X-Correlation-ID") or f"req-{uuid.uuid4().hex[:12]}"
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = cid
    response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - t0) * 1000:.2f}"
    response.headers["X-App-Version"] = APP_VERSION
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    # Never let the browser keep an old UI build (root cause of the missing Approvals tab).
    path = request.url.path
    if path == "/" or path.startswith("/static/") or path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token. POST /api/login first.")
    user = security.verify_token(authorization.split(" ", 1)[1])
    if not user:
        raise HTTPException(401, "Invalid or expired token")
    return user


class LoginReq(BaseModel):
    user_id: str


class DiscoverReq(BaseModel):
    query: str = Field(min_length=2)


class RunReq(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    intent: str = Field(min_length=2)
    input_text: str = ""
    agent_ids: Optional[List[str]] = None


class DecisionReq(BaseModel):
    agent_id: str
    approve: bool
    comment: str = Field(default="", max_length=500)


class BulkItem(BaseModel):
    run_id: str
    agent_id: str


class BulkDecisionReq(BaseModel):
    items: List[BulkItem] = Field(min_length=1, max_length=50)
    approve: bool
    comment: str = Field(default="", max_length=500)


class FeedbackReq(BaseModel):
    agent_id: str
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=500)


class SuspendReq(BaseModel):
    suspended: bool
    reason: str = Field(default="", max_length=200)


class RegisterReq(BaseModel):
    id: str
    name: str
    provider: str
    description: str
    owner: str
    capabilities: List[str]
    tasks: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    data_classification: str = "Internal"
    allowed_roles: List[str] = Field(default_factory=lambda: ["*"])
    regions: List[str] = Field(default_factory=lambda: ["All"])
    required_resources: List[str] = Field(default_factory=lambda: ["knowledge-base"])
    requires_approval: bool = False
    cost_per_call: float = 0.02
    version: str = "0.1"
    tools: List[str] = Field(default_factory=list)
    models: List[str] = Field(default_factory=list)


class LifecycleReq(BaseModel):
    target: str


class SimReq(BaseModel):
    user_id: str
    agent_id: str


@app.get("/", include_in_schema=False)
def index():
    # Inject the build version so JS/CSS URLs change on every release (cache busting).
    html = (STATIC / "index.html").read_text(encoding="utf-8").replace("__APP_VERSION__", APP_VERSION)
    return HTMLResponse(html)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": APP_VERSION, "agents": len(registry.AGENTS), "mode": "simulation"}


@app.get("/api/version")
def version():
    ui = (STATIC / "index.html").read_text(encoding="utf-8")
    return {"version": APP_VERSION, "ui_has_approvals_tab": 'data-tab="approvals"' in ui,
            "static_dir": str(STATIC.resolve())}


@app.get("/api/ready")
def ready():
    checks = {"registry": bool(registry.AGENTS), "static_ui": (STATIC / "index.html").exists(),
              "approvals_ui": 'data-tab="approvals"' in (STATIC / "index.html").read_text(encoding="utf-8")}
    if not all(checks.values()):
        raise HTTPException(503, {"status": "not_ready", "checks": checks})
    return {"status": "ready", "version": APP_VERSION, "checks": checks}


@app.get("/api/users")
def users():
    return [{k: u[k] for k in ("id", "name", "role", "persona", "region", "clearance")} for u in security.USERS.values()]


@app.post("/api/login")
def login(req: LoginReq):
    if req.user_id not in security.USERS:
        raise HTTPException(404, "Unknown user")
    return {"token": security.issue_token(req.user_id), "user": security.USERS[req.user_id]}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {**user, "spent_usd": T.spent(user["id"]), "remaining_usd": round(user["budget_usd"] - T.spent(user["id"]), 4)}


def _view(a, user):
    ev = security.evaluate(user, a, T.spent(user["id"]))
    return {**a, "access": {"allowed": ev["allowed"], "reason": ev["reason"]}}


@app.get("/api/agents")
def list_agents(status: Optional[str] = None, provider: Optional[str] = None, user=Depends(current_user)):
    out = [_view(a, user) for a in registry.AGENTS.values()]
    if status: out = [a for a in out if a["status"] == status]
    if provider: out = [a for a in out if a["provider"] == provider]
    return out


@app.get("/api/agents/{agent_id}")
def get_agent(agent_id: str, user=Depends(current_user)):
    if agent_id not in registry.AGENTS:
        raise HTTPException(404, "Agent not found")
    a = registry.AGENTS[agent_id]
    return {**_view(a, user), "policy_checks": security.evaluate(user, a, T.spent(user["id"]))["checks"]}


@app.post("/api/agents", status_code=201)
def register_agent(req: RegisterReq, user=Depends(current_user)):
    if user["role"] not in ("Agent Owner", "Platform Admin"):
        raise HTTPException(403, "Only Agent Owners or Platform Admins can register agents")
    errs = registry.validate_registration(req.model_dump())
    if errs:
        raise HTTPException(422, errs)
    a = registry.register(req.model_dump())
    T.audit(action="register", user=user["id"], user_name=user["name"], role=user["role"], agent_id=a["id"], agent_name=a["name"],
            decision="allow", outcome="registered", reason=None)
    return a


@app.post("/api/agents/{agent_id}/lifecycle")
def lifecycle(agent_id: str, req: LifecycleReq, user=Depends(current_user)):
    if user["role"] != "Platform Admin":
        raise HTTPException(403, "Only Platform Admins can change agent lifecycle (certification gate)")
    if agent_id not in registry.AGENTS:
        raise HTTPException(404, "Agent not found")
    if req.target not in registry.LIFECYCLE:
        raise HTTPException(422, f"target must be one of {registry.LIFECYCLE}")
    try:
        a = registry.promote(agent_id, req.target)
    except ValueError as e:
        raise HTTPException(409, str(e))
    T.audit(action="lifecycle", user=user["id"], user_name=user["name"], role=user["role"], agent_id=agent_id, agent_name=a["name"],
            decision="allow", outcome=f"-> {req.target}", reason=None)
    return a


@app.post("/api/discover")
def discover(req: DiscoverReq, user=Depends(current_user)):
    res = registry.discover(req.query)
    items = []
    for r in res[:8]:
        v = _view(registry.AGENTS[r["agent_id"]], user)
        items.append({**r, "agent": v})
    T.log_discovery(user["id"], req.query, items[0]["score"] if items else 0, len(items))
    return {"query": req.query, "results": items}


@app.post("/api/runs", status_code=201)
def create_run(req: RunReq, user=Depends(current_user)):
    if req.agent_ids:
        unknown = sorted(set(req.agent_ids) - set(registry.AGENTS))
        if unknown:
            raise HTTPException(422, {"unknown_agent_ids": unknown})
        if len(req.agent_ids) > orchestrator.MAX_AGENTS:
            raise HTTPException(422, f"A run supports at most {orchestrator.MAX_AGENTS} agents")
    return orchestrator.create_run(user, req.intent, req.input_text, req.agent_ids)


@app.get("/api/runs")
def list_runs(user=Depends(current_user)):
    runs = [r for r in T.RUNS.values() if r["user"] == user["id"] or user["role"] in ("Platform Admin", "Compliance Officer")]
    return [{k: r[k] for k in ("id", "intent", "status", "user_name", "created")} | {"agents": len(r["steps"])} for r in reversed(runs)]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, user=Depends(current_user)):
    r = T.RUNS.get(run_id)
    if not r or (r["user"] != user["id"] and user["role"] not in ("Platform Admin", "Compliance Officer")):
        raise HTTPException(404, "Run not found")
    return r


@app.get("/api/approvals")
def approvals(user=Depends(current_user)):
    """Human-in-the-loop inbox for the signed-in user."""
    return orchestrator.pending_approvals(user)


@app.post("/api/runs/{run_id}/decision")
def decide(run_id: str, req: DecisionReq, user=Depends(current_user)):
    r = T.RUNS.get(run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    try:
        _check_reason(req.approve, req.comment)
        return orchestrator.decide(r, user, req.agent_id, req.approve, req.comment.strip())
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


REQUIRE_REJECT_REASON = os.getenv("POC_REQUIRE_REJECT_REASON", "false").lower() == "true"


def _check_reason(approve: bool, comment: str):
    """UI always asks for a reason; set POC_REQUIRE_REJECT_REASON=true to enforce it for API clients too."""
    if not approve and REQUIRE_REJECT_REASON and len(comment.strip()) < 3:
        raise HTTPException(422, "A reason (at least 3 characters) is required to reject")


@app.post("/api/approvals/bulk")
def bulk_decide(req: BulkDecisionReq, user=Depends(current_user)):
    _check_reason(req.approve, req.comment)
    results = []
    for it in req.items:
        r = T.RUNS.get(it.run_id)
        try:
            if not r:
                raise ValueError("Run not found")
            orchestrator.decide(r, user, it.agent_id, req.approve, req.comment.strip())
            results.append({"run_id": it.run_id, "agent_id": it.agent_id, "ok": True})
        except (PermissionError, ValueError) as e:
            results.append({"run_id": it.run_id, "agent_id": it.agent_id, "ok": False, "error": str(e)})
    return {"decided": sum(x["ok"] for x in results), "results": results}


@app.post("/api/runs/{run_id}/feedback", status_code=201)
def feedback(run_id: str, req: FeedbackReq, user=Depends(current_user)):
    r = T.RUNS.get(run_id)
    if not r or r["user"] != user["id"]:
        raise HTTPException(404, "Run not found")
    if not any(s["agent_id"] == req.agent_id and s["status"] == "completed" for s in r["steps"]):
        raise HTTPException(409, "You can only rate an agent that completed in this run")
    with T.LOCK:
        T.FEEDBACK[:] = [f for f in T.FEEDBACK if not (f["run_id"] == run_id and f["agent_id"] == req.agent_id)]
        entry = {"run_id": run_id, "agent_id": req.agent_id, "user": user["id"], "rating": req.rating,
                 "comment": req.comment.strip() or None, "ts": T.now()}
        T.FEEDBACK.append(entry)
    return entry


@app.get("/api/agents/{agent_id}/feedback")
def agent_feedback(agent_id: str, user=Depends(current_user)):
    if agent_id not in registry.AGENTS:
        raise HTTPException(404, "Agent not found")
    rows = [f for f in T.FEEDBACK if f["agent_id"] == agent_id]
    avg = round(sum(f["rating"] for f in rows) / len(rows), 2) if rows else None
    return {"agent_id": agent_id, "count": len(rows), "average": avg, "items": list(reversed(rows))[:20]}


@app.post("/api/agents/{agent_id}/suspend")
def suspend(agent_id: str, req: SuspendReq, user=Depends(current_user)):
    if user["role"] != "Platform Admin":
        raise HTTPException(403, "Only Platform Admins can use the kill switch")
    a = registry.AGENTS.get(agent_id)
    if not a:
        raise HTTPException(404, "Agent not found")
    a["suspended"], a["suspended_reason"] = req.suspended, (req.reason.strip() or None) if req.suspended else None
    T.audit(action="suspend" if req.suspended else "resume", user=user["id"], user_name=user["name"], role=user["role"],
            agent_id=agent_id, agent_name=a["name"], decision="allow", outcome="suspended" if req.suspended else "active",
            reason=a["suspended_reason"])
    return a


@app.get("/api/runs/{run_id}/report", response_class=PlainTextResponse)
def run_report(run_id: str, user=Depends(current_user)):
    r = get_run(run_id, user)
    res = r.get("result") or {}
    L = [f"# Agent run report {r['id']}", "", f"- Requested by: {r['user_name']} ({r['role']})", f"- Created: {r['created']}",
         f"- Intent: {r['intent']}", f"- Status: {r['status']}", f"- Headline: {res.get('headline', 'n/a')}", "",
         "> Simulated POC output. Providers and agent logic are deterministic demo code.", "", "## Steps", ""]
    for i, s in enumerate(r["steps"], 1):
        L.append(f"### {i}. {s['agent_name']} ({s['provider']} v{s['version']}) - {s['status']}")
        if s.get("note"): L.append(f"- Note: {s['note']}")
        if s.get("approval"):
            ap = s["approval"]; L.append(f"- Human decision: {'approved' if ap['approve'] else 'rejected'} by {ap['by']} ({ap['role']}) at {ap['ts']}" + (f" - {ap['comment']}" if ap['comment'] else ""))
        if s.get("output"):
            L.append(f"- Verdict: {s['output'].get('verdict')}"); L.append(f"- Summary: {s['output'].get('summary')}")
        if s.get("delegation"): L.append(f"- Scopes: {', '.join(s['delegation']['scopes'])}")
        L.append("")
    if res.get("recommendations"):
        L += ["## Recommendations", ""] + [f"- {x['text']} ({x['agent']})" for x in res["recommendations"]]
    return "\n".join(L) + "\n"


@app.get("/api/audit/export")
def audit_export(user=Depends(current_user)):
    if user["role"] not in ("Platform Admin", "Compliance Officer"):
        raise HTTPException(403, "Only Platform Admins and Compliance Officers can export the audit log")
    cols = ["ts", "id", "action", "run_id", "user", "user_name", "role", "agent_id", "agent_name", "provider", "decision", "outcome", "reason", "cost_usd", "tokens"]
    buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore"); w.writeheader()
    for a in T.AUDIT:
        w.writerow({k: a.get(k, "") for k in cols})
    T.audit(action="audit_export", user=user["id"], user_name=user["name"], role=user["role"], decision="allow", outcome=f"{len(T.AUDIT)} rows", reason=None)
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=audit-log.csv"})


@app.get("/api/audit")
def audit_log(limit: int = 200, user=Depends(current_user)):
    limit = max(1, min(limit, 1000))
    rows = T.AUDIT if user["role"] in ("Platform Admin", "Compliance Officer") else [a for a in T.AUDIT if a["user"] == user["id"]]
    return list(reversed(rows))[:limit]


@app.get("/api/metrics")
def metrics(user=Depends(current_user)):
    return T.metrics(registry.AGENTS)


@app.post("/api/policy/simulate")
def simulate(req: SimReq, user=Depends(current_user)):
    if req.user_id not in security.USERS or req.agent_id not in registry.AGENTS:
        raise HTTPException(404, "Unknown user or agent")
    u, a = security.USERS[req.user_id], registry.AGENTS[req.agent_id]
    return {"user": u["name"], "role": u["role"], "agent": a["name"], **security.evaluate(u, a, T.spent(u["id"]))}


@app.get("/api/samples")
def samples():
    return [
        {"label": "Requirement readiness (vague spec)", "intent": "Review this requirement and determine whether it is ready for development",
         "text": "The system should be fast and user-friendly. Customers shall be able to pay invoices easily via the portal. The payment service must integrate with a third-party gateway. Reports should be generated as needed. Store customer name, email and card details."},
        {"label": "Requirement readiness (well-specified)", "intent": "Review this requirement and determine whether it is ready for development",
         "text": "The portal shall return invoice search results within 2 seconds for 95% of requests with up to 500 concurrent users. When the payment gateway returns an error, the system must show an error message and retry up to 3 times. Given a valid card, when the user confirms payment, then a receipt is emailed within 30 seconds. All payment events shall be written to an audit log and data encrypted at rest. Availability shall be 99.5% monthly."},
        {"label": "Finance review (needs approval)", "intent": "Analyze budget variance and review financial exposure",
         "text": "Q3 budget was $1,200,000. Actual spend reached $1,345,000 driven by cloud and contractor costs."},
        {"label": "KYC onboarding check", "intent": "Verify customer onboarding KYC identity documents",
         "text": "Customer name: A. Sharma. Date of birth: 12 May 1985. Passport provided. Address proof pending."},
    ]

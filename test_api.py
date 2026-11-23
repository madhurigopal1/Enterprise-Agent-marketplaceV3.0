import pytest
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)
GOOD = c.get("/api/samples").json()[1]
BAD = c.get("/api/samples").json()[0]


def auth(uid):
    t = c.post("/api/login", json={"user_id": uid}).json()["token"]
    return {"Authorization": f"Bearer {t}"}


def test_requires_auth():
    assert c.get("/api/agents").status_code == 401
    assert c.get("/api/agents", headers={"Authorization": "Bearer bad.token"}).status_code == 401


def test_catalog_size_and_access_preview():
    r = c.get("/api/agents", headers=auth("priya")).json()
    assert 10 <= len(r) <= 20
    fin = next(a for a in r if a["id"] == "fin-analysis")
    assert fin["access"]["allowed"] is False  # BA cannot use finance agent


def test_discovery_by_intent():
    r = c.post("/api/discover", json={"query": "Find an agent that can analyze requirements and identify quality gaps"}, headers=auth("priya")).json()
    assert r["results"][0]["agent_id"] == "req-quality"
    r = c.post("/api/discover", json={"query": "check customer KYC onboarding"}, headers=auth("meera")).json()
    assert r["results"][0]["agent_id"] == "kyc"


def test_multi_agent_run_bad_vs_good_spec():
    h = auth("priya")
    bad = c.post("/api/runs", json={"intent": BAD["intent"], "input_text": BAD["text"]}, headers=h).json()
    good = c.post("/api/runs", json={"intent": GOOD["intent"], "input_text": GOOD["text"]}, headers=h).json()
    assert sum(s["status"] == "completed" for s in bad["steps"]) >= 3
    sc = lambda run: next(s for s in run["steps"] if s["agent_id"] == "req-quality")["output"]["score"]
    assert sc(good) > sc(bad)
    assert "Ready" in good["result"]["headline"] or "completed" in good["result"]["headline"].lower() or "refinement" in good["result"]["headline"]
    assert bad["result"]["headline"].startswith(("Not ready", "Needs refinement"))


def test_delegation_is_scoped():
    run = c.post("/api/runs", json={"intent": "is this ready for development", "input_text": GOOD["text"]}, headers=auth("priya")).json()
    for s in run["steps"]:
        if s["delegation"]:
            assert s["delegation"]["inherits_user_permissions"] is False


def test_rbac_blocks_and_audits():
    h = auth("priya")
    run = c.post("/api/runs", json={"intent": "manual", "input_text": "Budget $10", "agent_ids": ["fin-analysis", "incident-triage"]}, headers=h).json()
    assert [s["status"] for s in run["steps"]] == ["blocked", "blocked"] or all(s["status"] == "blocked" for s in run["steps"])
    audit = c.get("/api/audit", headers=h).json()
    assert any(a["decision"] == "deny" and a["agent_id"] == "fin-analysis" for a in audit)


def test_human_approval_flow():
    h = auth("arjun")
    run = c.post("/api/runs", json={"intent": "Analyze budget variance and review financial exposure", "input_text": "Budget $1,200,000 actual $1,345,000"}, headers=h).json()
    assert run["status"] == "awaiting_approval"
    done = c.post(f"/api/runs/{run['id']}/decision", json={"agent_id": "fin-analysis", "approve": True}, headers=h).json()
    fin = next(s for s in done["steps"] if s["agent_id"] == "fin-analysis")
    assert fin["status"] == "completed" and done["status"] in ("completed", "partial")


def test_rejection_flow():
    h = auth("meera")
    run = c.post("/api/runs", json={"intent": "kyc", "input_text": "Customer name X", "agent_ids": ["kyc"]}, headers=h).json()
    assert run["status"] == "awaiting_approval"
    done = c.post(f"/api/runs/{run['id']}/decision", json={"agent_id": "kyc", "approve": False}, headers=h).json()
    assert done["steps"][0]["status"] == "rejected"


def test_only_owner_or_admin_can_approve():
    run = c.post("/api/runs", json={"intent": "kyc check", "input_text": "Customer name X", "agent_ids": ["kyc"]}, headers=auth("meera")).json()
    r = c.post(f"/api/runs/{run['id']}/decision", json={"agent_id": "kyc", "approve": True}, headers=auth("priya"))
    assert r.status_code in (403, 404)


def test_registration_and_lifecycle_gate():
    body = {"id": "poc-new-agent", "name": "New Agent", "provider": "Otari", "description": "Does new things", "owner": "Team X",
            "capabilities": ["new things"], "keywords": ["newthing"]}
    assert c.post("/api/agents", json=body, headers=auth("priya")).status_code == 403
    assert c.post("/api/agents", json=body, headers=auth("kiran")).status_code == 201
    assert c.post("/api/agents", json=body, headers=auth("kiran")).status_code == 422  # duplicate
    # not yet certified -> blocked
    run = c.post("/api/runs", json={"intent": "manual", "input_text": "hi", "agent_ids": ["poc-new-agent"]}, headers=auth("kiran")).json()
    assert run["steps"][0]["status"] == "blocked"
    adm = auth("sam")
    assert c.post("/api/agents/poc-new-agent/lifecycle", json={"target": "Production"}, headers=adm).status_code == 409  # skip not allowed
    for t in ("Validated", "Certified", "Production"):
        assert c.post("/api/agents/poc-new-agent/lifecycle", json={"target": t}, headers=adm).status_code == 200
    run = c.post("/api/runs", json={"intent": "manual", "input_text": "hi", "agent_ids": ["poc-new-agent"]}, headers=auth("kiran")).json()
    assert run["steps"][0]["status"] == "completed"


def test_policy_simulation_region_abac():
    r = c.post("/api/policy/simulate", json={"user_id": "meera", "agent_id": "payment-analysis"}, headers=auth("sam")).json()
    assert r["allowed"] is False
    assert any(x["name"] == "ABAC region" and not x["passed"] for x in r["checks"])


def test_budget_quota():
    from app import telemetry as T
    T.SPENT["kiran"] = 2.99
    run = c.post("/api/runs", json={"intent": "docs", "input_text": "doc", "agent_ids": ["doc-gen"]}, headers=auth("kiran")).json()
    assert run["steps"][0]["status"] == "blocked" and "Budget" in run["steps"][0]["note"]
    T.SPENT["kiran"] = 0


def test_metrics_kpis():
    m = c.get("/api/metrics", headers=auth("sam")).json()
    names = {k["name"]: k for k in m["kpis"]}
    assert names["Agents onboarded"]["met"] and names["Providers / frameworks"]["met"]
    assert m["totals"]["invocation_attempts"] == len([a for a in c.get("/api/audit?limit=1000", headers=auth("sam")).json() if a["action"] == "invoke"])

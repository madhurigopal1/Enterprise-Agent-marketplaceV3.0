"""Regression tests for the Human Approvals experience (v1.0)."""
from fastapi.testclient import TestClient
from app.main import app, APP_VERSION
from app import registry

c = TestClient(app)


def auth(uid):
    return {"Authorization": f"Bearer {c.post('/api/login', json={'user_id': uid}).json()['token']}"}


def test_ui_serves_approvals_tab_with_version_and_no_cache():
    r = c.get("/")
    assert r.status_code == 200
    assert 'data-tab="approvals"' in r.text and "Human approvals" in r.text
    assert 'data-tab="register"' in r.text and 'id="simBtn"' in r.text   # register + policy simulator restored
    assert "__APP_VERSION__" not in r.text and f"app.js?v={APP_VERSION}" in r.text
    assert "no-store" in r.headers["cache-control"]
    js = c.get(f"/static/app.js?v={APP_VERSION}")
    assert js.status_code == 200 and "loadApprovals" in js.text and "no-store" in js.headers["cache-control"]


def test_version_and_ready_report_approvals_ui():
    v = c.get("/api/version").json()
    assert v["version"] == APP_VERSION and v["ui_has_approvals_tab"] is True
    r = c.get("/api/ready")
    assert r.status_code == 200 and r.json()["checks"]["approvals_ui"] is True
    assert r.headers["x-app-version"] == APP_VERSION and r.headers["x-content-type-options"] == "nosniff"


def test_kyc_run_appears_in_meera_inbox_and_she_can_approve():
    h = auth("meera")
    run = c.post("/api/runs", json={"intent": "Verify customer onboarding KYC identity documents",
                                    "input_text": "Customer name: A. Sharma. Passport provided.", "agent_ids": ["kyc"]}, headers=h).json()
    assert run["status"] == "awaiting_approval"
    inbox = c.get("/api/approvals", headers=h).json()
    item = next(x for x in inbox if x["run_id"] == run["id"])
    assert item["agent_name"] == "KYC Verification Agent" and item["requested_by"] == "Meera Collins"
    done = c.post(f"/api/runs/{run['id']}/decision", json={"agent_id": "kyc", "approve": True}, headers=h).json()
    assert done["steps"][0]["status"] == "completed"
    assert not any(x["run_id"] == run["id"] for x in c.get("/api/approvals", headers=h).json())


def test_compliance_officer_can_approve_someone_elses_finance_run():
    run = c.post("/api/runs", json={"intent": "finance", "input_text": "Budget $100 actual $130",
                                    "agent_ids": ["fin-analysis"]}, headers=auth("arjun")).json()
    assert run["status"] == "awaiting_approval"
    assert any(x["run_id"] == run["id"] for x in c.get("/api/approvals", headers=auth("meera")).json())
    r = c.post(f"/api/runs/{run['id']}/decision", json={"agent_id": "fin-analysis", "approve": True}, headers=auth("meera"))
    assert r.status_code == 200 and r.json()["steps"][0]["status"] == "completed"


def test_business_analyst_sees_no_one_elses_approvals_and_cannot_decide():
    run = c.post("/api/runs", json={"intent": "finance", "input_text": "Budget",
                                    "agent_ids": ["fin-analysis"]}, headers=auth("arjun")).json()
    assert not any(x["run_id"] == run["id"] for x in c.get("/api/approvals", headers=auth("priya")).json())
    r = c.post(f"/api/runs/{run['id']}/decision", json={"agent_id": "fin-analysis", "approve": True}, headers=auth("priya"))
    assert r.status_code == 403


def test_rejected_step_never_executes_and_is_audited():
    h = auth("arjun")
    run = c.post("/api/runs", json={"intent": "finance", "input_text": "x", "agent_ids": ["fin-analysis"]}, headers=h).json()
    done = c.post(f"/api/runs/{run['id']}/decision", json={"agent_id": "fin-analysis", "approve": False}, headers=h).json()
    assert done["steps"][0]["status"] == "rejected" and done["steps"][0]["output"] is None
    audit = c.get("/api/audit?limit=1000", headers=auth("sam")).json()
    assert any(a["action"] == "approval" and a.get("run_id") == run["id"] and a["decision"] == "reject" for a in audit)


def test_double_decision_is_rejected():
    h = auth("arjun")
    run = c.post("/api/runs", json={"intent": "finance", "input_text": "x", "agent_ids": ["fin-analysis"]}, headers=h).json()
    assert c.post(f"/api/runs/{run['id']}/decision", json={"agent_id": "fin-analysis", "approve": True}, headers=h).status_code == 200
    assert c.post(f"/api/runs/{run['id']}/decision", json={"agent_id": "fin-analysis", "approve": True}, headers=h).status_code == 409


def test_unknown_and_too_many_agents_rejected():
    h = auth("sam")
    assert c.post("/api/runs", json={"intent": "manual", "agent_ids": ["nope"]}, headers=h).status_code == 422
    assert c.post("/api/runs", json={"intent": "manual", "agent_ids": list(registry.AGENTS)[:7]}, headers=h).status_code == 422


def test_approvals_requires_auth():
    assert c.get("/api/approvals").status_code == 401

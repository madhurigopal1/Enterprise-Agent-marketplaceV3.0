"""v1.1 feature tests: decision comments, bulk approvals, feedback, kill switch, report, audit export."""
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)


def auth(uid):
    return {"Authorization": f"Bearer {c.post('/api/login', json={'user_id': uid}).json()['token']}"}


def fin_run(uid="arjun"):
    return c.post("/api/runs", json={"intent": "finance", "input_text": "Budget $100 actual $130", "agent_ids": ["fin-analysis"]}, headers=auth(uid)).json()


def test_reject_requires_reason_and_comment_is_recorded():
    run, h = fin_run(), auth("arjun")
    import app.main as M
    M.REQUIRE_REJECT_REASON = True
    try:
        assert c.post(f"/api/runs/{run['id']}/decision", json={"agent_id": "fin-analysis", "approve": False}, headers=h).status_code == 422
    finally:
        M.REQUIRE_REJECT_REASON = False
    d = c.post(f"/api/runs/{run['id']}/decision", json={"agent_id": "fin-analysis", "approve": False, "comment": "Figures not reconciled"}, headers=h).json()
    st = d["steps"][0]
    assert st["status"] == "rejected" and st["approval"]["comment"] == "Figures not reconciled" and "Figures not reconciled" in st["note"]
    audit = c.get("/api/audit?limit=1000", headers=auth("sam")).json()
    assert any(a["action"] == "approval" and a.get("run_id") == run["id"] and a["reason"] == "Figures not reconciled" for a in audit)


def test_bulk_approve_partial_success():
    r1, r2 = fin_run(), fin_run()
    items = [{"run_id": r1["id"], "agent_id": "fin-analysis"}, {"run_id": r2["id"], "agent_id": "fin-analysis"},
             {"run_id": "run-missing", "agent_id": "fin-analysis"}]
    d = c.post("/api/approvals/bulk", json={"items": items, "approve": True}, headers=auth("meera")).json()
    assert d["decided"] == 2 and d["results"][2]["ok"] is False


def test_bulk_respects_permissions():
    r = fin_run()
    d = c.post("/api/approvals/bulk", json={"items": [{"run_id": r["id"], "agent_id": "fin-analysis"}], "approve": True}, headers=auth("priya")).json()
    assert d["decided"] == 0 and "Only the requester" in d["results"][0]["error"]


def test_feedback_only_for_completed_steps_and_aggregates():
    h = auth("priya")
    run = c.post("/api/runs", json={"intent": "docs", "input_text": "doc", "agent_ids": ["doc-gen"]}, headers=h).json()
    assert c.post(f"/api/runs/{run['id']}/feedback", json={"agent_id": "doc-gen", "rating": 4}, headers=h).status_code == 201
    assert c.post(f"/api/runs/{run['id']}/feedback", json={"agent_id": "doc-gen", "rating": 5}, headers=h).status_code == 201  # upsert
    assert c.post(f"/api/runs/{run['id']}/feedback", json={"agent_id": "kyc", "rating": 5}, headers=h).status_code == 409
    assert c.post(f"/api/runs/{run['id']}/feedback", json={"agent_id": "doc-gen", "rating": 9}, headers=h).status_code == 422
    assert c.post(f"/api/runs/{run['id']}/feedback", json={"agent_id": "doc-gen", "rating": 3}, headers=auth("kiran")).status_code == 404
    fb = c.get("/api/agents/doc-gen/feedback", headers=h).json()
    assert fb["count"] >= 1 and any(i["run_id"] == run["id"] and i["rating"] == 5 for i in fb["items"])


def test_kill_switch_blocks_and_resumes():
    assert c.post("/api/agents/doc-gen/suspend", json={"suspended": True}, headers=auth("kiran")).status_code == 403
    adm = auth("sam")
    assert c.post("/api/agents/doc-gen/suspend", json={"suspended": True, "reason": "Incident 42"}, headers=adm).json()["suspended"] is True
    run = c.post("/api/runs", json={"intent": "docs", "input_text": "doc", "agent_ids": ["doc-gen"]}, headers=auth("priya")).json()
    assert run["steps"][0]["status"] == "blocked" and "Kill switch" in run["steps"][0]["note"] and "Incident 42" in run["steps"][0]["note"]
    c.post("/api/agents/doc-gen/suspend", json={"suspended": False}, headers=adm)
    run = c.post("/api/runs", json={"intent": "docs", "input_text": "doc", "agent_ids": ["doc-gen"]}, headers=auth("priya")).json()
    assert run["steps"][0]["status"] == "completed"


def test_run_report_markdown():
    h = auth("arjun"); run = fin_run()
    c.post(f"/api/runs/{run['id']}/decision", json={"agent_id": "fin-analysis", "approve": True, "comment": "OK for Q3"}, headers=h)
    r = c.get(f"/api/runs/{run['id']}/report", headers=h)
    assert r.status_code == 200 and f"# Agent run report {run['id']}" in r.text and "approved by Arjun Mehta" in r.text and "OK for Q3" in r.text
    assert c.get(f"/api/runs/{run['id']}/report", headers=auth("priya")).status_code == 404


def test_audit_csv_export_rbac():
    assert c.get("/api/audit/export", headers=auth("priya")).status_code == 403
    r = c.get("/api/audit/export", headers=auth("meera"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0].startswith("ts,id,action") and "attachment" in r.headers["content-disposition"]


def test_ui_has_v11_controls():
    html = c.get("/").text
    for marker in ('data-tab="runs"', 'id="bulkApprove"', 'id="auditExport"', "1.1.0-features"):
        assert marker in html

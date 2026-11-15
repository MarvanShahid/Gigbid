"""API end to end (in-process runs): sign in -> scout -> analyse -> approve -> pipeline -> analytics -> memory."""
import os
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.integration.test_bid_graph import load, pick


@pytest.fixture()
def client(sim, tmp_path, monkeypatch):
    monkeypatch.setenv("GIGBID_INLINE_RUNS", "1")
    monkeypatch.setenv("CHECKPOINT_DB", str(tmp_path / "cp.db"))
    from apps.api import db
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    db.reset_engine()
    from apps.api.main import app
    with TestClient(app) as c:
        yield c
    db.reset_engine()
    os.environ.pop("DATABASE_URL", None)


def wait_for(c, h, job_id, statuses, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = c.get(f"/api/jobs/{job_id}", headers=h)
        if r.status_code == 200 and r.json()["status"] in statuses:
            return r.json()
        time.sleep(0.3)
    raise AssertionError(f"{job_id} never reached {statuses}: {r.json() if r.status_code == 200 else r.text}")


def test_full_flow(client, sim):
    c = client
    tok = c.post("/api/auth/login", json={"email": "reviewer@gigbid.dev", "password": "reviewer-pass-0800"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert c.get("/api/auth/me", headers=h).json()["settings"]["persona"] == "ml_engineer"
    assert c.get("/api/status").json()["marketplace_available"]
    job = pick(bid=True, scam=False, injected=False)
    scam = pick(scam=True)
    load(sim, [job, scam])
    c.post(f"/api/jobs/{job['id']}/analyse", headers=h)
    c.post(f"/api/jobs/{scam['id']}/analyse", headers=h)
    d = wait_for(c, h, job["id"], {"awaiting_approval"})
    assert d["approval_id"] and d["summary"]["fit"]["matrix"]
    s = wait_for(c, h, scam["id"], {"skipped"})
    assert s["summary"]["risk"]["is_scam"]
    # inbox is ranked: the job waiting for approval comes first
    assert c.get("/api/jobs", headers=h).json()[0]["job_id"] == job["id"]
    ap = c.get(f"/api/approvals/{d['approval_id']}", headers=h).json()
    assert ap["payload"]["preview"]["connects_cost"] > 0
    r = c.post(f"/api/approvals/{d['approval_id']}/decision", headers=h, json={"action": "approve"})
    assert r.status_code == 200
    again = c.post(f"/api/approvals/{d['approval_id']}/decision", headers=h, json={"action": "approve"})
    assert again.status_code == 409            # a double click cannot resume twice
    wait_for(c, h, job["id"], {"submitted"})
    board = c.get("/api/pipeline", headers=h).json()
    assert any(x["job_id"] == job["id"] and x["stage"] == "submitted" for x in board["cards"])
    sync = c.post("/api/pipeline/sync", headers=h).json()
    assert "moved" in sync
    runs = c.get("/api/runs", headers=h, params={"subject": job["id"]}).json()
    assert runs and any(e["node"] == "decide" for r in runs for e in r["events"])
    tr = c.get(f"/api/runs/traces/{runs[-1]['trace_id']}", headers=h).json()
    assert tr["spans"], "every run is traced"
    an = c.get("/api/analytics", headers=h).json()
    assert an["totals"]["proposals_sent"] == 1 and an["totals"]["scams_caught"] >= 1
    assert "style" in c.get("/api/memory", headers=h).json()
    props = httpx.get(f"{sim}/proposals", headers={"Authorization": "Bearer gigsim-dev-reviewer"}).json()["proposals"]
    assert len([p for p in props if p["job_id"] == job["id"]]) == 1


def test_auth_required_and_tenant_scoped(client, sim):
    c = client
    assert c.get("/api/jobs").status_code == 401
    t1 = c.post("/api/auth/register", json={"email": "a@x.dev", "password": "password-a"}).json()["token"]
    t2 = c.post("/api/auth/register", json={"email": "b@x.dev", "password": "password-b"}).json()["token"]
    job = pick(bid=True, scam=False, injected=False)
    load(sim, [job])
    c.post(f"/api/jobs/{job['id']}/analyse", headers={"Authorization": f"Bearer {t1}"})
    assert c.get(f"/api/jobs/{job['id']}", headers={"Authorization": f"Bearer {t2}"}).status_code == 404

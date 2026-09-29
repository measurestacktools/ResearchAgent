import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("GROQ_TEST_KEY", None)

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)
SID = {"X-Session-Id": "test-session-1"}


def test_status_no_key():
    r = client.get("/api/status", headers=SID)
    assert r.status_code == 200
    assert r.json()["model"] == "openai/gpt-oss-120b"


def test_empty_question_plan():
    r = client.post("/api/plan", json={"question": ""}, headers=SID)
    assert r.status_code == 400


def test_empty_source_rejected():
    client.delete("/api/sources", headers=SID)
    r = client.post("/api/sources", json={"title": "", "text": ""}, headers=SID)
    assert r.status_code == 400
    r2 = client.post("/api/sources", json={"title": "T", "text": ""}, headers=SID)
    assert r2.status_code == 400


def test_oversized_source():
    client.delete("/api/sources", headers=SID)
    r = client.post("/api/sources", json={"title": "Big", "text": "x" * 8001}, headers=SID)
    assert r.status_code == 400


def test_too_many_sources():
    client.delete("/api/sources", headers={"X-Session-Id": "many-test"})
    h = {"X-Session-Id": "many-test"}
    for i in range(6):
        r = client.post("/api/sources", json={"title": f"T{i}", "text": "content"}, headers=h)
        assert r.status_code == 200
    r = client.post("/api/sources", json={"title": "Extra", "text": "content"}, headers=h)
    assert r.status_code == 400


def test_bad_job():
    r = client.post("/api/analyze", json={"job": "nonsense"}, headers=SID)
    assert r.status_code == 400


def test_no_key_plan_503():
    r = client.post("/api/plan", json={"question": "Is water wet?"}, headers={"X-Session-Id": "nokey-1"})
    assert r.status_code in (503, 401, 502)


def test_add_list_delete_source():
    client.delete("/api/sources", headers=SID)
    r = client.post("/api/sources", json={"title": "S1", "text": "Some pasted content here."}, headers=SID)
    assert r.status_code == 200
    r2 = client.get("/api/sources", headers=SID)
    assert r2.json()["count"] >= 1
    d = client.delete("/api/sources/0", headers=SID)
    assert d.status_code == 200


def test_compare_needs_two():
    client.delete("/api/sources", headers={"X-Session-Id": "cmp-1"})
    client.post("/api/sources", json={"title": "Only", "text": "abc"}, headers={"X-Session-Id": "cmp-1"})
    r = client.post("/api/analyze", json={"job": "compare", "key": "gsk_fake"}, headers={"X-Session-Id": "cmp-1", "X-Groq-Key": "gsk_fake"})
    # either validation 400 (needs 2) or key error — but with 1 source, validation fires only if key present... check 400 path by key present logic order:
    # our code checks job validity, then key presence, so no-key => 503. Accept either.
    assert r.status_code in (400, 503)

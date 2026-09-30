import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("GROQ_TEST_KEY", None)

from fastapi.testclient import TestClient
import app as app_module
from app import app

client = TestClient(app)
SID = {"X-Session-Id": "test-session-1"}


def _clear_key():
    app_module._session_key = None
    os.environ.pop("GROQ_API_KEY", None)
    os.environ.pop("GROQ_TEST_KEY", None)


def test_status_no_key():
    _clear_key()
    r = client.get("/api/status", headers=SID)
    assert r.status_code == 200
    j = r.json()
    assert j["model"] == "openai/gpt-oss-120b"
    assert j["has_key"] is False
    assert j["key_source"] == "none"


def test_empty_question_plan():
    _clear_key()
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
    _clear_key()
    r = client.post("/api/analyze", json={"job": "nonsense"}, headers=SID)
    assert r.status_code == 400


def test_no_key_plan_401():
    _clear_key()
    r = client.post("/api/plan", json={"question": "Is water wet?"}, headers={"X-Session-Id": "nokey-1"})
    assert r.status_code == 401


def test_no_key_analyze_401():
    _clear_key()
    r = client.post("/api/analyze", json={"job": "findings"}, headers={"X-Session-Id": "nokey-2"})
    assert r.status_code == 401


def test_client_key_ignored():
    _clear_key()
    r = client.post("/api/plan", json={"question": "Is water wet?", "key": "gsk_fake"}, headers={"X-Session-Id": "nokey-3", "X-Groq-Key": "gsk_fake"})
    assert r.status_code == 401
    r2 = client.post("/api/analyze", json={"job": "findings", "key": "gsk_fake"}, headers={"X-Session-Id": "nokey-3", "X-Groq-Key": "gsk_fake"})
    assert r2.status_code == 401


def test_key_empty_400():
    _clear_key()
    r = client.post("/api/key", json={"key": ""})
    assert r.status_code == 400
    r2 = client.post("/api/key", json={"key": "   "})
    assert r2.status_code == 400


def test_key_fake_401_not_saved():
    _clear_key()
    r = client.post("/api/key", json={"key": "gsk_fake_invalid_key_123"})
    assert r.status_code == 401
    assert app_module._session_key is None
    s = client.get("/api/status", headers=SID)
    assert s.json()["has_key"] is False
    assert s.json()["key_source"] == "none"


def test_key_delete_200():
    _clear_key()
    r = client.delete("/api/key")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    s = client.get("/api/status", headers=SID)
    assert s.json()["has_key"] is False


def test_add_list_delete_source():
    client.delete("/api/sources", headers=SID)
    r = client.post("/api/sources", json={"title": "S1", "text": "Some pasted content here."}, headers=SID)
    assert r.status_code == 200
    r2 = client.get("/api/sources", headers=SID)
    assert r2.json()["count"] >= 1
    d = client.delete("/api/sources/0", headers=SID)
    assert d.status_code == 200


def test_compare_needs_two_no_key_401():
    _clear_key()
    client.delete("/api/sources", headers={"X-Session-Id": "cmp-1"})
    client.post("/api/sources", json={"title": "Only", "text": "abc"}, headers={"X-Session-Id": "cmp-1"})
    # Client-supplied keys are ignored, so even with fake keys this is 401 (no server key).
    r = client.post("/api/analyze", json={"job": "compare", "key": "gsk_fake"}, headers={"X-Session-Id": "cmp-1", "X-Groq-Key": "gsk_fake"})
    assert r.status_code == 401

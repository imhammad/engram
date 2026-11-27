"""End-to-end API tests in fake-model mode, with the network cut off.

Every test here runs with socket connections to anything other than the
loopback interface made to fail, so a library that tried to phone home
(model downloads, telemetry) would break the test rather than pass silently.
"""

import importlib
import ipaddress
import socket
import sys

import pytest

TOKEN = "t" * 64
ALLOWED_ORIGIN = "tauri://localhost"
EVIL_ORIGIN = "https://evil.example"

ENGINE_MODULES = ["main", "db", "vector_store", "ocr_capture", "audio_capture", "paths", "fake_models"]


class NetworkAccessAttempted(AssertionError):
    pass


def _is_loopback(address) -> bool:
    if isinstance(address, (str, bytes)) and not isinstance(address, tuple):
        return True  # AF_UNIX socket path
    host = address[0]
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture
def no_network(monkeypatch):
    attempts = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address):
        if not _is_loopback(address):
            attempts.append(address)
            raise NetworkAccessAttempted(f"blocked connection to {address!r}")
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        if not _is_loopback(address):
            attempts.append(address)
            raise NetworkAccessAttempted(f"blocked connection to {address!r}")
        return real_connect_ex(self, address)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host not in (None, "localhost", "127.0.0.1", "::1", "testserver"):
            attempts.append(host)
            raise NetworkAccessAttempted(f"blocked DNS lookup of {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    yield attempts
    assert attempts == [], f"engine attempted network access: {attempts}"


@pytest.fixture
def engine(tmp_path, monkeypatch, no_network):
    monkeypatch.setenv("ENGRAM_FAKE_MODELS", "1")
    monkeypatch.setenv("ENGRAM_TOKEN", TOKEN)
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ENGRAM_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.delenv("ENGRAM_DEV_ORIGIN", raising=False)
    for name in ENGINE_MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    client.headers.update({"X-Engram-Token": TOKEN})
    yield main, client
    client.close()
    for name in ENGINE_MODULES:
        sys.modules.pop(name, None)


# --- authentication and CORS ----------------------------------------------

def test_missing_token_is_rejected(engine):
    _, client = engine
    for method, path in [("get", "/health"), ("get", "/memories"), ("post", "/memories"), ("get", "/export")]:
        resp = client.request(method, path, headers={"X-Engram-Token": ""})
        assert resp.status_code == 401, path


def test_wrong_token_is_rejected(engine):
    _, client = engine
    resp = client.get("/memories", headers={"X-Engram-Token": "x" * 64})
    assert resp.status_code == 401


def test_right_token_is_accepted(engine):
    _, client = engine
    assert client.get("/health").json() == {"status": "ok"}


def test_preflight_from_app_origin_is_allowed(engine):
    _, client = engine
    resp = client.options("/memories", headers={
        "Origin": ALLOWED_ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-engram-token,content-type",
    })
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_preflight_from_other_origin_gets_no_cors_approval(engine):
    _, client = engine
    resp = client.options("/memories", headers={
        "Origin": EVIL_ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-engram-token",
    })
    assert resp.headers.get("access-control-allow-origin") != EVIL_ORIGIN
    simple = client.get("/health", headers={"Origin": EVIL_ORIGIN})
    assert "access-control-allow-origin" not in simple.headers


def test_engine_refuses_to_start_without_token(monkeypatch, tmp_path):
    monkeypatch.setenv("ENGRAM_FAKE_MODELS", "1")
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ENGRAM_TOKEN", raising=False)
    for name in ENGINE_MODULES:
        sys.modules.pop(name, None)
    with pytest.raises(SystemExit):
        importlib.import_module("main")
    for name in ENGINE_MODULES:
        sys.modules.pop(name, None)


# --- full flows with the network cut off ------------------------------------

def test_save_search_export_delete_flow(engine):
    _, client = engine
    note = client.post("/memories", json={"content": "Ship the offline search feature before onboarding work"}).json()
    other = client.post("/memories", json={"content": "Buy oat milk and coffee beans"}).json()
    assert note["memory"]["source"] == "manual"

    results = client.get("/search", params={"q": "offline search feature"}).json()
    assert results[0]["id"] == note["memory"]["id"]

    exported = client.get("/export").json()
    assert {m["id"] for m in exported["memories"]} == {note["memory"]["id"], other["memory"]["id"]}
    assert "capture_log" in exported

    assert client.delete(f"/memories/{other['memory']['id']}").json() == {"deleted": True}
    assert client.delete("/memories").json()["deleted_count"] == 1
    assert client.get("/memories").json() == []


def test_screen_capture_is_redacted_and_logged(engine, monkeypatch):
    _, client = engine
    monkeypatch.setenv(
        "ENGRAM_FAKE_OCR_TEXT",
        "Project kickoff notes for the research integrity agent\n"
        "Send the draft schedule to jane.doe@example.com before Friday afternoon",
    )
    resp = client.post("/capture/screen", json={
        "app_name": "Google Chrome", "window_title": "Inbox - jane.doe@example.com", "trigger": "auto",
    }).json()
    assert resp["saved"] is True
    assert "[email]" in resp["memory"]["content"]
    assert "jane.doe" not in resp["memory"]["content"]

    entry = client.get("/ledger").json()[0]
    assert entry["outcome"] == "saved"
    assert entry["trigger"] == "auto"
    assert entry["window_title"] == "Inbox - [email]"
    assert entry["memory_id"] == resp["memory"]["id"]


def test_noisy_capture_is_dropped_not_saved(engine, monkeypatch):
    _, client = engine
    monkeypatch.setenv("ENGRAM_FAKE_OCR_TEXT", "@ © ® 8 Bie O's AIM & x + +> eaiA 2? BO")
    resp = client.post("/capture/screen", json={"app_name": "Google Chrome"}).json()
    assert resp["saved"] is False
    assert client.get("/memories").json() == []
    assert client.get("/ledger").json()[0]["outcome"] == "dropped-noise"


def test_excluded_window_is_never_captured(engine):
    _, client = engine
    resp = client.post("/capture/screen", json={"app_name": "Terminal", "window_title": "zsh — secrets"}).json()
    assert resp["saved"] is False
    entry = client.get("/ledger").json()[0]
    assert entry["outcome"] == "excluded"
    assert entry["window_title"] == "[excluded]"
    assert client.get("/memories").json() == []


def test_private_window_activity_keeps_only_app_name(engine):
    _, client = engine
    resp = client.post("/activity", json={"app_name": "Google Chrome", "window_title": "Bank - Google Chrome (Incognito)"}).json()
    assert resp["excluded"] is True
    assert client.get("/activity").json()[0]["window_title"] == "[excluded]"


def test_activity_titles_are_redacted(engine):
    _, client = engine
    client.post("/activity", json={"app_name": "Mail", "window_title": "From jane.doe@example.com"})
    assert client.get("/activity").json()[0]["window_title"] == "From [email]"


def test_user_exclusion_rules(engine):
    _, client = engine
    rule = client.post("/exclusions/rules", json={"kind": "title", "pattern": "Payroll"}).json()
    assert client.get("/exclusions").json()["rules"][0]["id"] == rule["id"]
    resp = client.post("/capture/screen", json={"app_name": "Numbers", "window_title": "Payroll 2026.numbers"}).json()
    assert resp["saved"] is False
    assert client.delete(f"/exclusions/rules/{rule['id']}").json() == {"deleted": True}
    bad = client.post("/exclusions/rules", json={"kind": "regex", "pattern": ".*"})
    assert bad.status_code == 422


def test_audio_capture_flow(engine):
    _, client = engine
    resp = client.post("/capture/audio").json()
    assert resp["saved"] is True
    assert resp["memory"]["source"] == "audio_transcription"


def test_ledger_delete_and_clear(engine):
    _, client = engine
    client.post("/ledger", json={"app_name": "1Password", "reason": "built-in exclusion"})
    client.post("/ledger", json={"app_name": "Terminal", "reason": "built-in exclusion"})
    entries = client.get("/ledger").json()
    assert len(entries) == 2
    assert client.delete(f"/ledger/{entries[0]['id']}").json() == {"deleted": True}
    assert client.delete("/ledger").json() == {"deleted_count": 1}


def test_noisy_memories_are_not_offered_as_connections(engine, monkeypatch):
    main, client = engine
    junk = main.insert_memory("search feature @ © 8 Bie O's x + eaiA", source="screen_ocr")
    main.add_to_vector_store(junk["id"], junk["content"])
    resp = client.post("/memories", json={"content": "search feature"}).json()
    assert resp["related_memory"] is None


def test_network_guard_itself_blocks_outside_addresses(monkeypatch):
    """Make sure the guard used above would really catch an outbound call."""
    guard = no_network.__wrapped__(monkeypatch)
    attempts = next(guard)
    with pytest.raises(NetworkAccessAttempted):
        socket.create_connection(("93.184.216.34", 443), timeout=1)
    with pytest.raises(NetworkAccessAttempted):
        socket.getaddrinfo("huggingface.co", 443)
    assert len(attempts) == 2
    attempts.clear()
    with pytest.raises(StopIteration):
        next(guard)

"""Tests for FastAPI server — REST endpoints, health, auth, WebSocket."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

# Patch config before importing server to avoid real LLM calls
import config as cfg
cfg.MAX_MEMORY_TOKENS = 1000
cfg.MAX_HISTORY_TOKENS = 10000
cfg.MAX_TOOL_TURNS = 10
cfg.COMPACT_KEEP_FIRST = 2
cfg.COMPACT_KEEP_LAST = 4
cfg.CHIKA_API_KEY = ""

from fastapi.testclient import TestClient
from api.server import app


client = TestClient(app)


# ── /health ───────────────────────────────────────────────────────────────────

def test_health_returns_200():
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_returns_ok_status():
    resp = client.get("/health")
    data = resp.json()
    assert data["status"] == "ok"


def test_health_includes_provider():
    resp = client.get("/health")
    data = resp.json()
    assert "provider" in data


def test_health_includes_model():
    resp = client.get("/health")
    data = resp.json()
    assert "model" in data


def test_health_no_auth_required():
    # Health should be accessible without any Authorization header
    resp = client.get("/health")
    assert resp.status_code == 200


# ── /api/sessions ─────────────────────────────────────────────────────────────

def test_list_sessions_returns_200():
    resp = client.get("/api/sessions")
    assert resp.status_code == 200


def test_list_sessions_returns_list():
    resp = client.get("/api/sessions")
    data = resp.json()
    assert "sessions" in data
    assert isinstance(data["sessions"], list)


# ── /api/tools ────────────────────────────────────────────────────────────────

def test_get_tools_returns_200():
    resp = client.get("/api/tools")
    assert resp.status_code == 200


def test_get_tools_returns_tools_list():
    resp = client.get("/api/tools")
    data = resp.json()
    assert "tools" in data
    assert isinstance(data["tools"], list)


def test_get_tools_includes_count():
    resp = client.get("/api/tools")
    data = resp.json()
    assert "count" in data
    assert data["count"] == len(data["tools"])


def test_get_tools_has_name_and_description():
    resp = client.get("/api/tools")
    tools = resp.json()["tools"]
    for t in tools:
        assert "name" in t
        assert "description" in t


def test_get_tools_includes_shell_exec():
    resp = client.get("/api/tools")
    names = [t["name"] for t in resp.json()["tools"]]
    assert "shell_exec" in names


# ── /api/skills ───────────────────────────────────────────────────────────────

def test_get_skills_returns_200():
    resp = client.get("/api/skills")
    assert resp.status_code == 200


def test_get_skills_returns_list():
    resp = client.get("/api/skills")
    data = resp.json()
    assert "skills" in data
    assert isinstance(data["skills"], list)


def test_get_skills_includes_git_skill():
    resp = client.get("/api/skills")
    names = [s["name"] for s in resp.json()["skills"]]
    assert "git" in names


def test_get_skills_includes_web_skill():
    resp = client.get("/api/skills")
    names = [s["name"] for s in resp.json()["skills"]]
    assert "web" in names


# ── /api/workflows ─────────────────────────────────────────────────────────────

def test_get_workflows_returns_200():
    resp = client.get("/api/workflows")
    assert resp.status_code == 200


def test_get_workflows_returns_list():
    resp = client.get("/api/workflows")
    data = resp.json()
    assert "workflows" in data
    assert isinstance(data["workflows"], list)


# ── /api/config ───────────────────────────────────────────────────────────────

def test_get_config_returns_200():
    resp = client.get("/api/config")
    assert resp.status_code == 200


def test_get_config_includes_provider():
    resp = client.get("/api/config")
    data = resp.json()
    assert "provider" in data


def test_get_config_includes_auth_enabled():
    resp = client.get("/api/config")
    data = resp.json()
    assert "auth_enabled" in data
    assert data["auth_enabled"] is False  # CHIKA_API_KEY is ""


# ── /api/session/{id}/variables ───────────────────────────────────────────────

def test_get_session_variables_404_if_not_found():
    resp = client.get("/api/session/nonexistent_session_xyz/variables")
    assert resp.status_code == 404


def test_get_session_variables_200_after_creation():
    from api.session_manager import session_manager
    session_manager.get_or_create("test_vars_session")
    resp = client.get("/api/session/test_vars_session/variables")
    assert resp.status_code == 200
    assert "variables" in resp.json()


# ── /api/session/{id}/memory ──────────────────────────────────────────────────

def test_get_session_memory_404_if_not_found():
    resp = client.get("/api/session/nonexistent_xyz_mem/memory")
    assert resp.status_code == 404


def test_get_session_memory_200_after_creation():
    from api.session_manager import session_manager
    session_manager.get_or_create("test_mem_session")
    resp = client.get("/api/session/test_mem_session/memory")
    assert resp.status_code == 200
    assert "memory" in resp.json()


# ── /api/session/{id}/history ────────────────────────────────────────────────

def test_get_session_history_404_if_not_found():
    resp = client.get("/api/session/nonexistent_xyz_hist/history")
    assert resp.status_code == 404


def test_get_session_history_200_after_creation():
    from api.session_manager import session_manager
    session_manager.get_or_create("test_hist_session")
    resp = client.get("/api/session/test_hist_session/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "history" in data
    assert "count" in data


# ── DELETE /api/session/{id} ──────────────────────────────────────────────────

def test_delete_session_returns_200():
    from api.session_manager import session_manager
    session_manager.get_or_create("del_session")
    resp = client.delete("/api/session/del_session")
    assert resp.status_code == 200


def test_delete_session_response_includes_deleted_id():
    from api.session_manager import session_manager
    session_manager.get_or_create("del_session_2")
    resp = client.delete("/api/session/del_session_2")
    assert resp.json()["deleted"] == "del_session_2"


# ── POST /api/session/{id}/reset ─────────────────────────────────────────────

def test_reset_session_returns_200():
    from api.session_manager import session_manager
    session_manager.get_or_create("reset_session")
    resp = client.post("/api/session/reset_session/reset")
    assert resp.status_code == 200


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_auth_disabled_when_api_key_not_set():
    original = cfg.CHIKA_API_KEY
    try:
        cfg.CHIKA_API_KEY = ""
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
    finally:
        cfg.CHIKA_API_KEY = original


def test_auth_enabled_rejects_missing_key():
    original = cfg.CHIKA_API_KEY
    try:
        cfg.CHIKA_API_KEY = "secret123"
        resp = client.get("/api/sessions")
        assert resp.status_code == 401
    finally:
        cfg.CHIKA_API_KEY = original


def test_auth_enabled_accepts_valid_key():
    original = cfg.CHIKA_API_KEY
    try:
        cfg.CHIKA_API_KEY = "secret123"
        resp = client.get("/api/sessions", headers={"Authorization": "Bearer secret123"})
        assert resp.status_code == 200
    finally:
        cfg.CHIKA_API_KEY = original


def test_auth_rejects_wrong_key():
    original = cfg.CHIKA_API_KEY
    try:
        cfg.CHIKA_API_KEY = "correct_key"
        resp = client.get("/api/sessions", headers={"Authorization": "Bearer wrong_key"})
        assert resp.status_code == 401
    finally:
        cfg.CHIKA_API_KEY = original


def test_auth_rejects_malformed_header():
    original = cfg.CHIKA_API_KEY
    try:
        cfg.CHIKA_API_KEY = "mykey"
        resp = client.get("/api/sessions", headers={"Authorization": "Token mykey"})
        assert resp.status_code == 401
    finally:
        cfg.CHIKA_API_KEY = original


# ── Parametrized auth matrix ─────────────────────────────────────────────────

@pytest.mark.parametrize("header,key,expected_status", [
    # Auth disabled (empty key) — all requests pass regardless of header
    (None,                          "",          200),
    ("Bearer wrong",                "",          200),
    # Auth enabled — various failure modes
    (None,                          "secret",    401),  # no header
    ("Bearer wrong",                "secret",    401),  # wrong key
    ("Token secret",                "secret",    401),  # wrong scheme
    ("secret",                      "secret",    401),  # no scheme prefix
    # Auth enabled — success
    ("Bearer secret",               "secret",    200),
])
def test_auth_parametrized(header, key, expected_status):
    original = cfg.CHIKA_API_KEY
    try:
        cfg.CHIKA_API_KEY = key
        headers = {"Authorization": header} if header else {}
        resp = client.get("/api/sessions", headers=headers)
        assert resp.status_code == expected_status, (
            f"header={header!r}, key={key!r} → got {resp.status_code}, want {expected_status}"
        )
    finally:
        cfg.CHIKA_API_KEY = original


# ── /auth/spotify/status ─────────────────────────────────────────────────────

def test_spotify_status_returns_200():
    resp = client.get("/auth/spotify/status")
    assert resp.status_code == 200


def test_spotify_status_includes_authorized_field():
    resp = client.get("/auth/spotify/status")
    data = resp.json()
    assert "authorized" in data


# ── WebSocket ─────────────────────────────────────────────────────────────────

def test_websocket_accepts_connection():
    with client.websocket_connect("/ws/test_ws_session") as ws:
        ws.send_json({"type": "ping"})
        data = ws.receive_json()
        assert data["type"] == "pong"


def test_websocket_ping_pong():
    with client.websocket_connect("/ws/ping_pong_session") as ws:
        ws.send_json({"type": "ping"})
        data = ws.receive_json()
        assert data["type"] == "pong"


def test_websocket_reset_sends_reset_done():
    with client.websocket_connect("/ws/reset_ws_session") as ws:
        ws.send_json({"type": "reset"})
        data = ws.receive_json()
        assert data["type"] == "reset_done"
        assert data["session_id"] == "reset_ws_session"


def test_websocket_invalid_json_returns_error():
    with client.websocket_connect("/ws/bad_json_session") as ws:
        ws.send_text("not valid json {{")
        data = ws.receive_json()
        assert data["type"] == "error"


def test_websocket_auth_rejected_with_wrong_token():
    original = cfg.CHIKA_API_KEY
    try:
        cfg.CHIKA_API_KEY = "required_key"
        from starlette.websockets import WebSocketDisconnect as WSDisconnect
        with pytest.raises(WSDisconnect):
            with client.websocket_connect("/ws/auth_test?token=wrong") as ws:
                pass
    finally:
        cfg.CHIKA_API_KEY = original


def test_websocket_auth_accepted_with_correct_token():
    original = cfg.CHIKA_API_KEY
    try:
        cfg.CHIKA_API_KEY = "my_key"
        with client.websocket_connect("/ws/auth_ok_session?token=my_key") as ws:
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"
    finally:
        cfg.CHIKA_API_KEY = original


def test_websocket_user_message_no_crash_without_llm():
    """Empty text should be skipped silently (not crash)."""
    with client.websocket_connect("/ws/msg_session") as ws:
        ws.send_json({"type": "user_message", "text": ""})
        # Empty text is skipped — just check no exception thrown
        ws.send_json({"type": "ping"})
        data = ws.receive_json()
        assert data["type"] == "pong"

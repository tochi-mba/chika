"""Smoke tests for the spotify status endpoint.

Migrated out of ``tests/test_api_server.py`` so the spotify skill's
HTTP surface is fully tested inside its own folder — drop the skill,
the tests go with it (skill-isolation contract)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the repo root is on path before importing the API server.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Force-disable auth so these tests don't need an API key.
os.environ.pop("CHIKA_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from api.server import app  # noqa: E402

client = TestClient(app)


def test_status_returns_200():
    resp = client.get("/api/spotify/status")
    assert resp.status_code == 200


def test_status_includes_authorized_field():
    resp = client.get("/api/spotify/status")
    data = resp.json()
    assert "authorized" in data

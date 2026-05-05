"""Frontend ↔ backend contract test.

Hard-codes every URL the Vue app and the extension popup actually call,
plus the HTTP method they use. For each pair we assert the running
FastAPI exposes a route accepting that method.

Routability check goes via the OpenAPI schema, NOT by hitting endpoints
— too many handlers return their own 404 ("no tracked process with
pid=42") which is indistinguishable from "route not registered" at the
TestClient layer. The schema is authoritative: if a path+method appear
there, the route is wired.

Why this exists:
    Playwright tests stub ``window.fetch`` to return canned JSON
    (see frontend/e2e/_fixtures.js + profile_gate.spec.js), so they
    never integration-test the real backend. The route mismatch that
    showed up at runtime — frontend hitting /api/pets and getting 404
    because the running backend was a stale process from a different
    directory — would have been caught by this contract test.

Add a row whenever the frontend starts calling a new endpoint, OR when
a backend route is renamed/moved. Keeping the table here forces both
sides to stay in sync via a single PR. The first failure here usually
means one side renamed without telling the other.
"""
from __future__ import annotations

import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

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


# ── Contract table ──────────────────────────────────────────────────────────
#
# Each row: (METHOD, frontend_path, backend_template, source).
#
#   frontend_path     — what the JS actually fetches; may have concrete
#                       segments like "sample" where the backend has
#                       "{name}". Useful for diffing client code.
#   backend_template  — the openapi-style template the FastAPI route
#                       declares. {param} in matching positions.
#   source            — file:line of the caller, for failure messages.

_FRONTEND_CALLS: list[tuple[str, str, str, str]] = [
    # ── ProfileGate ────────────────────────────────────────────────────
    ("GET",   "/api/profiles",           "/api/profiles",           "ProfileGate.vue:122"),
    ("POST",  "/api/profiles/select",    "/api/profiles/select",    "ProfileGate.vue:159"),
    ("POST",  "/api/profiles/create",    "/api/profiles/create",    "ProfileGate.vue:190"),

    # ── ProfileSwitcher ────────────────────────────────────────────────
    ("GET",   "/api/profiles",           "/api/profiles",           "ProfileSwitcher.vue:77"),

    # ── PetCompanion / SettingsModal ───────────────────────────────────
    ("GET",   "/api/pets",               "/api/pets",               "PetCompanion.vue:42"),
    ("GET",   "/api/profile/x/pet",      "/api/profile/{name}/pet", "SettingsModal.vue:374"),
    ("PATCH", "/api/profile/x/pet",      "/api/profile/{name}/pet", "SettingsModal.vue:395"),

    # ── SettingsModal — provider, env, settings (all PATCH for partial
    # updates; the backend exposes GET to read + PATCH to update) ──────
    ("GET",   "/api/provider",           "/api/provider",           "SettingsModal.vue:220"),
    ("PATCH", "/api/provider",           "/api/provider",           "SettingsModal.vue:237"),
    ("PATCH", "/api/env",                "/api/env",                "SettingsModal.vue:334"),
    ("GET",   "/api/settings",           "/api/settings",           "useChika.js:45"),
    ("PATCH", "/api/settings",           "/api/settings",           "useChika.js:46 (patchSettings)"),

    # ── ShellsPanel ────────────────────────────────────────────────────
    ("POST",  "/api/shells/42/kill",     "/api/shells/{pid}/kill",  "ShellsPanel.vue:160"),
    ("POST",  "/api/shells/kill_all",    "/api/shells/kill_all",    "ShellsPanel.vue:177"),

    # ── Extension popup ────────────────────────────────────────────────
    ("GET",   "/api/profiles",           "/api/profiles",           "popup.js:158"),
    ("POST",  "/api/profiles/select",    "/api/profiles/select",    "popup.js:215"),
    ("POST",  "/api/profiles/create",    "/api/profiles/create",    "popup.js:252"),
    ("GET",   "/api/profile/x/pet",      "/api/profile/{name}/pet", "popup.js:513"),

    # ── Extension options ──────────────────────────────────────────────
    ("GET",   "/api/settings",           "/api/settings",           "options.js:41"),
    ("PATCH", "/api/settings",           "/api/settings",           "options.js:178"),
    ("GET",   "/health",                 "/health",                 "options.js:209"),

    # ── Health (sanity) ────────────────────────────────────────────────
    ("GET",   "/health",                 "/health",                 "smoke check"),
]


# OpenAPI schema is the source of truth for which (method, path)
# combinations are registered. Build a single index up-front.
_SCHEMA = app.openapi()
_REGISTERED: dict[str, set[str]] = {
    path: {m.upper() for m in spec.keys() if m.lower() in {
        "get", "post", "put", "patch", "delete", "head", "options",
    }}
    for path, spec in _SCHEMA["paths"].items()
}


def _allowed_methods_for_template(template: str) -> set[str]:
    """All HTTP methods registered for an openapi-style path template."""
    return _REGISTERED.get(template, set())


@pytest.mark.parametrize(
    "method,frontend_path,backend_template,source",
    _FRONTEND_CALLS,
    ids=lambda v: v if isinstance(v, str) and len(v) < 60 else None,
)
def test_frontend_url_resolves_to_backend_route(
    method: str, frontend_path: str, backend_template: str, source: str,
):
    """Every frontend URL must hit a registered backend route + method.

    Failure modes this catches:
      * Backend route renamed/removed but frontend still calls old path
      * Frontend started calling a new path that nobody implemented
      * Method drift (frontend POST ↔ backend PATCH — exactly the
        regression we hit when SettingsModal POSTs were checked)
    """
    allowed = _allowed_methods_for_template(backend_template)

    assert allowed, (
        f"backend has no route registered at {backend_template!r}. "
        f"Frontend caller: {source} (calls {method} {frontend_path}). "
        f"Either add the route on the backend or update the frontend."
    )
    assert method in allowed, (
        f"backend route {backend_template!r} exists but doesn't accept "
        f"{method} (allows: {sorted(allowed)}). "
        f"Frontend caller: {source}. Method drift between frontend and backend."
    )


def test_websocket_endpoints_exist():
    """Both WS endpoints (/ws/ for the frontend, /ws/extension/ for the
    Chrome extension) must be registered. We verify by inspecting the
    Starlette routing table — a full handshake spawns long-running
    background tasks that don't tear down cleanly inside TestClient,
    so connect-only is enough for the contract guarantee.
    """
    ws_paths = {
        getattr(r, "path", None)
        for r in app.routes
        if "WebSocket" in r.__class__.__name__
    }
    assert "/ws/" in ws_paths, (
        "frontend WebSocket route /ws/ is missing — frontend useChika.js "
        "won't be able to connect."
    )
    assert "/ws/extension/" in ws_paths, (
        "extension WebSocket route /ws/extension/ is missing — Chrome "
        "extension popup won't be able to connect."
    )


def test_frontend_path_matches_backend_template():
    """Sanity: each frontend_path actually fits the backend_template.

    Catches typos in this file itself — e.g. listing
    ``/api/profile/x/pet`` against the template ``/api/profiles/{name}``
    by accident. Compare segment-by-segment, allowing concrete frontend
    segments to fill template ``{param}`` slots.
    """
    for method, frontend_path, backend_template, source in _FRONTEND_CALLS:
        f_segments = frontend_path.strip("/").split("/")
        t_segments = backend_template.strip("/").split("/")
        assert len(f_segments) == len(t_segments), (
            f"frontend path {frontend_path!r} has different segment count "
            f"than template {backend_template!r}. Source: {source}"
        )
        for f_seg, t_seg in zip(f_segments, t_segments):
            if t_seg.startswith("{") and t_seg.endswith("}"):
                # template placeholder — anything goes
                continue
            assert f_seg == t_seg, (
                f"frontend segment {f_seg!r} doesn't match template "
                f"segment {t_seg!r} in {frontend_path} -> {backend_template}. "
                f"Source: {source}"
            )

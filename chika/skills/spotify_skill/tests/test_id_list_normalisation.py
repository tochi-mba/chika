"""Multi-id arg normalisation across every spotify tool that takes one.

The original bug: ``spotify_play(uris=["spotify:track:..."])`` crashed
with ``AttributeError: 'list' object has no attribute 'split'``
because the handler called ``uris.split(",")`` directly. The LLM
legitimately emits any of:

  - ``"abc,def"``                — comma-separated string
  - ``["abc", "def"]``           — JSON list (Python list at dispatch)
  - ``'["abc","def"]'``          — JSON-encoded string

These tests exercise EVERY shape × EVERY affected handler so a
regression on any one tool gets caught immediately. The
``_to_id_list`` helper is the single normaliser; if it's bypassed
in a future edit, the corresponding handler test will fail.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from chika.skills import spotify_skill
from chika.skills.spotify_skill import _to_id_list

# ── _to_id_list — the helper itself ───────────────────────────────────


@pytest.mark.parametrize("value, expected", [
    # Empty / null
    ("",                                []),
    (None,                              []),
    ("   ",                             []),
    # Comma-separated string
    ("abc,def",                         ["abc", "def"]),
    ("  abc , def  ",                   ["abc", "def"]),  # whitespace forgiveness
    ("abc,,def",                        ["abc", "def"]),  # blank items dropped
    ("solo",                            ["solo"]),
    # Real Python list (most common LLM output via tool dispatch)
    (["abc", "def"],                    ["abc", "def"]),
    (["  abc  ", "def"],                ["abc", "def"]),  # element strip
    ([],                                []),
    ([""],                              []),
    # JSON-encoded list-as-string
    ('["abc","def"]',                   ["abc", "def"]),
    ('["  abc  ", "def"]',              ["abc", "def"]),
    ('[]',                              []),
    # Defensive: numbers in a list (Spotify ids are always strings,
    # but if a model slips an int through we coerce).
    ([1, 2],                            ["1", "2"]),
    # Nonsense input — coerces but doesn't crash.
    (42,                                ["42"]),
])
def test_to_id_list_normalises_every_shape(value: Any, expected: list[str]):
    assert _to_id_list(value) == expected


def test_to_id_list_preserves_order():
    """Order matters for spotify_play — first URI plays first."""
    assert _to_id_list(["c", "a", "b"]) == ["c", "a", "b"]
    assert _to_id_list("c,a,b") == ["c", "a", "b"]


def test_to_id_list_handles_malformed_json_string_falls_back_to_split():
    """``'[abc'`` (broken JSON) shouldn't raise — fall back to
    treating it as a comma-separated string."""
    assert _to_id_list("[abc") == ["[abc"]   # one element, raw


# ── End-to-end: every affected handler accepts both shapes ────────────


# Handlers that take an ``ids`` (or ``uris``) multi-value arg, mapped
# to (kwargs_for_string_form, kwargs_for_list_form, expected body key,
# expected list of ids in the body).
_HANDLER_CASES: list[tuple[str, dict, dict, str, list[str]]] = [
    # name,                   string-form kwargs,                  list-form kwargs,                       body key, expected
    ("spotify_play",          {"uris": "spotify:track:a,spotify:track:b"},
                              {"uris": ["spotify:track:a", "spotify:track:b"]},
                              "uris", ["spotify:track:a", "spotify:track:b"]),
    ("spotify_save_tracks",   {"ids":  "a,b"},  {"ids":  ["a", "b"]},  "ids", ["a", "b"]),
    ("spotify_remove_saved_tracks",
                              {"ids":  "a,b"},  {"ids":  ["a", "b"]},  "ids", ["a", "b"]),
    ("spotify_save_albums",   {"ids":  "a,b"},  {"ids":  ["a", "b"]},  "ids", ["a", "b"]),
    ("spotify_follow_artist", {"ids":  "a,b"},  {"ids":  ["a", "b"]},  "ids", ["a", "b"]),
    ("spotify_unfollow_artist",
                              {"ids":  "a,b"},  {"ids":  ["a", "b"]},  "ids", ["a", "b"]),
]


@pytest.mark.parametrize("handler_name,str_kwargs,list_kwargs,body_key,expected_ids", _HANDLER_CASES)
def test_handler_accepts_string_form(handler_name, str_kwargs, list_kwargs, body_key, expected_ids, monkeypatch):
    """Comma-separated string form — the legacy shape."""
    captured: dict = {}

    async def _fake_req(method, path, user_auth=False, params=None, json_body=None):
        captured["body"] = json_body
        return {"ok": True}

    monkeypatch.setattr(spotify_skill, "_req", _fake_req)
    handler = getattr(spotify_skill, handler_name)
    asyncio.run(handler(**str_kwargs))
    assert captured["body"][body_key] == expected_ids


@pytest.mark.parametrize("handler_name,str_kwargs,list_kwargs,body_key,expected_ids", _HANDLER_CASES)
def test_handler_accepts_list_form(handler_name, str_kwargs, list_kwargs, body_key, expected_ids, monkeypatch):
    """Real Python list — the shape that crashed the user's session."""
    captured: dict = {}

    async def _fake_req(method, path, user_auth=False, params=None, json_body=None):
        captured["body"] = json_body
        return {"ok": True}

    monkeypatch.setattr(spotify_skill, "_req", _fake_req)
    handler = getattr(spotify_skill, handler_name)
    asyncio.run(handler(**list_kwargs))
    assert captured["body"][body_key] == expected_ids


@pytest.mark.parametrize("handler_name,str_kwargs,list_kwargs,body_key,expected_ids", _HANDLER_CASES)
def test_handler_accepts_json_encoded_string_form(handler_name, str_kwargs, list_kwargs, body_key, expected_ids, monkeypatch):
    """JSON-encoded list-as-string — some models emit this."""
    captured: dict = {}

    async def _fake_req(method, path, user_auth=False, params=None, json_body=None):
        captured["body"] = json_body
        return {"ok": True}

    monkeypatch.setattr(spotify_skill, "_req", _fake_req)
    handler = getattr(spotify_skill, handler_name)
    import json
    json_kwargs = {k: json.dumps(v) if isinstance(v, list) else v for k, v in list_kwargs.items()}
    asyncio.run(handler(**json_kwargs))
    assert captured["body"][body_key] == expected_ids


# ── Specific regression — the exact crash from the user's session ─────


def test_spotify_play_with_list_does_not_raise_attributeerror(monkeypatch):
    """The ORIGINAL crash: ``spotify_play(uris=["spotify:track:..."])``
    raised ``AttributeError: 'list' object has no attribute 'split'``.
    Pin this so the regression can't sneak back in even if someone
    rewrites the helper later."""
    async def _fake_req(*args, **kwargs):
        return {"ok": True}
    monkeypatch.setattr(spotify_skill, "_req", _fake_req)

    # Same exact call shape from the user's bug report.
    result = asyncio.run(spotify_skill.spotify_play(
        uris=["spotify:track:2dILHRW2MAp8wxC07Q0Shb"],
        device_id="854ea0e7f4af3922b664b951503d013711667ee8",
    ))
    assert result == {"ok": True}, f"expected success, got {result!r}"


def test_spotify_play_with_empty_uris_omits_field(monkeypatch):
    """``spotify_play()`` with no uris should still hit the player —
    Spotify resumes whatever was playing. The body must NOT include
    a ``uris: []`` key (which would 400 the request)."""
    captured: dict = {}

    async def _fake_req(method, path, user_auth=False, params=None, json_body=None):
        captured["body"] = json_body
        return {"ok": True}
    monkeypatch.setattr(spotify_skill, "_req", _fake_req)

    asyncio.run(spotify_skill.spotify_play(device_id="abc"))
    assert "uris" not in captured["body"], (
        "spotify_play with no uris must omit the field — sending an "
        "empty list would 400 the request"
    )


def test_spotify_remove_from_playlist_handles_list(monkeypatch):
    """``remove_from_playlist`` builds ``[{"uri": ...}]`` per track —
    the list shape needs the per-element wrapper too."""
    captured: dict = {}

    async def _fake_req(method, path, user_auth=False, params=None, json_body=None):
        captured["body"] = json_body
        return {"ok": True}
    monkeypatch.setattr(spotify_skill, "_req", _fake_req)

    asyncio.run(spotify_skill.spotify_remove_from_playlist(
        playlist_id="pl1",
        uris=["spotify:track:a", "spotify:track:b"],
    ))
    assert captured["body"]["tracks"] == [
        {"uri": "spotify:track:a"},
        {"uri": "spotify:track:b"},
    ]

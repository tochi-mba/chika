"""Variable-store ``[*]`` projection — list-comprehension-style refs.

The agent often needs to extract one field from every item in a list
result. Without projection, it had to either:

  - hand-write each list index (``$tracks[0].uri``, ``$tracks[1].uri``,
    ...) — fails the moment the result length changes
  - feed the whole list-of-objects into a tool that wants a list of
    URI strings — gets back ``Invalid track uri: [{'album': {...}}]``

Both played out in real user sessions. ``$tracks[*].uri`` resolves
to ``["spotify:track:a", "spotify:track:b", ...]`` in one step.

Tests pin:
  - Top-level projection from a list-typed variable
  - Nested projection (``$result.tracks[*].uri``)
  - Projection that skips items missing the deeper path (best-effort)
  - Index AND projection composing (``$results[*].items[0].id``)
  - Empty list → empty result (not error)
  - Non-list at the projection point → unresolved
  - Backward compat: scalar / dotted / indexed paths still work
"""
from __future__ import annotations

from chika.core.variable_store import VariableStore, VarType


def _vs_with(name: str, value):
    vs = VariableStore()
    vs.set(name, value, var_type=VarType.JSON)
    return vs


def test_projection_extracts_field_from_each_item():
    """The exact scenario from the user's session — pull ``uri``
    from every track in a Spotify top-tracks response."""
    vs = _vs_with("top_tracks", {
        "tracks": [
            {"name": "A", "uri": "spotify:track:a"},
            {"name": "B", "uri": "spotify:track:b"},
            {"name": "C", "uri": "spotify:track:c"},
        ],
    })
    out = vs.resolve("$top_tracks.tracks[*].uri")
    assert out == ["spotify:track:a", "spotify:track:b", "spotify:track:c"]


def test_projection_at_top_level():
    vs = _vs_with("ids", [{"id": "a"}, {"id": "b"}])
    assert vs.resolve("$ids[*].id") == ["a", "b"]


def test_projection_skips_items_missing_subpath():
    """If some items lack the deeper path, they're skipped (not an
    error). Best-effort projection — partial results are useful."""
    vs = _vs_with("mixed", [
        {"uri": "track:a"},
        {"name": "no-uri-here"},   # missing .uri
        {"uri": "track:c"},
    ])
    assert vs.resolve("$mixed[*].uri") == ["track:a", "track:c"]


def test_projection_returns_empty_list_for_empty_source():
    vs = _vs_with("empty", {"items": []})
    assert vs.resolve("$empty.items[*].id") == []


def test_projection_with_non_list_returns_unresolved():
    """Trying to project a dict (not a list) returns the original
    ref so the agent gets a clear ``unresolved_variable`` error."""
    vs = _vs_with("not_a_list", {"items": {"foo": "bar"}})
    out = vs.resolve("$not_a_list.items[*].foo")
    assert isinstance(out, str) and out.startswith("$")


def test_projection_composes_with_index():
    """``$x[*].items[0].id`` — for each entry, pick ``items[0].id``."""
    vs = _vs_with("data", [
        {"items": [{"id": "a1"}, {"id": "a2"}]},
        {"items": [{"id": "b1"}]},
    ])
    assert vs.resolve("$data[*].items[0].id") == ["a1", "b1"]


def test_projection_with_nested_dict_value():
    """Project an entire sub-dict, not just a scalar."""
    vs = _vs_with("results", [
        {"track": {"id": "1", "name": "A"}},
        {"track": {"id": "2", "name": "B"}},
    ])
    out = vs.resolve("$results[*].track")
    assert out == [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]


# ── Backward compatibility — old paths still work unchanged ───────────


def test_simple_scalar_ref_still_works():
    vs = _vs_with("greeting", "hello")
    assert vs.resolve("$greeting") == "hello"


def test_dotted_ref_still_works():
    vs = _vs_with("user", {"profile": {"name": "Tochi"}})
    assert vs.resolve("$user.profile.name") == "Tochi"


def test_indexed_ref_still_works():
    vs = _vs_with("items", ["a", "b", "c"])
    assert vs.resolve("$items[1]") == "b"


def test_dotted_then_indexed_still_works():
    vs = _vs_with("data", {"items": [{"id": 0}, {"id": 1}]})
    assert vs.resolve("$data.items[1].id") == 1


def test_unresolved_ref_returns_literal_string():
    vs = VariableStore()
    out = vs.resolve("$nothing")
    assert out == "$nothing"


def test_resolve_walks_into_lists_and_dicts():
    vs = _vs_with("ids", ["a", "b"])
    out = vs.resolve({"uris": ["$ids[0]", "$ids[1]", "literal"]})
    assert out == {"uris": ["a", "b", "literal"]}


# ── End-to-end: the user's real session, fixed ────────────────────────


def test_user_session_top_tracks_projection():
    """Reproduces the exact failing case from the user's session.
    With projection support, ``$top_tracks.tracks[*].uri`` resolves
    in one step instead of the agent fumbling for three turns."""
    vs = _vs_with("top_tracks", {
        "tracks": [
            {"album": {"name": "X"}, "uri": "spotify:track:6sTlzpJa"},
            {"album": {"name": "Y"}, "uri": "spotify:track:5cw9s"},
            {"album": {"name": "Z"}, "uri": "spotify:track:abc"},
        ],
    })
    # Resolution at the workflow-arg level — same shape an LLM emits.
    workflow_args = {"uris": "$top_tracks.tracks[*].uri", "device_id": "abc"}
    resolved = vs.resolve(workflow_args)
    assert resolved == {
        "uris": ["spotify:track:6sTlzpJa", "spotify:track:5cw9s", "spotify:track:abc"],
        "device_id": "abc",
    }

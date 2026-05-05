"""Tests for the workspace-scope policy used by the file-write tools.

These pin the safety contract: writes inside the active profile's
workspace pass through; writes outside trigger an approval flow that
returns one of ``session`` / ``once`` / ``deny``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from chika.core.workspace_policy import WorkspaceDecision, WorkspacePolicy


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def policy(workspace: Path) -> WorkspacePolicy:
    return WorkspacePolicy(workspace=str(workspace))


# ── Path classification ──────────────────────────────────────────────────


def test_inside_workspace_is_recognised(policy: WorkspacePolicy, workspace: Path):
    assert policy.is_inside_workspace(workspace / "a.txt") is True
    assert policy.is_inside_workspace(workspace / "nested" / "b.txt") is True


def test_outside_workspace_is_recognised(policy: WorkspacePolicy, tmp_path: Path):
    other = tmp_path / "outside" / "x.txt"
    other.parent.mkdir(parents=True, exist_ok=True)
    assert policy.is_inside_workspace(other) is False


def test_session_grants_extend_to_descendants(policy: WorkspacePolicy, tmp_path: Path):
    grant = tmp_path / "shared"
    grant.mkdir()
    policy.session_grants.add(str(grant))
    assert policy.is_session_granted(grant / "a.txt") is True
    assert policy.is_session_granted(grant / "deep" / "b.txt") is True
    assert policy.is_session_granted(tmp_path / "elsewhere" / "c.txt") is False


# ── Approval flow ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inside_workspace_no_approval_needed(
    policy: WorkspacePolicy, workspace: Path,
):
    handler_called = False

    async def handler(**_kw):
        nonlocal handler_called
        handler_called = True
        return {"scope": "deny"}

    decision = await policy.check(
        workspace / "x.txt", action="write", approval_handler=handler,
    )
    assert decision.allowed
    assert decision.scope == "inside"
    assert handler_called is False  # short-circuit


@pytest.mark.asyncio
async def test_outside_with_session_grant_short_circuits(
    policy: WorkspacePolicy, tmp_path: Path,
):
    grant_dir = tmp_path / "always_ok"
    grant_dir.mkdir()
    policy.session_grants.add(str(grant_dir))

    async def handler(**_kw):
        raise AssertionError("handler should not be called when grant exists")

    decision = await policy.check(
        grant_dir / "y.txt", action="write", approval_handler=handler,
    )
    assert decision.allowed
    assert decision.scope == "session"


@pytest.mark.asyncio
async def test_outside_no_grant_calls_handler_for_once(
    policy: WorkspacePolicy, tmp_path: Path,
):
    target = tmp_path / "stranger" / "z.txt"
    target.parent.mkdir()

    async def handler(**_kw):
        return {"scope": "once"}

    decision = await policy.check(
        target, action="write", approval_handler=handler,
    )
    assert decision.allowed
    assert decision.scope == "once"
    # "once" must NOT extend to future calls.
    assert not policy.session_grants


@pytest.mark.asyncio
async def test_session_scope_remembers_folder(
    policy: WorkspacePolicy, tmp_path: Path,
):
    target = tmp_path / "dir_a" / "file.txt"
    target.parent.mkdir()

    async def handler(**_kw):
        return {"scope": "session"}

    first = await policy.check(target, action="write", approval_handler=handler)
    assert first.allowed and first.scope == "session"

    # Second call to a sibling — handler must NOT be re-invoked.
    sibling = tmp_path / "dir_a" / "another.txt"

    async def fail_handler(**_kw):
        raise AssertionError("session grant should short-circuit second call")

    second = await policy.check(
        sibling, action="write", approval_handler=fail_handler,
    )
    assert second.allowed
    assert second.scope == "session"


@pytest.mark.asyncio
async def test_deny_response_blocks(
    policy: WorkspacePolicy, tmp_path: Path,
):
    async def handler(**_kw):
        return {"scope": "deny", "reason": "no thanks"}

    decision = await policy.check(
        tmp_path / "private.txt", action="write", approval_handler=handler,
    )
    assert not decision.allowed
    assert decision.scope == "denied"
    assert "no thanks" in decision.reason


@pytest.mark.asyncio
async def test_handler_returning_legacy_bool_is_accepted(
    policy: WorkspacePolicy, tmp_path: Path,
):
    """Old approval handlers return plain bool — ensure we treat
    True as one-shot allow and False as deny."""
    async def yes_handler(**_kw):
        return True

    async def no_handler(**_kw):
        return False

    yes = await policy.check(
        tmp_path / "a.txt", action="write", approval_handler=yes_handler,
    )
    assert yes.allowed and yes.scope == "once"

    no = await policy.check(
        tmp_path / "b.txt", action="write", approval_handler=no_handler,
    )
    assert not no.allowed and no.scope == "denied"


@pytest.mark.asyncio
async def test_no_approval_handler_auto_grants(
    policy: WorkspacePolicy, tmp_path: Path,
):
    """When there's no UI to ask (autonomous unsupervised batch), allow
    the write so the job actually finishes — but tag the decision so the
    caller / log can audit."""
    decision = await policy.check(
        tmp_path / "robot.txt", action="write", approval_handler=None,
    )
    assert decision.allowed
    assert decision.scope == "auto_grant"


@pytest.mark.asyncio
async def test_handler_exception_results_in_deny(
    policy: WorkspacePolicy, tmp_path: Path,
):
    async def boom_handler(**_kw):
        raise RuntimeError("approval channel dropped")

    decision = await policy.check(
        tmp_path / "x.txt", action="write", approval_handler=boom_handler,
    )
    assert not decision.allowed
    assert decision.scope == "denied"
    assert "approval handler raised" in decision.reason

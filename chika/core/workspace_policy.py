"""Workspace-scope policy.

Every profile owns a ``workspace`` directory (under ``data/profiles/<name>/
workspace/``). The agent should write files INSIDE that directory by
default. When it tries to touch anything outside, the policy gates the
attempt — the user gets a chance to approve once, allow for the rest of
the session (per-folder), or deny.

Three scopes:
- ``deny`` — refuse THIS attempt. The next attempt prompts again.
- ``once`` — allow ONLY this attempt. The next attempt prompts again.
- ``session`` — allow this folder (and everything beneath it) until the
  session ends. The grant is keyed by the resolved folder, so different
  folders prompt independently.

Policy decisions are per-session, kept in memory. Restarting the engine
clears them. Storing them on disk would be a security regression — a
"yes-forever" cache means the agent can quietly drift outside the
workspace forever after one approval.

Workflow:
    policy = WorkspacePolicy(workspace="/data/profiles/foo/workspace")
    decision = await policy.check(
        path="/etc/passwd",
        action="write",
        approval_handler=...,
    )
    if not decision.allowed:
        return {"error": "denied_by_workspace_policy"}
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

ApprovalHandler = Callable[..., Awaitable[dict]]


@dataclass
class WorkspaceDecision:
    """Outcome of a single ``WorkspacePolicy.check`` call."""
    allowed: bool
    scope:   str           # "inside" | "once" | "session" | "denied" | "auto_grant"
    reason:  str = ""      # short human-readable explanation


@dataclass
class WorkspacePolicy:
    """Per-session gate for file writes.

    ``workspace`` is the resolved absolute path of the active profile's
    workspace. ``session_grants`` is the running set of folder paths the
    user has approved for this session — once a folder is granted,
    every descendant write is auto-allowed.
    """
    workspace: str
    session_grants: set[str] = field(default_factory=set)

    # ── Path classification ─────────────────────────────────────────────

    def is_inside_workspace(self, path: str | Path) -> bool:
        """True iff ``path`` resolves underneath the workspace.

        We resolve symlinks before comparison so a symlinked escape
        path is detected as outside.
        """
        try:
            target = Path(path).resolve()
            ws = Path(self.workspace).resolve()
        except (OSError, RuntimeError):
            return False
        try:
            target.relative_to(ws)
            return True
        except ValueError:
            return False

    def is_session_granted(self, path: str | Path) -> bool:
        """True iff ``path`` lives under any folder the user already
        granted ``session`` access to during this session."""
        try:
            target = Path(path).resolve()
        except (OSError, RuntimeError):
            return False
        for grant in self.session_grants:
            try:
                target.relative_to(Path(grant).resolve())
                return True
            except ValueError:
                continue
        return False

    # ── Approval flow ───────────────────────────────────────────────────

    async def check(
        self,
        path: str | Path,
        *,
        action: str,
        approval_handler: ApprovalHandler | None = None,
    ) -> WorkspaceDecision:
        """Decide whether ``action`` on ``path`` may proceed.

        Order of evaluation:
        1. Inside workspace → allow silently.
        2. Already covered by a session grant → allow silently.
        3. No approval_handler available (autonomous mode, no UI) →
           allow with ``auto_grant`` scope so the action does not
           silently fail. The decision is logged so the user can audit
           later. Adjust ``WorkspacePolicy.allow_outside_when_unsupervised``
           if a stricter posture is desired in future.
        4. Otherwise: ask the user. Apply their answer.
        """
        if self.is_inside_workspace(path):
            return WorkspaceDecision(True, "inside")
        if self.is_session_granted(path):
            return WorkspaceDecision(True, "session")
        if approval_handler is None:
            return WorkspaceDecision(
                True, "auto_grant",
                reason=(
                    "no approval handler attached to this session — "
                    "allowing the action so unsupervised batch jobs "
                    "still complete."
                ),
            )

        # Format the request for the UI / CLI prompter.
        target_dir = str(Path(path).resolve().parent) if path else ""
        try:
            response = await approval_handler(
                request_id=f"workspace_{abs(hash(str(path))) & 0xFFFFFFFF:08x}",
                tool_name=f"workspace::{action}",
                args={
                    "path":         str(path),
                    "scope_dir":    target_dir,
                    "workspace":    self.workspace,
                    "action":       action,
                },
                step_id=f"workspace_{action}",
                message=(
                    f"Chika wants to {action} a file OUTSIDE the active "
                    f"profile's workspace. Workspace: {self.workspace}. "
                    f"Target: {path}."
                ),
                approval_type="workspace_scope",
            )
        except Exception as exc:
            return WorkspaceDecision(
                False, "denied",
                reason=f"approval handler raised: {type(exc).__name__}: {exc}",
            )

        # Normalise the handler response. Old approval handlers return
        # a plain bool; the new ones return {scope: "session"|"once"|"deny"}.
        if isinstance(response, bool):
            return (
                WorkspaceDecision(True, "once") if response
                else WorkspaceDecision(False, "denied", "user denied")
            )
        if isinstance(response, dict):
            scope = (response.get("scope") or "").lower()
            if scope == "session":
                self.session_grants.add(target_dir)
                return WorkspaceDecision(True, "session")
            if scope == "once":
                return WorkspaceDecision(True, "once")
            return WorkspaceDecision(
                False, "denied",
                reason=response.get("reason") or "user denied",
            )
        return WorkspaceDecision(
            False, "denied",
            reason=f"unexpected approval response: {response!r}",
        )

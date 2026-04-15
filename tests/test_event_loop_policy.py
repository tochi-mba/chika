"""
Regression: on Windows, the server MUST set WindowsProactorEventLoopPolicy
before uvicorn starts, or every shell_exec from a WebSocket handler raises
`NotImplementedError` because the default Selector loop can't spawn
subprocesses.

This was observed in production as `NotImplementedError: NotImplementedError()`
when the LLM tried to run any shell command via chat.
"""
import sys
import asyncio


def test_server_sets_proactor_policy_on_windows():
    """
    On Windows, importing api.server must leave the event-loop policy as
    Proactor (or any subclass thereof). On non-Windows platforms this test
    is a no-op success.
    """
    # Clean import of the server module to trigger its startup code
    # (including the policy set).
    if "api.server" in sys.modules:
        del sys.modules["api.server"]
    import api.server  # noqa: F401

    if sys.platform != "win32":
        # Nothing to check — non-Windows has no policy concern
        return

    policy = asyncio.get_event_loop_policy()
    # Should be a ProactorEventLoopPolicy (or subclass).
    name = type(policy).__name__
    assert "Proactor" in name, (
        f"api.server didn't set WindowsProactorEventLoopPolicy; "
        f"current policy is {name}. This means shell_exec calls from "
        f"WebSocket handlers will raise NotImplementedError."
    )


def test_selector_policy_reproduces_the_bug_without_the_fix():
    """
    Document the failure mode this fix prevents. We set Selector policy,
    try create_subprocess_shell, and confirm it raises NotImplementedError.
    """
    if sys.platform != "win32":
        return

    # Don't permanently disturb the test suite's loop policy.
    original = asyncio.get_event_loop_policy()
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        async def _try_subprocess():
            await asyncio.create_subprocess_shell(
                "echo bug",
                stdout=asyncio.subprocess.PIPE,
            )

        try:
            asyncio.run(_try_subprocess())
            raised = None
        except NotImplementedError as e:
            raised = e

        assert raised is not None, (
            "Expected NotImplementedError on Selector loop — test setup "
            "may have silently switched loops."
        )
    finally:
        asyncio.set_event_loop_policy(original)

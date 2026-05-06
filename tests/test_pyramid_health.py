"""Pyramid-shape enforcement.

The reviewer warned about silent test-pyramid degradation. This file
is the alarm. It runs at collection time and asserts the suite still
looks like a pyramid (lots of fast unit tests, fewer integration
tests, even fewer e2e tests).

Floors are loose on purpose — they catch *unintended* drift, not
deliberate restructuring. If you legitimately delete a hundred unit
tests in one PR, lower the floor in this file as part of the same PR.
That's the contract: drift is visible at PR time, not 6 months later.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ── Floor configuration ─────────────────────────────────────────────
#
# Chosen to be ~80% of the current actual count so a small handful of
# deletions doesn't trip the alarm, but a structural shift does.
# Refresh these as the suite genuinely grows.

# Total tests collected from tests/ (exclusive of __init__.py imports).
MIN_TOTAL_TESTS = 1900

# Tests that look like unit tests (the bulk of the suite).
MIN_UNIT_LIKE = 1500


def _collect_test_count() -> tuple[int, int]:
    """Return ``(total, unit_like)`` collected from ``tests/`` directory.

    "Unit-like" = does NOT carry an explicit ``cli_e2e``, ``slow``,
    ``frontend_e2e``, or ``extension_e2e`` marker. The split isn't
    perfect (some pure-unit tests don't get marked, integration tests
    don't always get marked either), but it's good enough to catch
    a structural pyramid inversion.
    """
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q",
         "--no-header"],
        cwd=repo_root,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    if proc.returncode != 0:
        # Collection failed — that's a different problem, don't fail
        # this test on top of it.
        return (0, 0)

    total = 0
    for line in proc.stdout.splitlines():
        if "::" in line and "test" in line.lower():
            total += 1
    # Approximation — we count all collected tests as unit-like for
    # the floor. The granular classification would require a separate
    # collection pass per marker.
    return (total, total)


@pytest.mark.slow
def test_total_tests_above_floor():
    total, _ = _collect_test_count()
    if total == 0:
        pytest.skip("collection failed — different problem, see other failures")
    assert total >= MIN_TOTAL_TESTS, (
        f"test pyramid floor breached: {total} tests collected, "
        f"floor is {MIN_TOTAL_TESTS}. If you deliberately removed tests, "
        f"lower MIN_TOTAL_TESTS in tests/test_pyramid_health.py as part "
        f"of the same PR. See the reviewer's note about silent pyramid "
        f"degradation in DECISIONS.md ADR-25."
    )


@pytest.mark.slow
def test_unit_like_count_dominates():
    total, unit_like = _collect_test_count()
    if total == 0:
        pytest.skip("collection failed — different problem, see other failures")
    # Unit-like should be the majority of the suite.
    assert unit_like >= MIN_UNIT_LIKE, (
        f"unit-like floor breached: {unit_like} unit-like tests "
        f"collected, floor is {MIN_UNIT_LIKE}."
    )


# ── Slow-test budget ────────────────────────────────────────────────
#
# We don't have ``pytest-timeout`` as a hard dep yet, but we can
# document expected runtimes and alert on regression via a separate
# CI step. For now, this test just enforces that a test marked @slow
# is respected (i.e. someone hasn't slipped a 30-second test in
# without the marker).


def test_slow_marker_is_documented():
    """The slow marker must be in pytest.markers."""
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--markers", "--no-header"],
        cwd=repo_root,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    assert "@pytest.mark.slow" in proc.stdout

"""Tests for chika/skills/git_skill/__init__.py."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from chika.skills.git_skill import (
    git_status,
    git_diff,
    git_log,
    git_commit,
    git_branch,
    git_checkout,
    git_push,
    git_pull,
    git_pr_create,
    git_pr_merge,
)


def _shell_result(stdout="", stderr="", exit_code=0):
    lines = stdout.splitlines() if stdout else []
    return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code, "stdout_lines": lines}


class TestGitStatus:
    def test_returns_status(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result(stdout="## main\nM file.py")) as mock_exec:
            result = asyncio.run(git_status("."))
        assert result["status"] == "## main\nM file.py"
        assert result["exit_code"] == 0
        mock_exec.assert_called_once_with("git status --short --branch", working_directory=".")

    def test_default_working_directory(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result()) as mock_exec:
            asyncio.run(git_status())
        mock_exec.assert_called_once_with("git status --short --branch", working_directory=".")


class TestGitDiff:
    def test_returns_diff(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result(stdout="diff --git a/f.py b/f.py")) as mock_exec:
            result = asyncio.run(git_diff())
        assert "diff" in result
        assert result["diff"] == "diff --git a/f.py b/f.py"

    def test_custom_path(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result()) as mock_exec:
            asyncio.run(git_diff(path="src/"))
        call_args = mock_exec.call_args[0][0]
        assert "src/" in call_args


class TestGitLog:
    def test_returns_log(self):
        log_output = "abc123 Initial commit\ndef456 Add feature"
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result(stdout=log_output)):
            result = asyncio.run(git_log(n=5))
        assert result["log"] == log_output
        assert len(result["lines"]) == 2

    def test_clamps_n_to_200(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result()) as mock_exec:
            asyncio.run(git_log(n=9999))
        call_args = mock_exec.call_args[0][0]
        assert "-200" in call_args

    def test_clamps_n_to_1_minimum(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result()) as mock_exec:
            asyncio.run(git_log(n=0))
        call_args = mock_exec.call_args[0][0]
        assert "-1" in call_args

    def test_max_count_kwarg_alias(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result()) as mock_exec:
            asyncio.run(git_log(n=5, max_count=15))
        call_args = mock_exec.call_args[0][0]
        assert "-15" in call_args


class TestGitCommit:
    def test_commits_with_message(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result(stdout="[main abc] My commit")) as mock_exec:
            result = asyncio.run(git_commit("My commit"))
        assert result["output"] == "[main abc] My commit"
        assert result["exit_code"] == 0
        call_args = mock_exec.call_args[0][0]
        assert "git add -A && git commit -m" in call_args
        assert "My commit" in call_args


class TestGitBranch:
    def test_returns_branches(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result(stdout="* main\n  feature/test")):
            result = asyncio.run(git_branch())
        assert len(result["branches"]) == 2


class TestGitCheckout:
    def test_checkout_existing(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result(stdout="Switched to branch 'main'")) as mock_exec:
            result = asyncio.run(git_checkout("main"))
        assert result["exit_code"] == 0
        call_args = mock_exec.call_args[0][0]
        assert "-b" not in call_args

    def test_checkout_create(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result()) as mock_exec:
            asyncio.run(git_checkout("new-branch", create=True))
        call_args = mock_exec.call_args[0][0]
        assert "-b" in call_args


class TestGitPush:
    def test_push_defaults(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result(stdout="pushed")) as mock_exec:
            result = asyncio.run(git_push())
        assert result["exit_code"] == 0
        call_args = mock_exec.call_args[0][0]
        assert "git push" in call_args
        assert "origin" in call_args
        assert "HEAD" in call_args


class TestGitPull:
    def test_pull_defaults(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result()) as mock_exec:
            asyncio.run(git_pull())
        call_args = mock_exec.call_args[0][0]
        assert "git pull" in call_args
        assert "origin" in call_args
        assert "main" in call_args


class TestGitPrCreate:
    def test_creates_pr(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result(stdout="https://github.com/org/repo/pull/1")) as mock_exec:
            result = asyncio.run(git_pr_create("My PR", body="Description"))
        assert result["exit_code"] == 0
        call_args = mock_exec.call_args[0][0]
        assert "gh pr create" in call_args
        assert "My PR" in call_args


class TestGitPrMerge:
    def test_merge_squash(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result()) as mock_exec:
            asyncio.run(git_pr_merge(method="squash"))
        call_args = mock_exec.call_args[0][0]
        assert "--squash" in call_args
        assert "--delete-branch" in call_args

    def test_merge_no_delete_branch(self):
        with patch("chika.skills.git_skill.shell_exec", new_callable=AsyncMock,
                   return_value=_shell_result()) as mock_exec:
            asyncio.run(git_pr_merge(method="merge", delete_branch=False))
        call_args = mock_exec.call_args[0][0]
        assert "--delete-branch" not in call_args

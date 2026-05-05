from __future__ import annotations

from shlex import quote

from chika.core.skill_registry import Skill
from chika.core.tool_registry import ToolDefinition
from chika.tools.shell_tool import shell_exec


async def git_status(working_directory: str = ".") -> dict:
    r = await shell_exec("git status --short --branch", working_directory=working_directory)
    return {"status": r["stdout"], "error": r["stderr"], "exit_code": r["exit_code"]}


async def git_diff(path: str = ".", working_directory: str = ".") -> dict:
    r = await shell_exec(f"git diff {path}", working_directory=working_directory)
    return {"diff": r["stdout"], "error": r["stderr"]}


async def git_log(n: int = 10, working_directory: str = ".", **kwargs) -> dict:
    """
    Get recent one-line commit log. Accepts `n` (primary name) or
    `max_count` (git's CLI flag name) as aliases — the LLM often reaches
    for `max_count` since that's what `git log` uses.
    """
    n = kwargs.get("max_count", kwargs.get("limit", n))
    n = max(1, min(int(n), 200))  # clamp to prevent abuse
    r = await shell_exec(f"git log --oneline -{n}", working_directory=working_directory)
    return {"log": r["stdout"], "lines": r["stdout_lines"]}


async def git_commit(message: str, working_directory: str = ".") -> dict:
    r = await shell_exec(
        f"git add -A && git commit -m {quote(message)}",
        working_directory=working_directory,
    )
    return {"output": r["stdout"], "error": r["stderr"], "exit_code": r["exit_code"]}


async def git_branch(working_directory: str = ".") -> dict:
    r = await shell_exec("git branch -a", working_directory=working_directory)
    return {"branches": r["stdout_lines"]}


async def git_checkout(branch: str, create: bool = False, working_directory: str = ".") -> dict:
    flag = "-b" if create else ""
    r = await shell_exec(f"git checkout {flag} {quote(branch)}".strip(), working_directory=working_directory)
    return {"output": r["stdout"] or r["stderr"], "exit_code": r["exit_code"]}


async def git_push(remote: str = "origin", branch: str = "HEAD", working_directory: str = ".") -> dict:
    r = await shell_exec(f"git push {quote(remote)} {quote(branch)}", working_directory=working_directory)
    return {"output": r["stdout"] or r["stderr"], "exit_code": r["exit_code"]}


async def git_pull(remote: str = "origin", branch: str = "main", working_directory: str = ".") -> dict:
    r = await shell_exec(f"git pull {quote(remote)} {quote(branch)}", working_directory=working_directory)
    return {"output": r["stdout"] or r["stderr"], "exit_code": r["exit_code"]}


async def git_pr_create(title: str, body: str = "", base: str = "main", working_directory: str = ".") -> dict:
    r = await shell_exec(
        f"gh pr create --title {quote(title)} --body {quote(body)} --base {quote(base)}",
        working_directory=working_directory,
    )
    return {"output": r["stdout"] or r["stderr"], "exit_code": r["exit_code"]}


async def git_pr_merge(
    method: str = "squash",
    delete_branch: bool = True,
    working_directory: str = ".",
) -> dict:
    flag = "--delete-branch" if delete_branch else ""
    r = await shell_exec(
        f"gh pr merge --{method} {flag}",
        working_directory=working_directory,
    )
    return {"output": r["stdout"] or r["stderr"], "exit_code": r["exit_code"]}


GIT_SKILL = Skill(
    name="git",
    description="Git operations — status, diff, log, commit, branch, push, PR create/merge",
    tools=[
        ToolDefinition(
            name="git_status",
            description="Get git status of a repo (branch + changed files).",
            parameters={
                "type": "object",
                "properties": {"working_directory": {"type": "string", "description": "Repo path (default .)"}},
            },
            handler=git_status,
        ),
        ToolDefinition(
            name="git_diff",
            description="Get diff of uncommitted changes.",
            parameters={
                "type": "object",
                "properties": {
                    "path":              {"type": "string"},
                    "working_directory": {"type": "string"},
                },
            },
            handler=git_diff,
        ),
        ToolDefinition(
            name="git_log",
            description="Get recent commit log (one-line format).",
            parameters={
                "type": "object",
                "properties": {
                    "n":                 {"type": "integer"},
                    "working_directory": {"type": "string"},
                },
            },
            handler=git_log,
        ),
        ToolDefinition(
            name="git_branch",
            description="List all branches (local and remote).",
            parameters={
                "type": "object",
                "properties": {"working_directory": {"type": "string"}},
            },
            handler=git_branch,
        ),
        ToolDefinition(
            name="git_checkout",
            description="Checkout an existing branch or create a new one (create=true).",
            parameters={
                "type": "object",
                "properties": {
                    "branch":            {"type": "string", "description": "Branch name"},
                    "create":            {"type": "boolean", "description": "True = create new branch"},
                    "working_directory": {"type": "string"},
                },
                "required": ["branch"],
            },
            handler=git_checkout,
        ),
        ToolDefinition(
            name="git_commit",
            description="Stage all changes (git add -A) and commit with the given message.",
            requires_approval=True,
            approval_message="Chika wants to commit changes to the repository.",
            parameters={
                "type": "object",
                "properties": {
                    "message":           {"type": "string"},
                    "working_directory": {"type": "string"},
                },
                "required": ["message"],
            },
            handler=git_commit,
        ),
        ToolDefinition(
            name="git_push",
            description="Push a branch to a remote. Defaults to 'git push origin HEAD'.",
            requires_approval=True,
            approval_message="Chika wants to push commits to the remote repository.",
            parameters={
                "type": "object",
                "properties": {
                    "remote":            {"type": "string", "description": "Remote name (default: origin)"},
                    "branch":            {"type": "string", "description": "Branch to push (default: HEAD)"},
                    "working_directory": {"type": "string"},
                },
            },
            handler=git_push,
        ),
        ToolDefinition(
            name="git_pull",
            description="Pull latest changes from a remote branch.",
            requires_approval=True,
            approval_message="Chika wants to pull the latest changes from the remote.",
            parameters={
                "type": "object",
                "properties": {
                    "remote":            {"type": "string"},
                    "branch":            {"type": "string"},
                    "working_directory": {"type": "string"},
                },
            },
            handler=git_pull,
        ),
        ToolDefinition(
            name="git_pr_create",
            description="Create a GitHub Pull Request using the gh CLI. Requires gh to be authenticated.",
            requires_approval=True,
            approval_message="Chika wants to open a Pull Request on GitHub.",
            parameters={
                "type": "object",
                "properties": {
                    "title":             {"type": "string"},
                    "body":              {"type": "string"},
                    "base":              {"type": "string", "description": "Target branch (default: main)"},
                    "working_directory": {"type": "string"},
                },
                "required": ["title"],
            },
            handler=git_pr_create,
        ),
        ToolDefinition(
            name="git_pr_merge",
            description="Merge the current branch's open PR using the gh CLI.",
            requires_approval=True,
            approval_message="Chika wants to merge a Pull Request into the main branch.",
            parameters={
                "type": "object",
                "properties": {
                    "method":            {"type": "string", "description": "squash | merge | rebase (default: squash)"},
                    "delete_branch":     {"type": "boolean", "description": "Delete branch after merge (default: true)"},
                    "working_directory": {"type": "string"},
                },
            },
            handler=git_pr_merge,
        ),
    ],
    workflow_examples="",
    memory_seeds={
        "git_conventions": "Use conventional commits: feat/fix/chore/docs/refactor/test",
    },
)

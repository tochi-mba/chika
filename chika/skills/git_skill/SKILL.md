# Git skill

Tools provided by this skill (call them inside a workflow_orchestrator step):

| Tool          | Purpose                                                   |
|---------------|-----------------------------------------------------------|
| `git_status`  | Show working-tree status. Always start here.              |
| `git_diff`    | Show staged or unstaged diff. Pass `staged: true` for the index. |
| `git_log`     | Recent commits. Default 10 entries; pass `limit` to override. |
| `git_branch`  | List or switch branches. Use `name: <new>` to create.     |
| `git_checkout`| Check out a branch or path. Requires confirmation.        |
| `git_commit`  | Commit staged changes. Requires `message`. **Never skip the user's commit-message conventions.** |
| `git_push`    | Push the current branch. Confirm before pushing.          |
| `git_pull`    | Pull from origin/<branch>.                                |
| `git_pr_create` | Open a PR via `gh`. Title under 70 chars; body in heredoc. |
| `git_pr_merge`  | Merge a PR by number. Always check CI status first.    |

## Conventions

- **Read before write**: run `git_status` before any `git_commit` so you can name modified files explicitly. Never `git add .`.
- **Stage explicit paths**: prefer `git add path/to/file.py` over `git add -A`.
- **Commit messages**: use the project's existing style (run `git_log limit=5` to learn it). Don't invent your own format.
- **PR titles**: short and imperative ("add", "fix", "refactor"). Long context goes in the body.

## Common workflows

### Fix and commit
```json
{"type": "sequential", "steps": [
  {"tool": "git_status"},
  {"tool": "file_read",  "args": {"path": "...", "start_line": 1, "end_line": 80}},
  {"tool": "file_replace", "args": {"path": "...", "old": "...", "new": "..."}},
  {"tool": "git_diff"},
  {"tool": "git_commit", "args": {"message": "fix: ..."}}
]}
```

### Branch + PR
```json
{"type": "sequential", "steps": [
  {"tool": "git_branch", "args": {"name": "feature/xyz"}},
  {"tool": "git_commit", "args": {"message": "feat: ..."}},
  {"tool": "git_push"},
  {"tool": "git_pr_create", "args": {"title": "feat: xyz", "body": "..."}}
]}
```

### Diff and summarise
```json
{"type": "sequential", "steps": [
  {"tool": "git_status", "store_result_as": "$status"},
  {"tool": "git_diff",   "store_result_as": "$diff"},
  {"tool": "llm_summarise",
   "args": {"prompt": "Describe these changes clearly.",
            "context": {"status": "$status", "diff": "$diff"}},
   "store_result_as": "$summary"}
]}
```

### Full feature flow — branch → commit → push → PR → merge → rebuild
```json
{"type": "sequential", "steps": [
  {"tool": "git_checkout",
   "args": {"branch": "chika/ui-update", "create": true,
            "working_directory": "$profile.workspace"},
   "description": "Create a feature branch"},
  {"tool": "git_commit",
   "args": {"message": "feat: update UI styles",
            "working_directory": "$profile.workspace"},
   "description": "Commit the changes"},
  {"tool": "git_push",
   "args": {"working_directory": "$profile.workspace"},
   "description": "Push branch to GitHub"},
  {"tool": "git_pr_create",
   "args": {"title": "Update UI styles", "body": "...",
            "working_directory": "$profile.workspace"},
   "description": "Open a Pull Request"},
  {"tool": "git_pr_merge",
   "args": {"method": "squash",
            "working_directory": "$profile.workspace"},
   "description": "Merge into main"},
  {"tool": "shell_exec",
   "args": {"command": "git pull origin main",
            "working_directory": "$profile.workspace"},
   "description": "Sync the local main with the merged change"}
]}
```

## Anti-patterns

- Force-push to `main` / `master` without explicit user authorisation.
- `--no-verify` to skip pre-commit hooks. If a hook fails, fix the underlying issue.
- Amending pushed commits — create a new commit instead.
- Committing files like `.env`, credentials, or large binaries.

---

<!-- chika:tool-reference:auto-start -->

<!-- This block is auto-generated from the live tool registry by
     scripts/sync_skill_docs.py. Don't hand-edit between the
     start/end markers — your changes will be overwritten.    -->

## Tool reference

_10 tools registered with the `git` skill._

### `git_branch`

List all branches (local and remote).

**Args**:

- `working_directory` (string, optional)

### `git_checkout`

Checkout an existing branch or create a new one (create=true).

**Args**:

- `branch` (string, **required**) — Branch name
- `create` (boolean, optional) — True = create new branch
- `working_directory` (string, optional)

### `git_commit` · **requires approval**

Stage all changes (git add -A) and commit with the given message.

**Args**:

- `message` (string, **required**)
- `working_directory` (string, optional)

### `git_diff`

Get diff of uncommitted changes.

**Args**:

- `path` (string, optional)
- `working_directory` (string, optional)

### `git_log`

Get recent commit log (one-line format).

**Args**:

- `n` (integer, optional)
- `working_directory` (string, optional)

### `git_pr_create` · **requires approval**

Create a GitHub Pull Request using the gh CLI. Requires gh to be authenticated.

**Args**:

- `title` (string, **required**)
- `body` (string, optional)
- `base` (string, optional) — Target branch (default: main)
- `working_directory` (string, optional)

### `git_pr_merge` · **requires approval**

Merge the current branch's open PR using the gh CLI.

**Args**:

- `method` (string, optional) — squash | merge | rebase (default: squash)
- `delete_branch` (boolean, optional) — Delete branch after merge (default: true)
- `working_directory` (string, optional)

### `git_pull` · **requires approval**

Pull latest changes from a remote branch.

**Args**:

- `remote` (string, optional)
- `branch` (string, optional)
- `working_directory` (string, optional)

### `git_push` · **requires approval**

Push a branch to a remote. Defaults to 'git push origin HEAD'.

**Args**:

- `remote` (string, optional) — Remote name (default: origin)
- `branch` (string, optional) — Branch to push (default: HEAD)
- `working_directory` (string, optional)

### `git_status`

Get git status of a repo (branch + changed files).

**Args**:

- `working_directory` (string, optional) — Repo path (default .)

<!-- chika:tool-reference:auto-end -->

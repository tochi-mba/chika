# shell_skill

Run shell commands and manage background processes. Five tools, one
shared registry, one dynamic prompt section that always tells you what
you have running.

## When to use

- Build / install / lint / test commands.
- Launching servers, watch processes, anything long-running.
- File operations that file_tools can't do (chmod, ln -s, rsync, …).
- Querying tool output (git, npm, pip).

For Python scripts the user wants to RUN, prefer `python_run` over
`shell_exec("python …")` — `python_run` has the import-fallback chain
(`pygame → pygame-ce`, `cv2 → opencv-python`, `PIL → Pillow`) and
spawns with the right console flags on Windows. **Never `shell_exec
("python -m pip install …")` to fix a missing import** — that
bypasses python_run's fallback table and dumps the user into manual
remediation.

## Foreground vs background

- `wait_for_completion=true` (default): blocks, returns
  `stdout / stderr / exit_code`. Best for short commands.
- `wait_for_completion=false`: returns a `pid` immediately, the process
  keeps running. Use for servers, watch jobs, long compiles. Then:
  - `shell_get_output(pid)` — reads buffered stdout/stderr.
  - `shell_wait(pid, timeout_seconds)` — blocks until exit.
  - `shell_kill(pid)` — terminates a runaway.
  - `shell_list_processes()` — current registry snapshot.

The dynamic prompt section the skill contributes lists every running
process every turn — you don't need to call `shell_list_processes`
just to remember what you spawned.

## Working directory

Pass `working_directory` (alias `cwd`). The runtime validates the
path up front; an invalid dir returns a structured error rather than
crashing the subprocess. When omitted, the command runs in the active
profile's workspace.

## Workspace gating

File-mutating shell commands are subject to the same workspace policy
as `file_write` — paths outside the active profile's workspace require
user approval (session / once / deny). This is enforced inside the
file_tools layer; raw `shell_exec` doesn't run path checks itself, so
malicious commands can still read outside the workspace. Don't write
shell commands that touch arbitrary paths without first asking the
user via natural-language confirmation.

## Patterns

### Foreground build

```json
{"type": "sequential", "steps": [
  {"tool": "shell_exec",
   "args": {"command": "npm run build", "working_directory": "$proj.path"},
   "store_result_as": "$build"}
]}
```

### Background server

```json
{"type": "sequential", "steps": [
  {"tool": "shell_exec",
   "args": {
     "command": "python -m http.server 4173",
     "wait_for_completion": false,
     "working_directory": "$proj.path"
   },
   "store_result_as": "$server"}
]}
```

Then poll with `shell_get_output($server.pid)` or kill with
`shell_kill($server.pid)`.

### Tail a long-running job

```json
{"type": "sequential", "steps": [
  {"tool": "shell_get_output", "args": {"pid": 12345}}
]}
```

## Anti-patterns

- Don't fire `shell_exec` then immediately `shell_kill` — use
  `wait_for_completion=true` instead.
- Don't poll-loop `shell_get_output` in a tight loop. Sleep / wait.
- Don't use `shell_exec` as a workaround for tool gaps. If `git` /
  `browser` / `web` actions are involved, use the corresponding skill.
- Don't write commands that depend on shell features the platform
  doesn't have. `find -name` works on POSIX; on Windows use
  `Get-ChildItem -Filter` via PowerShell.

---

<!-- chika:tool-reference:auto-start -->

<!-- This block is auto-generated from the live tool registry by
     scripts/sync_skill_docs.py. Don't hand-edit between the
     start/end markers — your changes will be overwritten.    -->

## Tool reference

_5 tools registered with the `shell` skill._

### `shell_exec` · **requires approval**

Run a shell command. wait_for_completion=true (default): blocks and returns stdout/stderr/exit_code. wait_for_completion=false: fires in background, returns pid immediately — use shell_get_output(pid) to poll output, shell_wait(pid) to block until done.

**Args**:

- `command` (string, **required**) — Shell command to execute
- `timeout_seconds` (number, optional) — Max seconds to wait (default 30, only for wait_for_completion=true)
- `wait_for_completion` (boolean, optional) — false = fire and forget, returns pid immediately
- `working_directory` (string, optional) — Working directory for the command

### `shell_get_output`

Read buffered stdout/stderr from a background process started with shell_exec(wait_for_completion=false). Pass clear=true to drain the buffer.

**Args**:

- `pid` (integer, **required**) — Process ID returned by shell_exec
- `clear` (boolean, optional) — Clear the buffer after reading (default false)

### `shell_kill` · **requires approval**

Kill a background process by pid.

**Args**:

- `pid` (integer, **required**) — Process ID to kill

### `shell_list_processes`

List all tracked background shell processes and their running status.

*No parameters.*

### `shell_wait`

Wait for a background process to finish (up to timeout_seconds), then return its full output.

**Args**:

- `pid` (integer, **required**) — Process ID to wait for
- `timeout_seconds` (number, optional) — Max seconds to wait (default 60)

<!-- chika:tool-reference:auto-end -->

# Plan skill

For multi-step tasks. The plan lives in `$plan` and is rendered in the
frontend's Workflow tab.

## Tools

| Tool          | Purpose                                                |
|---------------|--------------------------------------------------------|
| `plan_set`    | Replace the plan with a fresh list of steps.           |
| `plan_update` | Mark a step as `done`, `in_progress`, or `failed`.     |
| `plan_get`    | Read the current `$plan` (also exposed as variable).   |

## When to plan

- **3+ steps** or **>1 file edit** → set a plan first.
- **Single fix** or **read-only inspection** → no plan needed.

## How to write a good plan

A plan is the contract you make with the user up-front. Be **verbose
where it helps**, **terse where it doesn't** — the goal is to stop
mid-job and re-read the plan and instantly understand what's being
built and why.

Required structure:

1. **`goal`** — a single sentence stating the aim of the whole job.
   Reads as a header for the user. Examples:
   - "Build a Powder Toy clone in the browser using vanilla JS + canvas."
   - "Refactor `shell_tool.py` so subprocesses are reliably killed on Windows."
2. **`requirements`** — explicit constraints the user has stated or
   that the work obviously demands. Anything in the user's prompt that
   would change the design if violated. Examples:
   - "Must work offline (no API calls)."
   - "Use TypeScript, not JS."
   - "Performance: 60fps on a 1000×1000 grid."
   - "Must compile on Python 3.14."
3. **`tasks`** — ordered top-level work. Each task can have
   **`subtasks`** for steps that decompose into smaller pieces. Sub-task
   status auto-rolls up — a parent is done when every leaf is done,
   in_progress when any leaf is in_progress.

Granularity rule: each LEAF should be ~5-30 minutes of work. Not so
fine you spend more time updating the plan than executing it; not so
coarse the user can't see what's happening. If a top-level task is
clearly multi-step (e.g. "implement the simulation engine"), it
probably wants `subtasks`. If it's a one-liner (e.g. "add .gitignore"),
keep it flat.

When you genuinely don't know which path to take and the choice
materially changes the plan, **call `ask_user`** (question_skill)
BEFORE planning — don't guess and waste 10 turns on the wrong shape.

## Verbose plan template

```json
{"tool": "plan_set", "args": {
  "goal": "Build a Powder Toy clone in the browser using vanilla JS + canvas.",
  "requirements": [
    "No build step — must run by opening index.html",
    "60fps on a 600x600 grid",
    "Five elements minimum: sand, water, fire, smoke, metal",
    "Click-to-paint UI with element palette"
  ],
  "tasks": [
    {"id": "t1", "text": "Project scaffold + canvas setup", "subtasks": [
      {"id": "t1.1", "text": "scaffold_web_app stack=vanilla"},
      {"id": "t1.2", "text": "Wire main.js to a 600x600 canvas with requestAnimationFrame"},
      {"id": "t1.3", "text": "Verify the loop renders by drawing a single test pixel"}
    ]},
    {"id": "t2", "text": "Element data model + palette", "subtasks": [
      {"id": "t2.1", "text": "Define elements.js with {id, color, density, state}"},
      {"id": "t2.2", "text": "Build a UI palette that sets the active element"},
      {"id": "t2.3", "text": "Click-to-paint into the grid"}
    ]},
    {"id": "t3", "text": "Particle simulation loop", "subtasks": [
      {"id": "t3.1", "text": "Iterate the grid bottom-up so falling sand doesn't double-process"},
      {"id": "t3.2", "text": "Sand: fall, displace water"},
      {"id": "t3.3", "text": "Water: fall + spread laterally"},
      {"id": "t3.4", "text": "Fire: rise, decay over N frames, light wood"},
      {"id": "t3.5", "text": "Smoke: rise faster than fire, decay"},
      {"id": "t3.6", "text": "Metal: static, conducts heat to neighbours"}
    ]},
    {"id": "t4", "text": "Polish + verify", "subtasks": [
      {"id": "t4.1", "text": "Performance pass: profile and aim for 60fps"},
      {"id": "t4.2", "text": "live_server and verify_url the URL"}
    ]}
  ]
}}
```

## Mark progress as you go

Canonical kwargs are `task_id` and `status`. Aliases (`id`, `task`,
`taskId` for task_id; `state`, `new_status` for status) are tolerated
but please use the canonical names so the SKILL.md and your call line
up.

```json
{"tool": "plan_update", "args": {"task_id": "t1.1", "status": "done"}}
```

Sub-task statuses **auto-roll up**: when every leaf under `t1` is done,
`t1` itself becomes `done`. When you mark a leaf done and nothing else
is in_progress, the next pending leaf auto-promotes to in_progress.

## When to ask the user vs just plan

**Ask** with `ask_user` (one round, multiple choice) when:

- The user's request maps to ≥2 reasonable architectures with materially
  different work plans (e.g. "make me a chat app" → WebSocket vs polling
  vs SSE; "build me a 3D thing" → Three.js vs Babylon vs raw WebGL).
- A constraint they implied is ambiguous and getting it wrong costs ≥3
  re-plans (e.g. "needs auth" — Google OAuth? Email-link? Clerk?).

**Just plan** when:

- The shape is obvious from the prompt ("make me a tic-tac-toe").
- The user has been specific ("vanilla JS, canvas, no deps").
- The reasonable default is right >70% of the time and re-planning if
  wrong is cheap.

---

<!-- chika:tool-reference:auto-start -->

<!-- This block is auto-generated from the live tool registry by
     scripts/sync_skill_docs.py. Don't hand-edit between the
     start/end markers — your changes will be overwritten.    -->

## Tool reference

_9 tools registered with the `plan` skill._

### `plan_add`

Append tasks to the active plan WITHOUT replacing it. Use when you discover new work mid-job. Optional `after_id` inserts the new tasks immediately after a specific existing task id.

**Args**:

- `tasks` (array, **required**) — New tasks to add (strings or {id, text, status} dicts).
- `after_id` (string, optional) — Optional: insert after this task id; default is append at end.

### `plan_archive`

Retire the current plan to ``$plan_archive`` (a per-session list of past plans). The active ``$plan`` becomes empty so the system prompt + UI panels go blank — fresh slate for the next job. Past plans are kept; use plan_history to see them. Also writes a one-line summary to the profile memory so future sessions recall what was attempted. Use this when you've shipped a plan in full, or when the user explicitly pivots and the old plan is dead. Optional ``reason`` is preserved alongside the archive entry.

**Args**:

- `reason` (string, optional) — Why this plan is being archived ('shipped', 'abandoned', 'superseded').

### `plan_edit`

Apply a list of structured patches to the active plan in one call (set_goal, set/add/remove_requirement, set_task_text, set_task_status, add_task, add_subtask, remove_task, replace_in_field, replace_in_task). Use this when the user asks for a tweak ("swap WebAssembly for WebGPU", "add a 'must work offline' requirement", "insert a UI polish task after t3") instead of rewriting the whole plan with plan_set — surgical edits preserve task ids and progress. Each op is applied in order; failures don't block the rest. See plan SKILL.md for the full op reference.

**Args**:

- `operations` (array, **required**) — Ordered list of {op, ...} patches. Each op has its own required keys — see SKILL.md.

### `plan_get`

Return the current plan. Useful mid-workflow to remember where you are.

*No parameters.*

### `plan_history`

Return the list of past archived plans for this session, newest first. Use to reference what was attempted before without re-activating the plan. Default ``limit`` is 5 — pass higher for deeper history.

**Args**:

- `limit` (integer, optional) — Max archived plans to return (default 5).

### `plan_reconcile`

Refresh the plan against the latest conversation context. Runs an internal LLM call that compares the current goal + requirements + tasks against the recent chat tail and applies any plan_edit operations needed to bring stale tasks/requirements back in line with the goal. Use this right after the user pivots direction (e.g. 'switch to Three.js racing'); the agent should call plan_reconcile after plan_edit(set_goal=...) so tasks don't drift. Returns {applied, ops, reasoning, plan}; reasoning is the LLM's one-sentence justification. If nothing needs changing it returns applied=0 and ops=[].

**Args**:

- `chat_excerpt` (string, optional) — Optional chat snippet to consult. When empty the engine samples the recent history tail.
- `max_ops` (integer, optional) — Cap on operations the reconcile pass may propose in one call. Default 12.

### `plan_remove`

Drop one or more tasks from the plan. Pass a task id string or a list. Use this to clear out completed work from the visible queue, or to cancel tasks the user no longer wants.

**Args**:

- `task_ids` (any, **required**) — Single task id or list of ids to remove.

### `plan_set`

Set the task plan at the start of any multi-step job. Verbose by design: include `goal` (one-sentence aim), `requirements` (the user's must-haves), and `tasks` (ordered list, each optionally with `subtasks` for nested work). Sub-task statuses auto-roll up — a parent is done iff every leaf is done. The first pending leaf is auto-marked in_progress. Use plan_update to track progress; plan_add to insert work mid-job; plan_remove to drop completed-and-shipped items. See plan SKILL.md for the verbose template.

**Args**:

- `goal` (string, optional) — One-sentence aim of the whole job (e.g. 'Build a powder-toy clone in vanilla JS').
- `requirements` (array, optional) — Explicit constraints / must-haves stated by the user or obvious from the work (e.g. 'must run offline').
- `tasks` (array, **required**) — Ordered top-level tasks. Strings become pending tasks; objects {id, text, status, subtasks} allow explicit control. Each task may include a `subtasks` list of the same shape — sub-statuses auto-roll up.

### `plan_update`

Mark a task's status. Use as you finish each one — 'pending' | 'in_progress' | 'done'. When you mark a task 'done' the next pending task auto-promotes to 'in_progress'. Pass 'text' to rewrite the task description if scope changed.

**Args**:

- `task_id` (string, **required**) — ID of the task to update (e.g. 't1', 't2', ...)
- `status` (string, **required**)
- `text` (string, optional) — Optional: rewrite the task description

<!-- chika:tool-reference:auto-end -->

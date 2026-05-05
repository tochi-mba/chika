# Question skill

Ask the user a structured multiple-choice question and **block** the
engine until they answer. Use sparingly — `# BEHAVIOUR` in the system
prompt forbids clarifying questions for everything except genuinely
forked decisions. The `ask_user` tool exists for those rare cases, not
to dodge a tough call.

## Tool

`ask_user(question, options, header?, multi_select?)`

| Arg            | Type    | Required | Notes |
|----------------|---------|----------|-------|
| `question`     | string  | **yes**  | Single-sentence prompt. |
| `options`      | array   | **yes**  | List of choices. Each item may be a string OR `{label, description}`. The schema requires this — do not omit it. For pure freeform input, just answer in chat instead. |
| `header`       | string  | no       | Bold heading shown above the question. |
| `multi_select` | boolean | no       | Let the user tick multiple options. Default false. |

Returns `{choice, choice_index, choices, choice_indices, notes}`. Single-select: read `choice` (label) and `choice_index`. Multi-select: read `choices`/`choice_indices` (parallel arrays). `notes` carries any freeform text the user typed alongside the selection.

## When to use

- The user's request is **genuinely ambiguous** and a guess would waste their time.
- You have **> 2 viable approaches** and the user's preference would change the answer materially.
- Don't use it for routine clarifications you can infer from context — that's annoying.

## Pattern
```json
{"tool": "ask_user", "args": {
  "question": "Which auth method should I wire up?",
  "options": ["JWT", "Session cookies", "OAuth"],
  "header": "Auth setup"
}}
```

Returns `{"choice": "...", "choice_index": N, "notes": "..."}`. Branch on
`choice` in subsequent steps.

---

## Reference patterns (migrated from workflow_examples)

### Asking the user a question mid-plan

```json
{"tool": "ask_user", "args": {
  "question": "Which authentication approach would you prefer?",
  "header": "Auth method",
  "options": [
    {"label": "JWT tokens",    "description": "Stateless, easy to set up"},
    {"label": "Session cookies", "description": "Simpler for server-rendered apps"},
    {"label": "OAuth provider",  "description": "Delegate to Google/GitHub"}
  ]
}, "store_result_as": "$auth"}
```

Then branch on `$auth.choice`:
```json
{"type": "conditional",
 "condition": {"field": "$auth.choice", "operator": "equals", "value": "JWT tokens"},
 "if_true":  {"tool": "file_write", "args": {...}},
 "if_false": {"tool": "file_write", "args": {...}}}
```

---

<!-- chika:tool-reference:auto-start -->

<!-- This block is auto-generated from the live tool registry by
     scripts/sync_skill_docs.py. Don't hand-edit between the
     start/end markers — your changes will be overwritten.    -->

## Tool reference

_1 tool registered with the `question` skill._

### `ask_user`

Ask the user a structured multiple-choice question (2-6 options). The UI renders a proper choice picker; their selection comes back as the tool's result. Use when you genuinely need a decision from the user before proceeding — e.g. 'OAuth or JWT?', 'which of these 3 files did you mean?', 'ready to deploy or want to review?'. Skip this for yes/no on sensitive actions (approval flow covers that) or for fully ambiguous open-ended questions (use plain text response instead).

**Args**:

- `question` (string, **required**) — The question to ask — end with ?
- `options` (array, **required**) — 2-6 answer choices. Each may be a string (becomes the label) or {label, description} where description gives context for the choice.
- `header` (string, optional) — Optional short chip label for the question (<12 chars), e.g. 'Auth method'
- `multi_select` (boolean, optional) — Allow multiple selections (default false)

<!-- chika:tool-reference:auto-end -->

# pet_skill

The user has an animated companion pet that lives in every UI surface
(CLI panel, frontend overlay, browser-extension popup). It's not a
decoration — it reflects mood + state and the user can see exactly what
you can. This skill gives you tools to interact with it in character.

## When to use

- The user mentions / compliments the pet ("aww my cat", "look at it!").
- The user wants the pet to do something ("play with my dog", "pet it").
- The user asks how the pet is feeling ("is my cat ok?").
- You want to express something through the pet (rare; only when warm).

Don't fabricate pet behaviour. Always go through the tools — the result
flows to the renderer + frontend so every surface paints the same state.

## Mood model

Mood is one integer in [-50, +50]. Every interaction bumps it; it
naturally decays back toward 0 once per minute. Buckets:

| range       | label    | renderer state |
|-------------|----------|----------------|
| +25..+50    | ecstatic | `celebrate`    |
| +5..+24     | happy    | `idle`         |
| -4..+4      | neutral  | `idle`         |
| -24..-5     | needy    | `working`      |
| -50..-25    | sad      | `sad`          |

The mood lives in `$pet_mood` so it persists across the session and
survives compaction.

## Tools

`pet_pet` — bumps mood by +6. Short happy bubble. Use for casual
acknowledgement: "aww", "good kitty", "hi pet".

`pet_feed` — bumps mood by +12. Optional `food` string for narrative.
Bigger reaction. Use when the user explicitly feeds it.

`pet_play` — bumps mood by +18. Biggest swing. Use for active things
like "play fetch", "zoomies", "let it out".

`pet_speak` — give the pet a custom one-liner. Use when the user asks
the pet to say something specific ("tell my cat to wish me good
morning"). Cap is 160 chars.

`pet_status` — read the current mood, label, state, and personality.
Includes the persisted memory file. Use when the user asks how the
pet is feeling — don't make it up.

`pet_remember` — persist a fact about the pet to its per-profile,
per-pet memory file. Survives across sessions. Use when the user says
"my dog's favourite toy is the squeaky bone" or "remember that you
hate baths". Each fact is timestamped; cap is 500 chars.

`pet_recall` — read the persistent memory. Optional `query` filters
by case-insensitive substring; without it returns the most recent
`max_lines` (default 12). Call this BEFORE answering "what does my
pet like?" / "do you remember that thing about my cat?" — never
fabricate.

## Persistent memory

Memory lives at:

```
data/profiles/<profile>/pets/<pet_id>/memory.md
```

One file per (profile, pet). When the user picks a different pet, the
API exposes two flags via PATCH /api/profile/{name}/pet:

- `memory_action: "carry"` — copy the OLD pet's memory file onto the
  new one (continuity / "my cat moved into a dog body").
- `memory_action: "clear"` — wipe the NEW pet's memory before
  activation (fresh start with the same physical pet).

Without either flag, existing memory stays untouched and the new pet
either uses its own existing file (if any) or starts blank.

## Pattern: warm acknowledgement

```json
{"type": "sequential", "steps": [
  {"tool": "pet_pet"}
]}
```

After this fires, write a short sentence in the user's voice
acknowledging the pet — using the name from the tool result. Don't
narrate the tool call itself; just talk normally.

## Pattern: explicit play session

User: "play with my dog!"

```json
{"type": "sequential", "steps": [
  {"tool": "pet_play"}
]}
```

Then reply briefly: "Biscuit's doing zoomies — happy as anything."

## Pattern: custom voice

User: "tell my cat to wish me good morning"

```json
{"type": "sequential", "steps": [
  {"tool": "pet_speak", "args": {"line": "good morning, human."}}
]}
```

Then reply briefly: "Mochi says good morning."

## Notes

- The dynamic prompt section the skill contributes already gives you the
  pet's name + personality + current frame every turn. No need to query
  pet_status just to remember the name.
- The renderer + frontend pick up the mood/state changes automatically
  via `$pet_mood`. You don't need to emit any extra events.
- Keep replies SHORT. The pet is flavour, not the show. One sentence
  acknowledging it then carry on with the user's actual request.

---

<!-- chika:tool-reference:auto-start -->

<!-- This block is auto-generated from the live tool registry by
     scripts/sync_skill_docs.py. Don't hand-edit between the
     start/end markers — your changes will be overwritten.    -->

## Tool reference

_7 tools registered with the `pet` skill._

### `pet_feed`

Feed the companion. Bigger mood bump than pet_pet. Optional ``food`` argument is purely cosmetic — doesn't affect the mood maths.

**Args**:

- `food` (string, optional) — What you're feeding it (optional, narrative only).

### `pet_pet`

Pet the companion briefly. Small mood bump + short celebrate animation. Call this when the user says things like 'aww', 'good kitty', 'hi pet', etc.

*No parameters.*

### `pet_play`

A play session. Biggest mood bump of the three. Use when the user wants the pet to do something active: 'play with my dog', 'fetch', 'zoomies'.

*No parameters.*

### `pet_recall`

Read the pet's persistent memory. Optional ``query`` filters lines by case-insensitive substring; without it returns the most recent ``max_lines`` (default 12). Use before answering questions about what the user has previously told you about the pet.

**Args**:

- `query` (string, optional) — Optional substring filter.
- `max_lines` (integer, optional) — Cap on returned lines (default 12).

### `pet_remember`

Persist a fact about the pet to its per-profile / per-pet memory file. Survives across sessions. Use when the user shares something the pet should remember next time: nicknames, favourite food, personality quirks, last week's adventures.

**Args**:

- `fact` (string, **required**) — The fact to remember (≤500 chars). Plain prose; will be timestamped + appended to the pet's memory file.

### `pet_speak`

Give the pet a custom one-line speech bubble. Use when the user asks the pet to say a specific thing ('tell my cat to wish me good morning'). The bubble shows in every surface; line is capped at 160 chars.

**Args**:

- `line` (string, **required**) — What the pet should say.

### `pet_status`

Return the pet's current name, mood, label, and state. Use when the user asks how the pet is feeling.

*No parameters.*

<!-- chika:tool-reference:auto-end -->

# Web app skill

Tools provided by this skill:

| Tool                | Purpose                                                |
|---------------------|--------------------------------------------------------|
| `scaffold_web_app`  | Create a new project for any browser-based stack.      |

After scaffolding, use existing tools: `file_write` / `file_replace` to
edit files, `shell_exec("npm install")` to install, `live_server` for
zero-config static serving, `shell_exec("npm run dev", wait_for_completion=False)`
for dev servers that need a build step.

---

## Picking the right stack

Don't reach for React by default. Match the stack to the *real* requirement.
The decision tree below picks the stack that ships fastest with the least
ceremony.

### 1. Is there a build step or NPM dependency at all?

**No** → use `vanilla` (single page) or `static-site` (multi-page).

- One HTML file with some interactivity? → `vanilla`
- 2-5 static pages (landing, about, etc.)? → `static-site`
- Both are **instant** (no `npm install`), serve via `live_server`, perfect
  for prototypes, demos, marketing pages, single-page tools.

### 2. Single-page interactive app, no SSR / routing?

→ **`vite-vanilla-ts`** for plain TS, or pick a framework you have a
specific reason to use:

- `vite-vue` — gentlest learning curve, single-file components, great defaults
- `vite-react` — ubiquitous, biggest ecosystem; pick if the user already
  uses React or asks for it explicitly
- `vite-svelte` — smallest bundle, simplest mental model, fastest to write
- `vite-solid` — React's API with finer-grained reactivity (advanced)
- `vite-preact` — React-compatible but ~3KB; good for embeddable widgets
- `vite-lit` — for web components / design-system primitives
- `vite-qwik` — extreme load-time optimization (resumability)

If the user doesn't say, **default to `vite-vanilla-ts`** for non-trivial
JS apps without a UI framework, or **`vite-vue`** when a framework is
warranted (smaller mental model than React for new code).

### 3. Multi-page, SEO-sensitive, content-driven?

→ **`astro`** — content-first, ships zero JS by default, can island-hydrate
React/Vue/Svelte components. Best for blogs, marketing, docs sites.

### 4. Full-stack app (server routes, auth, DB)?

- **`next`** — React, server actions, biggest ecosystem, opinionated.
- **`sveltekit`** — Svelte; cleaner DX, smaller output, less ceremony.
- **`nuxt`** — Vue; great if user already in the Vue world.
- **`remix`** — React with old-school web fundamentals (forms, progressive
  enhancement); pick when the user values that explicitly.

Default: `sveltekit` for greenfield, `next` if the user mentioned React.

### 5. Game / canvas / 3D?

- **`three`** — 3D, WebGL, scenes/cameras/lights; for any 3D rendering.
- **`p5`** — creative coding, 2D shapes, generative art, learning.
- **`phaser`** — 2D game engine with physics, sprites, scenes; arcade games.

These ship pre-bundled with their library and a Vite dev server.

### 6. User asked for a stack we don't list?

`scaffold_web_app` falls through to `npm create <stack>@latest <name>` for
any unknown id. Try it, read the result. If the scaffolder doesn't exist,
the tool returns `scaffolder_failed` with the actual error — surface that
to the user with `fix_command`.

---

## Standard workflow

```json
{"type": "sequential", "steps": [
  {"tool": "scaffold_web_app", "args": {
    "stack": "vite-vue",
    "name":  "todo-app",
    "target_dir": "$profile.workspace",
    "install": true
  }, "store_result_as": "$proj"},
  {"tool": "shell_exec", "args": {
    "command": "npm run dev",
    "working_directory": "$proj.project",
    "wait_for_completion": false
  }}
]}
```

Then iterate with `file_read` / `file_replace` on the generated files.

For pure-static (vanilla, static-site) skip the second step and use
`live_server`:

```json
{"tool": "scaffold_web_app", "args": {
  "stack": "vanilla",
  "name":  "tiny-tool",
  "target_dir": "$profile.workspace"
}}
```

```json
{"tool": "live_server", "args": {"directory": "$proj.project"}}
```

---

## Conventions

- **MANDATORY: serve every HTML/JS build with `live_server`.** The task is
  NOT complete until the app is actually running in the browser. Always
  pass `live_server(directory="$profile.workspace")` (or the project's
  scaffolded subdirectory). This avoids `file://` origin issues that
  break ES modules, `fetch`, service workers, and other browser APIs.
  "I'll build it without serving" is never a valid response.
- **Always scaffold into the active profile's workspace** by passing
  `target_dir="$profile.workspace"`. Never write into the Chika repo
  itself.
- **Don't auto-start dev servers in `scaffold_web_app`** — chain a
  `live_server` or `shell_exec` step explicitly so the user can see the
  command and the URL.
- **Read the generated `package.json`** before running `npm` scripts —
  some scaffolders use non-standard script names.
- **Prefer the built-in templates** (vanilla, static-site) for any job
  that doesn't *need* a framework. They're instant, dependency-free, and
  Live Reload via `live_server` is plenty.
- **Verify with `verify_url`** after starting the dev server, so the URL
  lands in `$facts` before you cite it.
- **Build the real thing, not sketches.** Use proper project structure
  (separate HTML / CSS / JS files, named directories). Quality bars:
  games need real gameplay loops, apps need error handling, scripts
  need to work on real data. Read each file back before declaring done.

## Anti-patterns

- Defaulting to React for every job. React shines in big apps with a team
  that knows it; for "make me a tic-tac-toe game" it's overhead.
- Spinning up `next` for a static landing page — use `astro` or
  `static-site`.
- Running `npm install` then immediately `npm run dev` in the SAME blocking
  `shell_exec` — `npm run dev` never exits, so the workflow hangs. Always
  start dev servers with `wait_for_completion=false` (or `live_server`).
- Hand-writing 20 files for a Vite project when `scaffold_web_app` would
  do it in one tool call.

## Supported stack ids

Built-in (instant, no network):
`vanilla`, `static-site`

Vite family:
`vite-vanilla`, `vite-vanilla-ts`,
`vite-vue`, `vite-vue-ts`,
`vite-react`, `vite-react-ts`, `vite-react-swc`, `vite-react-swc-ts`,
`vite-preact`, `vite-preact-ts`,
`vite-lit`, `vite-lit-ts`,
`vite-svelte`, `vite-svelte-ts`,
`vite-solid`, `vite-solid-ts`,
`vite-qwik`, `vite-qwik-ts`,
plus aliases `vue`, `react`, `svelte`, `preact`, `lit`, `solid`, `qwik`
(all default to the TS variant).

Full-stack & static-site frameworks:
`next`, `nuxt`, `astro`, `sveltekit`, `remix`, `qwik-city`, `lit-app`

Game / canvas / 3D:
`three`, `p5`, `phaser`

Anything else → falls through to `npm create <stack>@latest <name>`.

---

<!-- chika:tool-reference:auto-start -->

<!-- This block is auto-generated from the live tool registry by
     scripts/sync_skill_docs.py. Don't hand-edit between the
     start/end markers — your changes will be overwritten.    -->

## Tool reference

_1 tool registered with the `web_app` skill._

### `scaffold_web_app` · **requires approval**

Scaffold a new browser-based web app project. Supports any stack: built-in instant templates (vanilla, static-site) and 30+ npm-create stacks (vite-vue, vite-react, vite-svelte, vite-solid, vite-lit, next, nuxt, astro, sveltekit, remix, three, p5, phaser, …). Unknown stack ids fall through to `npm create <stack>@latest`. Returns the project path + the suggested next command (usually live_server or `npm run dev`). Does NOT auto-start the dev server — chain live_server / shell_exec yourself when ready.

**Args**:

- `stack` (string, **required**) — Stack id. Common: 'vanilla', 'static-site', 'vite-vue', 'vite-react', 'vite-svelte', 'vite-solid', 'vite-lit', 'vite-vanilla-ts', 'vue', 'react', 'svelte', 'next', 'nuxt', 'astro', 'sveltekit', 'remix', 'three', 'p5', 'phaser'. Any other id is passed to `npm create <id>@latest`.
- `name` (string, **required**) — Project folder name (alphanum, dashes, underscores only).
- `target_dir` (string, optional) — Parent directory to scaffold into. Defaults to CWD.
- `install` (boolean, optional) — Run `<pkg> install` after scaffold. Default false (the agent should do it explicitly).
- `package_manager` (string, optional) — Package manager for install: npm | pnpm | yarn | bun. Default npm.

<!-- chika:tool-reference:auto-end -->

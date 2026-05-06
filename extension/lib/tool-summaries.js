/**
 * Per-tool compact result formatters — JS port of
 * chika/_cli/tool_summaries.py (canonical version is the Python file).
 *
 * Each formatter takes a tool's result object and returns a SHORT,
 * human-friendly summary string (≤120 chars) describing what happened.
 * The frontend uses these in ToolEventRow.vue's collapsed row; the
 * extension popup uses them in its tool-row strip.
 *
 * Pattern:
 *
 *     summarise(tool, result) -> string | null
 *
 * Returning null = caller falls back to JSON.stringify(result).
 *
 * Parity rule: when a formatter is added/changed in the Python source
 * of truth, mirror it here AND in extension/lib/tool-summaries.js.
 * See ADR-29 (per-tool result rendering across surfaces).
 */

function short(s, n = 60) {
  if (s == null) return ''
  const text = String(s).replace(/\n/g, ' ').trim()
  return text.length <= n ? text : text.slice(0, n - 1) + '…'
}

const isObj = (v) => v != null && typeof v === 'object' && !Array.isArray(v)

// ── File ──────────────────────────────────────────────────────────────
function fileRead(r) {
  if (!isObj(r)) return null
  const path = r.path || ''
  const lineCount = r.line_count
  const total = r.total_lines
  const size = r.size_bytes
  const content = r.content
  const suffix = path ? ` · ${path}` : ''
  if (lineCount != null && total != null && lineCount !== total) {
    return `read ${lineCount}/${total} lines${suffix}`
  }
  if (total != null) return `read ${total} lines${suffix}`
  if (size != null) return `${size}B${suffix}`
  if (typeof content === 'string') {
    const n = content ? content.split('\n').length : 0
    return `read ${n} line${n !== 1 ? 's' : ''}${suffix}`
  }
  return null
}

function fileWrite(r) {
  if (!isObj(r)) return null
  const path = r.path || '?'
  const size = r.size_bytes ?? r.bytes_written ?? r.bytes
  if (size != null) return `wrote ${size}B → ${path}`
  if (r.ok || path !== '?') return `wrote → ${path}`
  return null
}

function fileEditLines(r) {
  if (!isObj(r)) return null
  const n = r.lines_replaced
  const total = r.total_lines
  if (n != null && total != null) return `replaced ${n} lines · ${total} lines total`
  return null
}

function fileReplace(r) {
  if (!isObj(r)) return null
  if (r.replaced && r.path) return `replaced 1 occurrence · ${r.path}`
  return null
}

function fileAppend(r) {
  if (!isObj(r)) return null
  const bytes = r.appended_bytes
  const path = r.path || '?'
  if (bytes != null) return `appended ${bytes}B → ${path}`
  return null
}

function fileInfo(r) {
  if (!isObj(r)) return null
  const path = r.path || '?'
  if (r.is_dir) return `directory · ${path}`
  const size = r.size_bytes
  const ext = r.extension || ''
  if (size != null) return `${size}B · ${ext} · ${path}`
  return null
}

// ── Shell ─────────────────────────────────────────────────────────────
function shellExec(r) {
  if (!isObj(r)) return null
  const code = r.exit_code ?? r.returncode
  const pid = r.pid
  const stdout = (r.stdout || '').trim()
  if (pid && r.background) return `started · pid ${pid}`
  if (code != null) {
    const tail = stdout ? short(stdout, 50) : ''
    return tail ? `exit ${code} · ${tail}` : `exit ${code}`
  }
  return null
}

function shellGetOutput(r) {
  if (!isObj(r)) return null
  const out = r.stdout
  if (typeof out === 'string') {
    const lines = out.split('\n').length - (out.endsWith('\n') ? 1 : 0) || (out ? 1 : 0)
    const pid = r.pid
    return pid ? `pid ${pid} · ${lines} line${lines !== 1 ? 's' : ''}`
               : `${lines} line${lines !== 1 ? 's' : ''}`
  }
  return null
}

function shellKill(r) {
  if (!isObj(r)) return null
  const pid = r.pid
  if (r.killed || r.ok) return `killed pid ${pid}`
  return null
}

// ── Web ───────────────────────────────────────────────────────────────
function webFetch(r) {
  if (!isObj(r)) return null
  const status = r.status ?? r.status_code
  const url = r.url || ''
  const bytes = r.bytes ?? r.size_bytes
  const parts = []
  if (status != null) parts.push(`${status}`)
  if (bytes != null) parts.push(`${bytes}B`)
  if (url) parts.push(short(url, 60))
  return parts.length ? parts.join(' · ') : null
}

function webSearch(r) {
  if (!isObj(r)) return null
  const results = r.results || []
  const query = r.query || ''
  const n = Array.isArray(results) ? results.length : 0
  return query ? `${n} results · '${short(query, 50)}'` : `${n} results`
}

function webHead(r) {
  if (!isObj(r)) return null
  const status = r.status ?? r.status_code
  const url = r.url || ''
  if (status != null) return `${status} · ${short(url, 60)}`
  return null
}

function verifyUrl(r) {
  if (!isObj(r)) return null
  if (r.ok || r.verified) return `verified · ${short(r.url || '', 60)}`
  return null
}

// ── Browser ───────────────────────────────────────────────────────────
function browserScreenshot(r) {
  if (!isObj(r)) return null
  const w = r.width, h = r.height
  if (w && h) return `screenshot · ${w}×${h}`
  return null
}

function browserNavigate(r) {
  if (!isObj(r)) return null
  if (r.url) return `navigated · ${short(r.url, 60)}`
  return null
}

function browserGetText(r) {
  if (!isObj(r)) return null
  const chars = r.char_count
  const title = r.title || ''
  if (chars != null && title) return `${chars} chars · ${short(title, 50)}`
  if (chars != null) return `${chars} chars`
  return null
}

function browserGetDom(r) {
  if (!isObj(r)) return null
  const chars = r.char_count ?? (r.html || '').length
  if (chars) return `${chars}B HTML`
  return null
}

function browserClick(r) {
  if (!isObj(r)) return null
  if (r.ok || r.clicked) return `clicked · ${short(r.selector || '', 60)}`
  return null
}

function browserFillInput(r) {
  if (!isObj(r)) return null
  if (r.ok || r.filled) return `filled · ${short(r.selector || '', 60)}`
  return null
}

function browserGetPageVar(r) {
  if (!isObj(r)) return null
  const path = r.var_path || ''
  if (r.keys_preview) {
    const keys = r.keys_preview.slice(0, 5).map(String).join(', ')
    return `${path} → keys: ${keys}…`
  }
  if (r.bytes) return `${path} · ${r.bytes}B`
  return null
}

function browserWatch(r) {
  if (!isObj(r)) return null
  if (r.watch_id) return `watching · ${short(r.selector || '', 50)}`
  return null
}

// ── Plan ──────────────────────────────────────────────────────────────
function planSet(r) {
  if (!isObj(r)) return null
  const n = r.count
  if (n != null) return `plan set · ${n} task${n !== 1 ? 's' : ''}`
  return null
}

function planUpdate(r) {
  if (!isObj(r)) return null
  const plan = r.plan || {}
  const tasks = plan.tasks || []
  const done = tasks.filter((t) => isObj(t) && t.status === 'done').length
  return `plan updated · ${done}/${tasks.length} done`
}

function planAdd(r) {
  if (!isObj(r)) return null
  const added = r.added || []
  if (added.length) return `+${added.length} task${added.length !== 1 ? 's' : ''}`
  return null
}

function planRemove(r) {
  if (!isObj(r)) return null
  const removed = r.removed || []
  if (removed.length) return `-${removed.length} task${removed.length !== 1 ? 's' : ''}`
  return null
}

function planArchive(r) {
  if (!isObj(r)) return null
  if (r.archived) return 'plan archived'
  return r.note || null
}

function planHistory(r) {
  if (!isObj(r)) return null
  const n = r.count
  if (n != null) return `${n} archived plan${n !== 1 ? 's' : ''}`
  return null
}

// ── Memory ────────────────────────────────────────────────────────────
function memoryPersist(r) {
  if (!isObj(r)) return null
  const name = r.name
  const text = r.text || r.content || r.body || ''
  if (name && text) return `remembered · ${name} → '${short(text, 60)}'`
  if (name) return `remembered · ${name}`
  if (text) return `remembered · '${short(text, 80)}'`
  if (r.saved || r.ok) return 'remembered'
  return null
}

function memoryRecall(r) {
  if (!isObj(r)) return null
  const items = r.memories || r.results || []
  const n = Array.isArray(items) ? items.length : 0
  return `recalled ${n} memor${n !== 1 ? 'ies' : 'y'}`
}

function memoryForget(r) {
  if (!isObj(r)) return null
  if (r.forgotten || r.ok) return 'forgot memory'
  return null
}

// ── Git ───────────────────────────────────────────────────────────────
function gitStatus(r) {
  if (!isObj(r)) return null
  const branch = r.branch || '?'
  const dirty = r.dirty || r.modified || []
  const n = Array.isArray(dirty) ? dirty.length : 0
  return `branch ${branch} · ${n} change${n !== 1 ? 's' : ''}`
}

function gitLog(r) {
  if (!isObj(r)) return null
  const commits = r.commits || []
  const n = Array.isArray(commits) ? commits.length : 0
  return `${n} commit${n !== 1 ? 's' : ''}`
}

function gitCommit(r) {
  if (!isObj(r)) return null
  const sha = r.sha || r.hash || ''
  if (sha) return `committed ${String(sha).slice(0, 7)}`
  return null
}

function gitDiff(r) {
  if (!isObj(r)) return null
  const files = r.files_changed ?? r.files
  if (files != null) return `diff · ${files} file${files !== 1 ? 's' : ''}`
  return null
}

function gitPush(r) {
  if (!isObj(r)) return null
  if (r.pushed || r.ok) return `pushed · ${r.remote || 'origin'}/${r.branch || '?'}`
  return null
}

// ── Spotify / LLM / other ─────────────────────────────────────────────
function spotifySearch(r) {
  if (!isObj(r)) return null
  const tracks = r.tracks?.items || []
  if (tracks.length) return `${tracks.length} tracks`
  return null
}

function spotifyPlay(r) {
  if (!isObj(r)) return null
  if (r.ok) return '▶ playing'
  return null
}

function llmSummarise(r) {
  if (!isObj(r)) return null
  const summary = r.summary || r.text || ''
  if (summary) return `summary · '${short(summary, 80)}'`
  return null
}

function llmTransform(r) {
  if (!isObj(r)) return null
  const keys = Object.keys(r)
  if (keys.length) return `transformed · keys: ${keys.slice(0, 6).join(', ')}`
  return null
}

function pythonRun(r) {
  if (!isObj(r)) return null
  const code = r.exit_code ?? r.returncode
  const out = (r.stdout || '').trim()
  if (code != null) {
    return out ? `exit ${code} · ${short(out, 50)}` : `exit ${code}`
  }
  return null
}

function liveServer(r) {
  if (!isObj(r)) return null
  const port = r.port, pid = r.pid
  if (port && pid) return `localhost:${port} · pid ${pid}`
  return null
}

function scaffoldWebApp(r) {
  if (!isObj(r)) return null
  const files = r.files_created || r.files || []
  const n = Array.isArray(files) ? files.length : 0
  return `scaffolded · ${n} file${n !== 1 ? 's' : ''}`
}

// ── Registry ──────────────────────────────────────────────────────────
const FORMATTERS = {
  // File
  file_read:        fileRead,
  file_write:       fileWrite,
  file_edit_lines:  fileEditLines,
  file_replace:     fileReplace,
  file_append:      fileAppend,
  file_info:        fileInfo,
  // Shell
  shell_exec:       shellExec,
  shell_get_output: shellGetOutput,
  shell_kill:       shellKill,
  // Web
  web_fetch:        webFetch,
  web_search:       webSearch,
  web_head:         webHead,
  verify_url:       verifyUrl,
  // Browser
  browser_screenshot:    browserScreenshot,
  browser_navigate:      browserNavigate,
  browser_get_text:      browserGetText,
  browser_get_dom:       browserGetDom,
  browser_click:         browserClick,
  browser_fill_input:    browserFillInput,
  browser_get_page_var:  browserGetPageVar,
  browser_watch_element: browserWatch,
  // Plan
  plan_set:      planSet,
  plan_update:   planUpdate,
  plan_add:      planAdd,
  plan_remove:   planRemove,
  plan_archive:  planArchive,
  plan_history:  planHistory,
  // Memory
  memory_persist: memoryPersist,
  memory_recall:  memoryRecall,
  memory_forget:  memoryForget,
  // Git
  git_status: gitStatus,
  git_log:    gitLog,
  git_commit: gitCommit,
  git_diff:   gitDiff,
  git_push:   gitPush,
  // Spotify / LLM
  spotify_search: spotifySearch,
  spotify_play:   spotifyPlay,
  llm_summarise:  llmSummarise,
  llm_transform:  llmTransform,
  // Other
  python_run:        pythonRun,
  live_server:       liveServer,
  scaffold_web_app:  scaffoldWebApp,
}

/**
 * Return a short summary of `result` for the named tool, or null
 * if no formatter is registered (caller falls back to JSON dump).
 */
export function summarise(tool, result) {
  const fn = FORMATTERS[tool]
  if (!fn) return null
  try {
    return fn(result)
  } catch {
    // A formatter bug must never break tool-row rendering.
    return null
  }
}

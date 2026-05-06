<template>
  <!-- tool-block card for tool_call / tool_result -->
  <div
    v-if="isToolEvent"
    class="tool-block"
    :class="[
      categoryClass,
      {
        'is-pending': isPending,
        'is-error': isErrorResult,
        'is-success': isSuccessResult,
        'is-skill-load': isSkillLoad,
      }
    ]"
  >
    <div class="tool-head">
      <div class="tool-head-left">
        <div class="cat-icon" :title="categoryLabel">{{ categoryIcon }}</div>
        <div class="tool-name-wrap">
          <span class="tool-name">{{ toolName }}</span>
          <span v-if="skillBadge" class="skill-badge">{{ skillBadge }}</span>
        </div>
      </div>
      <div class="tool-head-right">
        <span class="status-pill" :class="dotStateClass">
          <template v-if="isPending">
            <span class="status-dot dot-pending" />
            <span class="status-word">Running</span>
          </template>
          <template v-else-if="isErrorResult">
            <svg class="status-glyph" width="11" height="11" viewBox="0 0 12 12" fill="none">
              <path d="M3 3L9 9M9 3L3 9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            <span class="status-word">Error</span>
          </template>
          <template v-else-if="isSuccessResult">
            <svg class="status-glyph" width="11" height="11" viewBox="0 0 12 12" fill="none">
              <path d="M2 6L5 9L10 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span class="status-word">Done</span>
          </template>
        </span>
        <span v-if="isPending && elapsedLabel" class="elapsed">{{ elapsedLabel }}</span>
        <span v-else-if="resultSummary" class="result-summary">{{ resultSummary }}</span>
      </div>
    </div>

    <div v-if="argPills.length" class="arg-pills">
      <div v-for="p in argPills" :key="p.key" class="arg-pill">
        <span class="arg-key">{{ p.key }}=</span>
        <span class="arg-val">{{ p.value }}</span>
      </div>
    </div>

    <details v-if="hasDetails" class="tool-details">
      <summary class="tool-details-toggle">{{ detailsLabel }}</summary>
      <pre class="tool-pre" :class="{ 'is-error-pre': isErrorResult }">{{ detailsContent }}</pre>
    </details>
  </div>

  <!-- Lightweight inline row for non-tool events (workflow/step/loop/etc) -->
  <div v-else class="row" :class="{ live }">
    <div class="row-icon">
      <span v-if="isDot" class="dot" :class="dotClass" />
      <span v-else class="glyph" :class="glyphColorClass">{{ glyph }}</span>
    </div>
    <div class="row-body">
      <div class="row-head">
        <span class="row-label">{{ label }}</span>
        <span v-if="subtext" class="row-sub">{{ subtext }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { summarise as summariseTool } from '../lib/toolSummaries.js'

const props = defineProps({
  event: { type: Object, required: true },
  live:  { type: Boolean, default: false },
})

const isToolEvent = computed(() =>
  props.event.type === 'tool_call' || props.event.type === 'tool_result'
)

const isPending = computed(() =>
  props.event.type === 'tool_call' && props.event.pending === true
)

const isErrorResult = computed(() =>
  props.event.type === 'tool_result' && !!props.event.error
)

const isSuccessResult = computed(() =>
  props.event.type === 'tool_result' && !props.event.error
)

const _now = ref(Date.now())
let _timer = null
onMounted(() => {
  if (!isPending.value) return
  _timer = setInterval(() => { _now.value = Date.now() }, 250)
})
onUnmounted(() => { if (_timer) clearInterval(_timer) })

const elapsedLabel = computed(() => {
  if (!isPending.value || !props.event._startedAt) return ''
  const ms = _now.value - props.event._startedAt
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60_000)
  const s = Math.floor((ms % 60_000) / 1000)
  return `${m}m ${String(s).padStart(2, '0')}s`
})

const isDot = computed(() =>
  props.event.type === 'step_start' || props.event.type === 'step_done'
)

const isSkillLoad = computed(() => {
  const e = props.event
  return (e.type === 'tool_call' && e.tool === 'skill_load')
      || (e.type === 'tool_result' && e.tool === 'skill_load')
})

const skillBadge = computed(() => {
  const e = props.event
  if (e.type === 'tool_call' && e.tool === 'skill_load') {
    return `→ ${e.args?.skill || '?'}`
  }
  if (e.type === 'tool_result' && e.tool === 'skill_load' && !e.error) {
    const r = e.result || {}
    const condensed = r.condensed ? 'condensed' : 'verbatim'
    const chars = typeof r.char_count === 'number'
      ? `${r.char_count.toLocaleString()} chars · `
      : ''
    return `${r.skill || '?'} · ${chars}${condensed}`
  }
  return null
})

const dotStateClass = computed(() => {
  if (isPending.value) return 'state-pending'
  if (isErrorResult.value) return 'state-error'
  if (isSuccessResult.value) return 'state-success'
  return 'state-neutral'
})

const dotClass = computed(() => ({
  'dot-live': props.live && props.event.type === 'step_start',
  'dot-done': props.event.type === 'step_done',
}))

const glyph = computed(() => {
  switch (props.event.type) {
    case 'workflow_start':         return '◫'
    case 'workflow_done':          return '⚑'
    case 'loop_iteration':         return '↺'
    case 'condition_eval':         return '⑂'
    case 'variable_set':           return '$'
    case 'browser_watch_trigger':  return '◎'
    default:                       return '·'
  }
})

const glyphColorClass = computed(() => {
  if (props.event.type === 'workflow_done') return 'is-success'
  return ''
})

const toolName = computed(() => {
  const e = props.event
  if (e.type === 'tool_call')   return e.tool || e.step_id || 'tool'
  if (e.type === 'tool_result') return e.tool || e.step_id || 'result'
  return ''
})

/**
 * Map a tool name → category. Mirrors api/settings_store.py::TOOL_CATEGORY_MAP
 * so a new tool inherits the right colour without a CSS edit. Falls through
 * to a neutral default for unknown tools.
 */
const categoryKey = computed(() => {
  const name = (toolName.value || '').toLowerCase()
  if (name.startsWith('shell_') || name === 'python_run' || name === 'bg_shell_exec' || name === 'shell_kill') return 'shell'
  if (name === 'file_write' || name === 'file_append' || name === 'file_create_dir' || name === 'file_delete') return 'file_write'
  if (name.startsWith('file_'))     return 'file_read'
  if (name === 'browser_click' || name === 'browser_fill_input' || name === 'browser_select_option' || name.startsWith('browser_set_') || name === 'browser_keypress') return 'browser_write'
  if (name.startsWith('browser_')) return 'browser_read'
  if (name.startsWith('memory_'))  return 'memory'
  if (name.startsWith('profile_')) return 'profile'
  if (name.startsWith('git_'))     return 'git'
  if (name === 'web_fetch' || name === 'web_search' || name === 'verify_url' || name === 'verify' || name === 'web_head') return 'network'
  return 'default'
})

const categoryClass = computed(() => `cat-${categoryKey.value}`)

const categoryIcon = computed(() => {
  const map = {
    shell: '>_',
    file_write: '+f',
    file_read: '=f',
    browser_write: '@w',
    browser_read: '@r',
    memory: '*m',
    profile: '~p',
    git: '%g',
    network: '^n',
    default: '··',
  }
  return map[categoryKey.value] || '··'
})

const categoryLabel = computed(() => {
  const labels = {
    shell: 'Shell / Python',
    file_write: 'File write',
    file_read: 'File read',
    browser_write: 'Browser action',
    browser_read: 'Browser read',
    memory: 'Memory',
    profile: 'Profile',
    git: 'Git',
    network: 'Network',
    default: 'Tool',
  }
  return labels[categoryKey.value] || 'Tool'
})

const label = computed(() => {
  const e = props.event
  switch (e.type) {
    case 'workflow_start':         return e.name || `workflow (${e.step_count ?? '?'} steps)`
    case 'workflow_done':          return 'workflow complete'
    case 'step_start':             return e.step_id || 'step'
    case 'step_done':              return e.step_id || 'step'
    case 'loop_iteration':         return `iteration ${e.iteration ?? '?'}`
    case 'condition_eval':         return e.step_id || 'condition'
    case 'variable_set':           return `$${e.name || '?'}`
    case 'browser_watch_trigger':  return e.event_name || 'watch trigger'
    default:                       return e.type
  }
})

const subtext = computed(() => {
  const e = props.event
  switch (e.type) {
    case 'workflow_start':         return e.step_count ? `${e.step_count} steps` : null
    case 'step_start':             return e.step_type || null
    case 'step_done':              return e.step_type || null
    case 'loop_iteration':         return e.max != null ? `of ${e.max}` : null
    case 'condition_eval':         return e.result === true ? 'true' : e.result === false ? 'false' : null
    case 'variable_set':           return e.value != null ? truncate(JSON.stringify(e.value), 60) : null
    case 'browser_watch_trigger':  return e.data?.selector
      ? truncate(e.data.selector, 40) + (e.data.current != null ? ` → ${truncate(String(e.data.current), 30)}` : '')
      : null
    default:                       return null
  }
})

const argPills = computed(() => {
  const e = props.event
  if (e.type !== 'tool_call' || !e.args) return []
  const out = []
  for (const [k, v] of Object.entries(e.args)) {
    if (v == null) continue
    let s
    if (typeof v === 'string') s = v
    else if (typeof v === 'number' || typeof v === 'boolean') s = String(v)
    else { try { s = JSON.stringify(v) } catch { s = String(v) } }
    out.push({ key: k, value: `"${truncate(s, 60)}"` })
    if (out.length >= 4) break
  }
  return out
})

const resultSummary = computed(() => {
  const e = props.event
  if (e.type !== 'tool_result') return null
  if (e.error) return truncate(e.error, 60)
  if (e.result == null) return 'ok'
  const summary = summariseTool(e.tool, e.result)
  if (summary) return summary
  try { return truncate(JSON.stringify(e.result), 60) } catch { return 'ok' }
})

const hasDetails = computed(() => {
  const e = props.event
  return (e.type === 'tool_call' && e.args != null && Object.keys(e.args).length > 0) ||
         (e.type === 'tool_result' && (e.result != null || e.error != null))
})

const detailsLabel = computed(() => {
  return props.event.type === 'tool_call' ? 'view args' : 'view result'
})

const detailsContent = computed(() => {
  const e = props.event
  if (e.type === 'tool_call')   return fmtJson(e.args)
  if (e.type === 'tool_result') return e.error || fmtJson(e.result)
  return ''
})

function truncate(s, n) {
  if (!s) return ''
  return s.length > n ? s.slice(0, n) + '…' : s
}

function fmtJson(v) {
  if (v == null) return 'null'
  try { return JSON.stringify(v, null, 2) }
  catch { return String(v) }
}
</script>

<style scoped>
/* ── Tool-block card ──────────────────────────────────────────────────── */
.tool-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px 10px 14px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin: 4px 0;
  transition: border-color 240ms cubic-bezier(0.32, 0.72, 0, 1),
              background 240ms cubic-bezier(0.32, 0.72, 0, 1);
  /* Per-category accent owned by --cat-color (set in cat-* classes below).
     Fallback to accent so unstyled categories still look right. */
  --cat-color: var(--accent);
  --cat-tint: color-mix(in srgb, var(--cat-color) 12%, transparent);
  --cat-bg:   color-mix(in srgb, var(--cat-color) 4%, var(--surface-1));
  border-left: 3px solid var(--cat-color);
}
.tool-block:hover {
  border-color: var(--border-strong);
  background: var(--cat-bg);
}

/* Per-category palette — translates the React reference's amber/green/blue
   /cyan/purple/pink/orange/violet to design-token mixes. */
.tool-block.cat-shell         { --cat-color: var(--warn); }
.tool-block.cat-file_write    { --cat-color: var(--success); }
.tool-block.cat-file_read     { --cat-color: color-mix(in srgb, var(--success) 80%, var(--accent-2)); }
.tool-block.cat-browser_write { --cat-color: var(--accent); }
.tool-block.cat-browser_read  { --cat-color: var(--accent-2, var(--accent)); }
.tool-block.cat-memory        { --cat-color: color-mix(in srgb, var(--accent) 60%, #b48cff); }
.tool-block.cat-profile       { --cat-color: color-mix(in srgb, var(--accent) 50%, #ff8cb4); }
.tool-block.cat-git           { --cat-color: color-mix(in srgb, var(--warn) 70%, var(--success)); }
.tool-block.cat-network       { --cat-color: color-mix(in srgb, var(--accent-2, var(--accent)) 80%, #b48cff); }

.tool-block.is-error {
  --cat-color: var(--error);
  border-color: color-mix(in srgb, var(--error) 35%, var(--border));
}
.tool-block.is-skill-load {
  background: color-mix(in srgb, var(--accent) 6%, var(--surface-1));
  border-color: color-mix(in srgb, var(--accent) 25%, var(--border));
}

.tool-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}
.tool-head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}
.tool-head-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* Category icon — colored monospace mini-tile, the React reference's
   primary visual marker for "what kind of work is this." */
.cat-icon {
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: var(--cat-tint);
  color: var(--cat-color);
  display: grid;
  place-items: center;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: -0.04em;
  user-select: none;
}

.tool-name-wrap {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.tool-name {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text-1);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: -0.01em;
}

.skill-badge {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  padding: 2px 7px;
  border-radius: 4px;
  letter-spacing: -0.01em;
  white-space: nowrap;
}

/* Status pill (icon + word) — replaces the bare dot from the prior
   version. Matches the React reference. */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.01em;
  white-space: nowrap;
}
.status-pill.state-pending  { color: var(--accent); }
.status-pill.state-success  { color: var(--success); }
.status-pill.state-error    { color: var(--error); }
.status-pill.state-neutral  { color: var(--text-3); }

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
.status-dot.dot-pending {
  animation: pulse-dot 1.4s ease-in-out infinite;
}

.status-glyph { color: currentColor; flex-shrink: 0; }

@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.4; transform: scale(0.85); }
}

.elapsed {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.result-summary {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 240px;
}
.tool-block.is-error .result-summary { color: var(--error); }

/* Argument pills */
.arg-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-left: 36px; /* aligns under tool-name, past the cat-icon */
}
.arg-pill {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px 8px;
  background: var(--surface-2);
  border-radius: 4px;
  max-width: 100%;
}
.arg-key {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
}
.arg-val {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 360px;
}

/* Expandable details */
.tool-details { margin-top: 2px; margin-left: 36px; }

.tool-details-toggle {
  list-style: none;
  font-size: 11px;
  color: var(--text-3);
  cursor: pointer;
  user-select: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 0;
  transition: color 120ms;
}
.tool-details-toggle::-webkit-details-marker { display: none; }
.tool-details-toggle::before {
  content: '›';
  display: inline-block;
  font-size: 13px;
  line-height: 1;
  transition: transform 150ms cubic-bezier(0.32, 0.72, 0, 1);
}
details[open] .tool-details-toggle::before { transform: rotate(90deg); }
.tool-details-toggle:hover { color: var(--text-2); }

.tool-pre {
  margin-top: 6px;
  background: var(--surface-2);
  border-radius: 6px;
  padding: 8px 10px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 180px;
  overflow-y: auto;
  line-height: 1.55;
}
.tool-pre.is-error-pre {
  background: color-mix(in srgb, var(--error) 10%, transparent);
  color: var(--error);
}

/* ── Inline row (non-tool events) ────────────────────────────────────── */
.row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 4px 0;
  transition: opacity 150ms;
}
.row-icon {
  width: 18px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding-top: 2px;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-3);
  flex-shrink: 0;
}
.dot.dot-done { background: var(--success); }
.dot.dot-live {
  background: var(--accent);
  animation: pulse-dot 1.4s ease-in-out infinite;
}
.glyph {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-mono);
  line-height: 1;
  user-select: none;
}
.glyph.is-success { color: var(--success); }

.row-body { flex: 1; min-width: 0; }
.row-head {
  display: flex;
  align-items: baseline;
  gap: 7px;
  flex-wrap: wrap;
}
.row-label {
  font-size: 12.5px;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.row-sub {
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}
.row.live .row-label { color: var(--text-1); }
</style>

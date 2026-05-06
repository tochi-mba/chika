<template>
  <!-- v0 tool-block card for tool_call / tool_result -->
  <div
    v-if="isToolEvent"
    class="tool-block"
    :class="{
      'is-pending': isPending,
      'is-error': isErrorResult,
      'is-success': isSuccessResult,
      'is-skill-load': isSkillLoad,
    }"
  >
    <div class="tool-head">
      <div class="tool-head-left">
        <span class="status-dot" :class="dotStateClass" />
        <span class="tool-name">{{ toolName }}</span>
        <span v-if="skillBadge" class="skill-badge">{{ skillBadge }}</span>
      </div>
      <div class="tool-head-right">
        <span v-if="isPending" class="mini-spinner" aria-label="running" />
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
  if (isPending.value) return 'dot-pending'
  if (isErrorResult.value) return 'dot-error'
  if (isSuccessResult.value) return 'dot-success'
  return 'dot-neutral'
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
  // Per-tool compact summary first (web_fetch → "200 · 2400B",
  // plan_set → "plan set · 1 task", etc). Falls back to a short
  // JSON dump for tools without a registered formatter.
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
/* ── v0 tool-block card ─────────────────────────────────────────────── */
.tool-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin: 4px 0;
  transition: border-color 160ms var(--spring);
}
.tool-block:hover { border-color: var(--border-strong); }
.tool-block.is-error { border-color: color-mix(in srgb, var(--error) 35%, var(--border)); }
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
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.tool-head-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-3);
  flex-shrink: 0;
}
.status-dot.dot-pending {
  background: var(--accent);
  animation: pulse-dot 1.4s ease-in-out infinite;
}
.status-dot.dot-success { background: var(--success); }
.status-dot.dot-error   { background: var(--error); }

@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.4; transform: scale(0.85); }
}

.tool-name {
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 12px;
  color: var(--accent);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: -0.01em;
}

.skill-badge {
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 10.5px;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  padding: 2px 7px;
  border-radius: 4px;
  letter-spacing: -0.01em;
  white-space: nowrap;
}

.mini-spinner {
  display: inline-block;
  width: 11px;
  height: 11px;
  border: 1.5px solid var(--text-3);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spinner-rotate 0.8s linear infinite;
}
@keyframes spinner-rotate {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

.elapsed {
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.result-summary {
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
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
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 11px;
  color: var(--text-3);
}
.arg-val {
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 11px;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 360px;
}

/* Expandable details */
.tool-details { margin-top: 2px; }

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
  transition: transform 150ms var(--spring);
}
details[open] .tool-details-toggle::before { transform: rotate(90deg); }
.tool-details-toggle:hover { color: var(--text-2); }

.tool-pre {
  margin-top: 6px;
  background: var(--surface-2);
  border-radius: 6px;
  padding: 8px 10px;
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
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

/* ── Inline row (non-tool events) ───────────────────────────────────── */
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
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
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

<template>
  <div class="row" :class="{ live }">
    <div class="row-icon">
      <span v-if="isDot" class="dot" :class="dotClass" />
      <span v-else class="glyph">{{ glyph }}</span>
    </div>
    <div class="row-body">
      <div class="row-head">
        <span class="row-label" :class="{ bold: event.type === 'tool_call' }">{{ label }}</span>
        <span v-if="subtext" class="row-sub">{{ subtext }}</span>
      </div>
      <details v-if="hasDetails" class="row-details">
        <summary class="row-details-toggle">{{ detailsLabel }}</summary>
        <pre class="row-pre">{{ detailsContent }}</pre>
      </details>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  event: { type: Object, required: true },
  live:  { type: Boolean, default: false },
})

// ── Icon logic ────────────────────────────────────────────────────────────────

const isDot = computed(() =>
  props.event.type === 'step_start' || props.event.type === 'step_done'
)

const dotClass = computed(() => ({
  'dot-live': props.live && props.event.type === 'step_start',
  'dot-done': props.event.type === 'step_done',
}))

const glyph = computed(() => {
  switch (props.event.type) {
    case 'workflow_start':         return '◫'
    case 'workflow_done':          return '⚑'
    case 'tool_call':              return '⚙'
    case 'tool_result':            return props.event.error ? '✕' : '✓'
    case 'loop_iteration':         return '↺'
    case 'condition_eval':         return '⑂'
    case 'variable_set':           return '$'
    case 'browser_watch_trigger':  return '◎'
    default:                       return '·'
  }
})

const glyphColorClass = computed(() => {
  if (props.event.type === 'tool_result') {
    return props.event.error ? 'red' : 'green'
  }
  return ''
})

// ── Label / subtext ───────────────────────────────────────────────────────────

const label = computed(() => {
  const e = props.event
  switch (e.type) {
    case 'workflow_start':         return e.name || `workflow (${e.step_count ?? '?'} steps)`
    case 'workflow_done':          return 'workflow complete'
    case 'step_start':             return e.step_id || 'step'
    case 'step_done':              return e.step_id || 'step'
    case 'tool_call':              return e.tool || e.step_id || 'tool'
    case 'tool_result':            return e.step_id || 'result'
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
    case 'tool_result':            return e.error
      ? truncate(e.error, 80)
      : e.result != null ? truncate(JSON.stringify(e.result), 80) : null
    case 'loop_iteration':         return e.max != null ? `of ${e.max}` : null
    case 'condition_eval':         return e.result === true ? 'true' : e.result === false ? 'false' : null
    case 'variable_set':           return e.value != null ? truncate(JSON.stringify(e.value), 60) : null
    case 'browser_watch_trigger':  return e.data?.selector
      ? truncate(e.data.selector, 40) + (e.data.current != null ? ` → ${truncate(String(e.data.current), 30)}` : '')
      : null
    default:                       return null
  }
})

// ── Expandable details (args for tool_call, full result for tool_result) ──────

const hasDetails = computed(() => {
  const e = props.event
  return (e.type === 'tool_call' && e.args != null) ||
         (e.type === 'tool_result' && (e.result != null || e.error != null))
})

const detailsLabel = computed(() => {
  return props.event.type === 'tool_call' ? 'args' : 'result'
})

const detailsContent = computed(() => {
  const e = props.event
  if (e.type === 'tool_call')   return fmtJson(e.args)
  if (e.type === 'tool_result') return e.error || fmtJson(e.result)
  return ''
})

// ── Helpers ───────────────────────────────────────────────────────────────────

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
.row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 4px 0;
  transition: opacity 150ms;
}

/* Icon column */
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
  background: var(--text-3, #4f4f6a);
  flex-shrink: 0;
}
.dot.dot-done {
  background: var(--green, #3dd68c);
}
.dot.dot-live {
  background: var(--accent, #6c63ff);
  animation: pulse 1.4s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.35; }
}

.glyph {
  font-size: 11px;
  color: var(--text-3, #4f4f6a);
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  line-height: 1;
  user-select: none;
}

/* Color overrides per event type */
.row[data-type="tool_result-ok"] .glyph   { color: var(--green, #3dd68c); }
.row[data-type="tool_result-err"] .glyph  { color: var(--red, #e05c5c); }

/* Body column */
.row-body {
  flex: 1;
  min-width: 0;
}

.row-head {
  display: flex;
  align-items: baseline;
  gap: 7px;
  flex-wrap: wrap;
}

.row-label {
  font-size: 12.5px;
  color: var(--text-2, #8888a2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.row-label.bold {
  color: var(--text-1, #ededf2);
  font-weight: 500;
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 12px;
}

.row-sub {
  font-size: 11px;
  color: var(--text-3, #4f4f6a);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}

/* Expandable args/result */
.row-details {
  margin-top: 4px;
}

.row-details-toggle {
  list-style: none;
  font-size: 11px;
  color: var(--text-3, #4f4f6a);
  cursor: pointer;
  user-select: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 0;
  transition: color 120ms;
}
.row-details-toggle::-webkit-details-marker { display: none; }
.row-details-toggle::before {
  content: '›';
  display: inline-block;
  font-size: 13px;
  line-height: 1;
  transition: transform 150ms var(--ease, cubic-bezier(0.16, 1, 0.3, 1));
}
details[open] .row-details-toggle::before {
  transform: rotate(90deg);
}
.row-details-toggle:hover { color: var(--text-2, #8888a2); }

.row-pre {
  margin-top: 5px;
  background: var(--surface-3, #20202a);
  border: 1px solid var(--border, rgba(255,255,255,0.07));
  border-radius: var(--radius-sm, 5px);
  padding: 8px 10px;
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 11px;
  color: var(--text-2, #8888a2);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 180px;
  overflow-y: auto;
  line-height: 1.55;
}

/* Live row highlight */
.row.live .row-label {
  color: var(--text-1, #ededf2);
}
</style>

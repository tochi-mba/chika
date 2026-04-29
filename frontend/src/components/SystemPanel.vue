<template>
  <div class="system-panel" :class="{ collapsed }">
    <div class="panel-header">
      <!-- Tab strip -->
      <div class="tabs">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="tab"
          :class="{ active: activeTab === tab.id }"
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
          <span v-if="tab.count" class="tab-count">{{ tab.count }}</span>
        </button>
      </div>
      <!-- Collapse toggle -->
      <button class="collapse-btn" @click="$emit('toggle')" :title="collapsed ? 'Expand panel' : 'Collapse panel'">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
          :style="{ transform: collapsed ? 'rotate(180deg)' : 'none', transition: 'transform 200ms' }">
          <polyline points="9 18 15 12 9 6"/>
        </svg>
      </button>
    </div>

    <!-- Live Events -->
    <div v-if="activeTab === 'events'" class="panel-body" ref="eventsContainer">
      <div v-if="system.events.length === 0" class="empty-hint">No events yet</div>
      <div
        v-for="(event, i) in system.events"
        :key="i"
        class="event-row"
        :class="event.type"
      >
        <span class="ev-type">{{ event.type }}</span>
        <span class="ev-preview">{{ preview(event) }}</span>
        <span class="ev-ts">{{ fmtTs(event._ts) }}</span>
      </div>
    </div>

    <!-- Workflow -->
    <div v-else-if="activeTab === 'workflow'" class="panel-body">
      <div v-if="!system.activeWorkflow" class="empty-hint">No active workflow</div>
      <WorkflowCard v-else :workflow="system.activeWorkflow" />
    </div>

    <!-- Variables -->
    <div v-else-if="activeTab === 'variables'" class="panel-body">
      <div v-if="!system.variableCount" class="empty-hint">No variables set</div>
      <VariableCard v-for="v in sortedVars" :key="v.name" :variable="v" />
    </div>

    <!-- Memory -->
    <div v-else-if="activeTab === 'memory'" class="panel-body">
      <div v-if="!system.memoryCount" class="empty-hint">Memory is empty</div>
      <MemoryEntry v-for="e in memoryEntries" :key="e.key" :entry="e" />
    </div>

    <!-- Shells -->
    <div v-else-if="activeTab === 'shells'" class="panel-body">
      <ShellsPanel />
    </div>

    <!-- Raw JSON -->
    <div v-else-if="activeTab === 'raw'" class="panel-body raw-panel">
      <div v-if="system.events.length === 0" class="empty-hint">No events yet</div>
      <pre v-for="(event, i) in system.events" :key="i" class="raw-line">{{ JSON.stringify(event) }}</pre>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useSystemStore } from '../stores/system'
import WorkflowCard from './WorkflowCard.vue'
import VariableCard from './VariableCard.vue'
import MemoryEntry from './MemoryEntry.vue'
import ShellsPanel from './ShellsPanel.vue'

defineProps({
  collapsed: { type: Boolean, default: false },
})
defineEmits(['toggle'])

const system = useSystemStore()
const activeTab = ref('events')
const eventsContainer = ref(null)

const tabs = computed(() => [
  { id: 'events',    label: 'Events',    count: system.eventCount },
  { id: 'workflow',  label: 'Workflow',  count: null },
  { id: 'shells',    label: 'Shells',    count: system.runningShellCount || system.shellCount || null },
  { id: 'variables', label: 'Variables', count: system.variableCount || null },
  { id: 'memory',    label: 'Memory',    count: system.memoryCount || null },
  { id: 'raw',       label: 'Raw',       count: null },
])

const sortedVars = computed(() =>
  Object.values(system.variables).sort((a, b) => b.updatedAt - a.updatedAt)
)
const memoryEntries = computed(() => Object.values(system.memory))

watch(() => system.events.length, () => {
  if (activeTab.value !== 'events') return
  nextTick(() => {
    const el = eventsContainer.value
    if (el) el.scrollTop = el.scrollHeight
  })
})

function preview(event) {
  if (event.type === 'token')              return event.text?.slice(0, 40) + (event.text?.length > 40 ? '…' : '')
  if (event.type === 'tool_call')          return `${event.tool}(${JSON.stringify(event.args)?.slice(0, 40)})`
  if (event.type === 'tool_result')        return event.error || JSON.stringify(event.result)?.slice(0, 40)
  if (event.type === 'variable_set')       return `${event.name} (${event.var_type}, ${event.size_bytes}B)`
  if (event.type === 'step_start')         return `${event.step_id} [${event.step_type}]`
  if (event.type === 'loop_iteration')     return `iter ${event.iteration}/${event.max}`
  if (event.type === 'condition_eval')     return `${event.result ? '✓' : '✗'} ${event.step_id}`
  if (event.type === 'workflow_start')     return event.name
  if (event.type === 'error')              return event.message
  if (event.type === 'shell_process_start') return `pid=${event.pid} ${event.command?.slice(0, 40)}`
  if (event.type === 'shell_output')       return `pid=${event.pid} [${event.stream}] ${event.lines?.[0]?.slice(0, 30)}`
  if (event.type === 'shell_process_done') return `pid=${event.pid} exit=${event.exit_code}`
  if (event.type === 'approval_required')  return `${event.tool} — waiting`
  if (event.type === 'browser_watch_trigger') return `${event.event_name || 'watch'} — ${event.data?.selector || ''}`
  if (event.type === 'extension_status')   return event.connected ? 'extension connected' : 'extension disconnected'
  return ''
}

function fmtTs(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
</script>

<style scoped>
.system-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface-1, #111117);
  border-left: 1px solid var(--border, rgba(255,255,255,0.07));
  min-width: 0;
}

/* ── Panel header (tabs + collapse) ──────────────────────────────────────── */
.panel-header {
  display: flex;
  align-items: stretch;
  border-bottom: 1px solid var(--border, rgba(255,255,255,0.07));
  flex-shrink: 0;
}

.tabs {
  display: flex;
  flex: 1;
  overflow-x: auto;
  gap: 0;
}
.tabs::-webkit-scrollbar { height: 0; }

.tab {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 9px 11px;
  font-size: 12px;
  font-family: inherit;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-3, #4f4f6a);
  cursor: pointer;
  white-space: nowrap;
  transition: color 150ms, border-color 150ms;
}
.tab:hover    { color: var(--text-2, #8888a2); }
.tab.active   { color: var(--text-1, #ededf2); border-bottom-color: var(--accent, #6c63ff); }

.tab-count {
  font-size: 10px;
  padding: 1px 5px;
  background: var(--surface-3, #20202a);
  border-radius: 999px;
  color: var(--text-2, #8888a2);
  font-variant-numeric: tabular-nums;
}

.collapse-btn {
  flex-shrink: 0;
  width: 38px;
  background: none;
  border: none;
  border-left: 1px solid var(--border, rgba(255,255,255,0.07));
  color: var(--text-3, #4f4f6a);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 150ms, background 150ms;
}
.collapse-btn:hover {
  color: var(--text-2, #8888a2);
  background: var(--surface-2, #18181f);
}

/* ── Panel body ──────────────────────────────────────────────────────────── */
.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}

.empty-hint {
  text-align: center;
  color: var(--text-3, #4f4f6a);
  font-size: 12px;
  padding: 28px 16px;
}

/* ── Event rows ──────────────────────────────────────────────────────────── */
.event-row {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 3px 5px;
  border-radius: var(--radius-sm, 5px);
  font-size: 11px;
  line-height: 1.45;
  cursor: default;
}
.event-row:hover { background: var(--surface-2, #18181f); }

.ev-type {
  font-family: var(--font-mono, monospace);
  color: var(--accent, #6c63ff);
  width: 116px;
  flex-shrink: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ev-preview {
  flex: 1;
  color: var(--text-2, #8888a2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ev-ts {
  color: var(--text-3, #4f4f6a);
  font-family: var(--font-mono, monospace);
  font-variant-numeric: tabular-nums;
  width: 78px;
  text-align: right;
  flex-shrink: 0;
}

/* Type-specific colours */
.event-row.tool_call     .ev-type { color: #d0a060; }
.event-row.tool_result   .ev-type { color: var(--green, #3dd68c); }
.event-row.error         .ev-type { color: var(--red, #e05c5c); }
.event-row.workflow_start .ev-type { color: #60a0ff; }
.event-row.token         .ev-type { color: var(--text-3, #4f4f6a); }
.event-row.variable_set  .ev-type { color: #c080d0; }
.event-row.memory_update .ev-type { color: #80d0a0; }
.event-row.shell_process_start .ev-type { color: var(--green, #3dd68c); }
.event-row.shell_output        .ev-type { color: #668877; }
.event-row.shell_process_done  .ev-type { color: var(--text-3, #4f4f6a); }
.event-row.approval_required      .ev-type { color: var(--yellow, #e0b35c); }
.event-row.browser_watch_trigger  .ev-type { color: var(--yellow, #e0b35c); }
.event-row.extension_status       .ev-type { color: #9d7fff; }

/* ── Raw JSON ─────────────────────────────────────────────────────────────── */
.raw-panel { background: rgba(0,0,0,0.2); }
.raw-line {
  font-family: var(--font-mono, monospace);
  font-size: 10px;
  color: var(--text-3, #4f4f6a);
  white-space: pre-wrap;
  word-break: break-all;
  border-bottom: 1px solid var(--border, rgba(255,255,255,0.07));
  padding: 2px 0;
}
.raw-line:hover { color: var(--text-2, #8888a2); }
</style>

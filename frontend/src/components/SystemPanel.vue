<template>
  <div class="system-panel">
    <!-- Tab bar -->
    <div class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
        <span v-if="tab.count !== null" class="count">{{ tab.count }}</span>
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
      <VariableCard
        v-for="v in sortedVars"
        :key="v.name"
        :variable="v"
      />
    </div>

    <!-- Memory -->
    <div v-else-if="activeTab === 'memory'" class="panel-body">
      <div v-if="!system.memoryCount" class="empty-hint">Memory is empty</div>
      <MemoryEntry
        v-for="e in memoryEntries"
        :key="e.key"
        :entry="e"
      />
    </div>

    <!-- Shells -->
    <div v-else-if="activeTab === 'shells'" class="panel-body">
      <ShellsPanel />
    </div>

    <!-- Raw JSON -->
    <div v-else-if="activeTab === 'raw'" class="panel-body raw">
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

const system = useSystemStore()
const activeTab = ref('events')
const eventsContainer = ref(null)

const tabs = computed(() => [
  { id: 'events',   label: 'Live Events', count: system.eventCount },
  { id: 'workflow', label: 'Workflow',    count: null },
  { id: 'shells',   label: 'Shells',      count: system.runningShellCount || system.shellCount || null },
  { id: 'variables',label: 'Variables',  count: system.variableCount || null },
  { id: 'memory',   label: 'Memory',     count: system.memoryCount || null },
  { id: 'raw',      label: 'Raw JSON',   count: null },
])

const sortedVars = computed(() =>
  Object.values(system.variables).sort((a, b) => b.updatedAt - a.updatedAt)
)

const memoryEntries = computed(() => Object.values(system.memory))

// Auto-scroll events panel
watch(() => system.events.length, () => {
  if (activeTab.value !== 'events') return
  nextTick(() => {
    const el = eventsContainer.value
    if (el) el.scrollTop = el.scrollHeight
  })
})

function preview(event) {
  if (event.type === 'token') return event.text?.slice(0, 40) + (event.text?.length > 40 ? '…' : '')
  if (event.type === 'tool_call') return `${event.tool}(${JSON.stringify(event.args).slice(0, 40)}…)`
  if (event.type === 'tool_result') return event.error || JSON.stringify(event.result)?.slice(0, 40) + '…'
  if (event.type === 'variable_set') return `${event.name} (${event.var_type}, ${event.size_bytes}B)`
  if (event.type === 'step_start') return `${event.step_id} [${event.step_type}]`
  if (event.type === 'loop_iteration') return `iter ${event.iteration}/${event.max}`
  if (event.type === 'condition_eval') return `${event.result ? '✓' : '✗'} ${event.step_id}`
  if (event.type === 'workflow_start') return event.name
  if (event.type === 'error') return event.message
  if (event.type === 'shell_process_start') return `pid=${event.pid} ${event.command?.slice(0, 40)}`
  if (event.type === 'shell_output') return `pid=${event.pid} [${event.stream}] ${event.lines?.[0]?.slice(0, 30)}`
  if (event.type === 'shell_process_done') return `pid=${event.pid} exit=${event.exit_code}`
  if (event.type === 'approval_required') return `${event.tool} — waiting for approval`
  return ''
}

function fmtTs(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
</script>

<style scoped>
.system-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #111118;
  border-left: 1px solid #2a2a35;
}

.tabs {
  display: flex;
  border-bottom: 1px solid #2a2a35;
  flex-shrink: 0;
  overflow-x: auto;
}
.tabs::-webkit-scrollbar { height: 0; }
.tabs button {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 9px 12px;
  font-size: 12px;
  background: none;
  border: none;
  color: #666;
  cursor: pointer;
  white-space: nowrap;
  border-bottom: 2px solid transparent;
  transition: color 0.15s;
}
.tabs button:hover  { color: #aaa; }
.tabs button.active { color: #a8a0ff; border-bottom-color: #6c63ff; }

.count {
  font-size: 10px;
  padding: 1px 5px;
  background: #2a2a3a;
  border-radius: 8px;
  color: #888;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.panel-body::-webkit-scrollbar { width: 5px; }
.panel-body::-webkit-scrollbar-track { background: transparent; }
.panel-body::-webkit-scrollbar-thumb { background: #2a2a35; border-radius: 3px; }

.empty-hint {
  text-align: center;
  color: #444;
  font-size: 12px;
  padding: 24px;
}

/* Event rows */
.event-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 3px 6px;
  border-radius: 4px;
  font-size: 11px;
  line-height: 1.4;
}
.event-row:hover { background: #1a1a22; }
.ev-type {
  font-family: monospace;
  color: #6c63ff;
  width: 120px;
  flex-shrink: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ev-preview { flex: 1; color: #888; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ev-ts { color: #444; font-family: monospace; width: 80px; text-align: right; flex-shrink: 0; }

/* Type-specific colours */
.event-row.tool_call    .ev-type { color: #d0a060; }
.event-row.tool_result  .ev-type { color: #60d080; }
.event-row.error        .ev-type { color: #ff6060; }
.event-row.workflow_start .ev-type { color: #60a0ff; }
.event-row.token        .ev-type { color: #555; }
.event-row.variable_set .ev-type { color: #c080d0; }
.event-row.memory_update .ev-type { color: #80d0a0; }
.event-row.shell_process_start .ev-type { color: #40d080; }
.event-row.shell_output        .ev-type { color: #668877; }
.event-row.shell_process_done  .ev-type { color: #888888; }
.event-row.approval_required   .ev-type { color: #ffaa44; }

/* Raw JSON */
.raw { background: #0d0d10; }
.raw-line {
  font-family: monospace;
  font-size: 10px;
  color: #666;
  white-space: pre-wrap;
  word-break: break-all;
  border-bottom: 1px solid #1a1a20;
  padding: 2px 0;
}
.raw-line:hover { color: #aaa; }
</style>

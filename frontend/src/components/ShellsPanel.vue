<template>
  <div class="shells-panel">
    <div v-if="!procs.length" class="empty-hint">No shell processes yet</div>

    <div v-if="runningCount > 0" class="shells-toolbar">
      <span class="shells-count">{{ runningCount }} running</span>
      <button class="shells-killall" @click="killAll" :disabled="killing">
        {{ killing ? 'Killing…' : 'Kill all' }}
      </button>
    </div>

    <div
      v-for="proc in procs"
      :key="proc.pid"
      class="proc-card"
      :class="{ running: proc.running, exited: !proc.running }"
    >
      <!-- Header -->
      <div class="proc-header" @click="toggle(proc.pid)">
        <span class="status-dot" :class="{ running: proc.running }" />
        <span class="pid">PID {{ proc.pid }}</span>
        <span class="cmd">{{ proc.command }}</span>
        <span class="exit-badge" v-if="!proc.running">
          exit {{ proc.exit_code ?? '?' }}
        </span>
        <span class="duration" v-if="proc.finishedAt">
          {{ fmtDuration(proc.startedAt, proc.finishedAt) }}
        </span>
        <span class="running-pill" v-if="proc.running">running</span>
        <button
          v-if="proc.running"
          class="kill-btn"
          @click.stop="killOne(proc.pid)"
          :disabled="killing"
          title="Terminate this process"
        >Kill</button>
        <span class="chevron">{{ expanded.has(proc.pid) ? '▾' : '▸' }}</span>
      </div>

      <!-- Output -->
      <div v-if="expanded.has(proc.pid)" class="proc-body">
        <!-- stdout -->
        <div v-if="proc.stdout.length" class="stream-section">
          <div class="stream-label">stdout</div>
          <div class="output-scroll" :ref="el => setScrollRef(proc.pid, 'out', el)">
            <div
              v-for="(line, i) in proc.stdout"
              :key="i"
              class="out-line stdout"
            >{{ line }}</div>
          </div>
        </div>

        <!-- stderr -->
        <div v-if="proc.stderr.length" class="stream-section">
          <div class="stream-label stderr-label">stderr</div>
          <div class="output-scroll">
            <div
              v-for="(line, i) in proc.stderr"
              :key="i"
              class="out-line stderr"
            >{{ line }}</div>
          </div>
        </div>

        <div v-if="!proc.stdout.length && !proc.stderr.length" class="no-output">
          No output yet
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useSystemStore } from '../stores/system'

const system = useSystemStore()

const procs = computed(() =>
  Object.values(system.shellProcesses).sort((a, b) => b.startedAt - a.startedAt)
)

const expanded = ref(new Set())

function toggle(pid) {
  if (expanded.value.has(pid)) {
    expanded.value.delete(pid)
  } else {
    expanded.value.add(pid)
  }
  // Trigger reactivity on the Set
  expanded.value = new Set(expanded.value)
}

// Auto-expand new processes
watch(procs, (newProcs, oldProcs) => {
  const oldPids = new Set((oldProcs || []).map(p => p.pid))
  for (const p of newProcs) {
    if (!oldPids.has(p.pid)) {
      expanded.value = new Set([...expanded.value, p.pid])
    }
  }
}, { deep: false })

// Auto-scroll to bottom of stdout when new lines arrive
const scrollRefs = ref({})

function setScrollRef(pid, stream, el) {
  if (el) scrollRefs.value[`${pid}_${stream}`] = el
}

watch(
  () => system.shellProcesses,
  () => {
    nextTick(() => {
      for (const [key, el] of Object.entries(scrollRefs.value)) {
        if (el) el.scrollTop = el.scrollHeight
      }
    })
  },
  { deep: true }
)

// ── Kill controls ──────────────────────────────────────────────────────
// Per-pid pending set so kills can run concurrently — a global
// ``killing`` flag would freeze every other Kill button while one
// request is in flight, which is bad UX when multiple processes are
// hung. ``killingAll`` is a separate flag because kill-all is genuinely
// one operation.
const killingPids = ref(new Set())
const killingAll  = ref(false)

const killing = computed(() => killingAll.value || killingPids.value.size > 0)

const runningCount = computed(
  () => procs.value.filter(p => p.running).length,
)

function authHeaders() {
  const key = localStorage.getItem('chika_api_key') || ''
  const h = { 'Content-Type': 'application/json' }
  if (key) h['Authorization'] = `Bearer ${key}`
  return h
}

function _markKilling(pid) {
  killingPids.value = new Set([...killingPids.value, pid])
}
function _unmarkKilling(pid) {
  killingPids.value = new Set(
    [...killingPids.value].filter(p => p !== pid),
  )
}

async function killOne(pid) {
  if (killingPids.value.has(pid)) return
  _markKilling(pid)
  try {
    const res = await fetch(`/api/shells/${pid}/kill`, {
      method: 'POST',
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    // The shell_process_done event will arrive over the WS shortly.
  } catch (err) {
    console.error('[Chika] kill', pid, 'failed:', err)
  } finally {
    _unmarkKilling(pid)
  }
}

async function killAll() {
  if (killingAll.value) return
  killingAll.value = true
  try {
    const res = await fetch('/api/shells/kill_all', {
      method: 'POST',
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
  } catch (err) {
    console.error('[Chika] killAll failed:', err)
  } finally {
    killingAll.value = false
  }
}

function fmtDuration(start, end) {
  const ms = end - start
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
}
</script>

<style scoped>
.shells-panel {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.empty-hint {
  text-align: center;
  color: var(--text-3);
  font-size: 12px;
  padding: 24px;
}

.shells-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px 0;
  font-size: 11px;
}
.shells-count {
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.shells-killall {
  background: none;
  border: 1px solid var(--red, #e05c5c);
  color: var(--red, #e05c5c);
  border-radius: 4px;
  padding: 3px 9px;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  transition: background 100ms, color 100ms;
}
.shells-killall:hover:not(:disabled) {
  background: var(--red, #e05c5c);
  color: white;
}
.shells-killall:disabled { opacity: 0.5; cursor: not-allowed; }

.kill-btn {
  background: none;
  border: 1px solid var(--red, #e05c5c);
  color: var(--red, #e05c5c);
  border-radius: 4px;
  padding: 2px 7px;
  font: inherit;
  font-size: 10px;
  cursor: pointer;
  margin-left: auto;
  transition: background 100ms, color 100ms;
}
.kill-btn:hover:not(:disabled) {
  background: var(--red, #e05c5c);
  color: white;
}
.kill-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.proc-card {
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  overflow: hidden;
}
.proc-card.running { border-color: var(--green); }
.proc-card.exited  { border-color: var(--border-strong); }

.proc-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--surface-2);
  cursor: pointer;
  user-select: none;
  font-size: 12px;
}
.proc-header:hover { background: var(--surface-3); }

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-3);
  flex-shrink: 0;
}
.status-dot.running {
  background: var(--green);
  box-shadow: 0 0 5px rgba(61, 214, 140, 0.5);
  animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
}

.pid {
  font-family: var(--font-mono);
  color: var(--accent);
  flex-shrink: 0;
  font-size: 11px;
}

.cmd {
  flex: 1;
  font-family: var(--font-mono);
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 11px;
}

.exit-badge {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--red-dim);
  color: var(--red);
  flex-shrink: 0;
}

.running-pill {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--green-dim);
  color: var(--green);
  flex-shrink: 0;
  animation: pulse 1.5s ease-in-out infinite;
}

.duration {
  font-size: 10px;
  color: var(--text-3);
  flex-shrink: 0;
  font-family: var(--font-mono);
}

.chevron {
  color: var(--text-3);
  font-size: 10px;
  flex-shrink: 0;
}

/* Terminal output area — stays dark in both themes */
.proc-body {
  background: var(--surface-0);
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stream-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stream-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-3);
}
.stderr-label {
  color: var(--red);
  opacity: 0.7;
}

.output-scroll {
  max-height: 200px;
  overflow-y: auto;
  background: var(--surface-0);
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  padding: 6px 8px;
}
.output-scroll::-webkit-scrollbar       { width: 4px; }
.output-scroll::-webkit-scrollbar-track { background: transparent; }
.output-scroll::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 3px; }

.out-line {
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}
/* Terminal text always light-on-dark regardless of theme */
.out-line.stdout { color: #c0c8d0; }
.out-line.stderr { color: #d08080; }

.no-output {
  font-size: 11px;
  color: var(--text-3);
  padding: 4px;
}
</style>

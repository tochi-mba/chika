<template>
  <div class="shells-panel">
    <div v-if="!procs.length" class="empty-hint">No shell processes yet</div>

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
  color: #444;
  font-size: 12px;
  padding: 24px;
}

.proc-card {
  border: 1px solid #2a2a35;
  border-radius: 8px;
  overflow: hidden;
}
.proc-card.running { border-color: #40d08055; }
.proc-card.exited   { border-color: #2a2a35; }

.proc-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: #1a1a24;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
}
.proc-header:hover { background: #1e1e2c; }

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #444;
  flex-shrink: 0;
}
.status-dot.running {
  background: #40d080;
  box-shadow: 0 0 5px #40d08088;
  animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.pid {
  font-family: monospace;
  color: #6c63ff;
  flex-shrink: 0;
  font-size: 11px;
}

.cmd {
  flex: 1;
  font-family: monospace;
  color: #c8c8d8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 11px;
}

.exit-badge {
  font-family: monospace;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #2a1a1a;
  color: #cc6666;
  flex-shrink: 0;
}

.running-pill {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #1a2a1a;
  color: #40d080;
  flex-shrink: 0;
  animation: pulse 1.5s ease-in-out infinite;
}

.duration {
  font-size: 10px;
  color: #555;
  flex-shrink: 0;
  font-family: monospace;
}

.chevron {
  color: #555;
  font-size: 10px;
  flex-shrink: 0;
}

.proc-body {
  background: #0d0d12;
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
  color: #555;
}
.stderr-label { color: #884444; }

.output-scroll {
  max-height: 200px;
  overflow-y: auto;
  background: #111118;
  border: 1px solid #1e1e28;
  border-radius: 6px;
  padding: 6px 8px;
}
.output-scroll::-webkit-scrollbar { width: 4px; }
.output-scroll::-webkit-scrollbar-track { background: transparent; }
.output-scroll::-webkit-scrollbar-thumb { background: #2a2a35; border-radius: 3px; }

.out-line {
  font-family: monospace;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}
.out-line.stdout { color: #c0c8d0; }
.out-line.stderr { color: #d08080; }

.no-output {
  font-size: 11px;
  color: #444;
  padding: 4px;
}
</style>

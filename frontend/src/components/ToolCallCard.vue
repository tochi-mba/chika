<template>
  <div class="tool-card" :class="{ done: result !== null, error: hasError }">
    <div class="header" @click="open = !open">
      <span class="icon">{{ hasError ? '✗' : result !== null ? '✓' : '⋯' }}</span>
      <span class="name">{{ event.tool }}</span>
      <span v-if="event.duration_ms" class="dur">{{ event.duration_ms }}ms</span>
      <span class="toggle">{{ open ? '▲' : '▼' }}</span>
    </div>
    <div v-if="open" class="body">
      <div class="section-label">Args</div>
      <pre class="json">{{ fmt(event.args) }}</pre>
      <template v-if="result !== null">
        <div class="section-label">Result</div>
        <pre class="json" :class="{ error: hasError }">{{ fmt(result) }}</pre>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({ event: Object })
const open = ref(false)

const result   = computed(() => props.event.result ?? null)
const hasError = computed(() => props.event.error || (result.value && result.value.error))

function fmt(val) {
  try { return JSON.stringify(val, null, 2) }
  catch { return String(val) }
}
</script>

<style scoped>
.tool-card {
  border: 1px solid #2a2a35;
  border-radius: 8px;
  overflow: hidden;
  font-size: 12px;
  margin: 3px 0;
}
.tool-card.done  { border-color: #2a3a2a; }
.tool-card.error { border-color: #3a2a2a; }

.header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #1a1a22;
  cursor: pointer;
  user-select: none;
}
.header:hover { background: #1e1e2a; }
.icon { font-size: 10px; width: 14px; }
.name { flex: 1; font-family: monospace; color: #a8a0ff; }
.dur  { color: #666; font-size: 11px; }
.toggle { color: #555; font-size: 10px; }

.body { padding: 8px 10px; background: #13131a; }
.section-label { font-size: 10px; color: #555; text-transform: uppercase; letter-spacing: 0.5px; margin: 4px 0 2px; }

pre.json {
  font-family: monospace;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
  color: #c0c0d0;
  max-height: 300px;
  overflow-y: auto;
}
pre.json.error { color: #ff8080; }
</style>

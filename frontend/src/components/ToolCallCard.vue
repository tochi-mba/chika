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
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  font-size: 12px;
  margin: 3px 0;
  background: var(--surface-1);
  transition: border-color 140ms var(--spring);
}
.tool-card.done  { border-color: color-mix(in srgb, var(--success) 24%, var(--border)); }
.tool-card.error { border-color: color-mix(in srgb, var(--error) 30%, var(--border)); }

.header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  background: var(--surface-2);
  cursor: pointer;
  user-select: none;
}
.header:hover { background: color-mix(in srgb, var(--accent) 6%, var(--surface-2)); }
.icon { font-size: 11px; width: 14px; color: var(--text-3); font-family: var(--font-mono); }
.tool-card.done .icon  { color: var(--success); }
.tool-card.error .icon { color: var(--error); }
.name { flex: 1; font-family: var(--font-mono); color: var(--accent); font-weight: 500; }
.dur  { color: var(--text-3); font-size: 11px; font-variant-numeric: tabular-nums; }
.toggle { color: var(--text-3); font-size: 10px; }

.body { padding: 10px 12px; background: var(--surface-1); border-top: 1px solid var(--border); }
.section-label {
  font-size: 10px;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  font-weight: 600;
  margin: 4px 0 4px;
}

pre.json {
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--text-2);
  max-height: 300px;
  overflow-y: auto;
  background: var(--surface-2);
  border-radius: 6px;
  padding: 8px 10px;
  margin: 0 0 8px;
  line-height: 1.5;
}
pre.json.error {
  color: var(--error);
  background: color-mix(in srgb, var(--error) 8%, transparent);
}
</style>

<template>
  <div class="step-row" :class="event.step_type">
    <span class="icon">{{ icon }}</span>
    <span class="label">{{ event.step_id }}</span>
    <span class="type-badge">{{ event.step_type }}</span>
    <span v-if="done" class="dur">{{ done.duration_ms }}ms</span>
    <span v-else class="spinner">…</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ event: Object, done: Object })

const ICONS = {
  sequential: '→', parallel: '⫸', conditional: '⋔',
  loop: '↻', map: '⊕', fan_out: '⇶',
  retry: '↺', pipeline: '⤳', sub_workflow: '⊞',
}

const icon = computed(() => ICONS[props.event.step_type] || '·')
</script>

<style scoped>
.step-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
  background: #1a1a22;
  margin: 2px 0;
}
.icon { width: 16px; text-align: center; color: #6c63ff; }
.label { flex: 1; font-family: monospace; color: #c0c0d0; }
.type-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 10px;
  background: #252535;
  color: #888;
}
.dur { color: #555; font-size: 11px; }
.spinner { color: #6c63ff; animation: pulse 1s infinite; }
@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.3 } }
</style>

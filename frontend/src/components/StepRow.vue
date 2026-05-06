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
  padding: 6px 10px;
  border-radius: 8px;
  border-left: 2px solid color-mix(in srgb, var(--accent) 50%, transparent);
  font-size: 12px;
  background: var(--surface-2);
  margin: 2px 0;
  transition: background 200ms cubic-bezier(0.32, 0.72, 0, 1);
}
.step-row:hover {
  background: color-mix(in srgb, var(--accent) 6%, var(--surface-2));
}
.icon { width: 16px; text-align: center; color: var(--accent); font-family: var(--font-mono); }
.label { flex: 1; font-family: var(--font-mono); color: var(--text-1); }
.type-badge {
  font-size: 10px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  color: var(--text-3);
  font-weight: 500;
}
.dur {
  color: var(--text-3);
  font-size: 11px;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.spinner { color: var(--accent); animation: pulse 1.4s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.4 } }
</style>

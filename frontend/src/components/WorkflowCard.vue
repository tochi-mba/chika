<template>
  <div class="wf-card">
    <div class="wf-header">
      <span class="wf-icon">{{ workflow.status === 'done' ? '✓' : '⋯' }}</span>
      <span class="wf-name">{{ workflow.name }}</span>
      <span class="wf-status" :class="workflow.status">{{ workflow.status }}</span>
    </div>

    <div class="steps" v-if="steps.length">
      <div v-for="(entry, i) in steps" :key="i" class="step-entry">
        <template v-if="entry.type === 'tool_call'">
          <ToolCallCard :event="entry" />
        </template>
        <template v-else-if="entry.type === 'step_start'">
          <StepRow :event="entry" :done="stepDone[entry.step_id]" />
        </template>
        <template v-else-if="entry.type === 'loop_iteration'">
          <div class="loop-iter">Loop {{ entry.step_id }} — iteration {{ entry.iteration }}/{{ entry.max }}</div>
        </template>
        <template v-else-if="entry.type === 'condition_eval'">
          <div class="cond">
            <span class="cond-icon">{{ entry.result ? '✓ true' : '✗ false' }}</span>
            <span class="cond-expr">{{ entry.step_id }}</span>
          </div>
        </template>
        <template v-else-if="entry.type === 'variable_set'">
          <div class="var-set">
            <span class="var-name">{{ entry.name }}</span>
            <span class="var-type">{{ entry.var_type }}</span>
            <span class="var-size">{{ entry.size_bytes }}B</span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useSystemStore } from '../stores/system'
import ToolCallCard from './ToolCallCard.vue'
import StepRow from './StepRow.vue'

const props = defineProps({ workflow: Object })
const system = useSystemStore()

// Filter events belonging to this workflow
const steps = computed(() => {
  return system.events.filter(e =>
    ['step_start','tool_call','loop_iteration','condition_eval','variable_set'].includes(e.type)
  )
})

const stepDone = computed(() => {
  const map = {}
  system.events.filter(e => e.type === 'step_done').forEach(e => { map[e.step_id] = e })
  return map
})
</script>

<style scoped>
.wf-card {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 12px;
  overflow: hidden;
  margin: 8px 12px;
  transition: border-color 240ms cubic-bezier(0.32, 0.72, 0, 1);
}
.wf-card:hover {
  border-color: var(--border-strong);
  border-left-color: var(--accent-2, var(--accent));
}
.wf-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border);
}
.wf-icon {
  font-size: 12px;
  color: var(--text-3);
  font-family: var(--font-mono);
}
.wf-name {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-1);
  letter-spacing: -0.01em;
}
.wf-status {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 500;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}
.wf-status.running {
  background: var(--accent-dim);
  color: var(--accent);
}
.wf-status.done {
  background: color-mix(in srgb, var(--success) 14%, transparent);
  color: var(--success);
}

.steps { padding: 8px 10px; }

.loop-iter {
  font-size: 11px;
  color: var(--text-3);
  padding: 4px 8px;
  font-family: var(--font-mono);
}
.cond {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  font-size: 11px;
}
.cond-icon { font-family: var(--font-mono); color: var(--success); }
.cond-expr { color: var(--text-3); font-family: var(--font-mono); }

.var-set {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  font-size: 11px;
}
.var-name { font-family: var(--font-mono); color: var(--accent); flex: 1; }
.var-type { color: var(--text-2); }
.var-size { color: var(--text-3); font-variant-numeric: tabular-nums; }
</style>

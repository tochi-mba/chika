<template>
  <div v-if="toolEvents.length" class="activity">
    <button class="activity-header" @click="expanded = !expanded" :class="{ running: isRunning }">
      <span class="activity-chevron" :class="{ open: expanded }">›</span>
      <span class="activity-summary">{{ summary }}</span>
      <span v-if="isRunning" class="activity-runner" />
    </button>

    <div class="activity-body" :class="{ open: expanded }">
      <div class="activity-rail">
        <ToolEventRow
          v-for="(event, idx) in toolEvents"
          :key="idx"
          :event="event"
          :live="isRunning && idx === toolEvents.length - 1"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import ToolEventRow from './ToolEventRow.vue'

const props = defineProps({
  toolEvents: { type: Array, default: () => [] },
  streaming:  { type: Boolean, default: false },
})

const expanded = ref(false)

const isRunning = computed(() =>
  props.streaming && !props.toolEvents.some(e => e.type === 'workflow_done')
)

const summary = computed(() => {
  const events = props.toolEvents
  const toolCount = events.filter(e => e.type === 'tool_call').length
  const stepCount = events.filter(e => e.type === 'step_done').length
  const done      = events.some(e  => e.type === 'workflow_done')

  if (isRunning.value) {
    const lastStep = [...events].reverse().find(e => e.type === 'step_start')
    return lastStep ? `running ${lastStep.step_id}…` : 'running…'
  }

  const parts = []
  if (stepCount > 0) parts.push(`${stepCount} step${stepCount !== 1 ? 's' : ''}`)
  if (toolCount > 0) parts.push(`${toolCount} tool${toolCount !== 1 ? 's' : ''}`)
  if (done) parts.push('done')
  return parts.length ? parts.join(' · ') : 'activity'
})
</script>

<style scoped>
.activity {
  margin-bottom: 10px;
}

/* ── Collapsed header ──────────────────────────────────────────────────────── */
.activity-header {
  display: flex;
  align-items: center;
  gap: 5px;
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 0;
  width: 100%;
  text-align: left;
}

.activity-chevron {
  font-size: 14px;
  color: var(--text-3, #4f4f6a);
  line-height: 1;
  transition: transform 150ms var(--ease, cubic-bezier(0.16, 1, 0.3, 1)),
              color 150ms;
  display: inline-block;
  user-select: none;
}
.activity-chevron.open {
  transform: rotate(90deg);
}
.activity-header:hover .activity-chevron {
  color: var(--text-2, #8888a2);
}

.activity-summary {
  font-size: 11.5px;
  color: var(--text-3, #4f4f6a);
  letter-spacing: 0.01em;
  transition: color 150ms;
}
.activity-header:hover .activity-summary {
  color: var(--text-2, #8888a2);
}
.activity-header.running .activity-summary {
  color: var(--accent, #6c63ff);
  opacity: 0.85;
}

/* Live pulse dot */
.activity-runner {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent, #6c63ff);
  flex-shrink: 0;
  animation: rpulse 1.4s ease-in-out infinite;
}
@keyframes rpulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.4; transform: scale(0.8); }
}

/* ── Expanded body ─────────────────────────────────────────────────────────── */
.activity-body {
  overflow: hidden;
  max-height: 0;
  transition: max-height 260ms var(--ease, cubic-bezier(0.16, 1, 0.3, 1));
}
.activity-body.open {
  max-height: 900px;
}

.activity-rail {
  margin-top: 8px;
  padding-left: 16px;
  border-left: 2px solid color-mix(in srgb, var(--accent, #6c63ff) 40%, transparent);
}
</style>

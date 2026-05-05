<template>
  <ul class="ptl">
    <li v-for="task in tasks" :key="task.id" class="ptl-row">
      <button class="ptl-tick" :class="`ptl-${task.status}`"
              :title="`Click to cycle: ${cycleHint(task.status)}`"
              @click="cycle(task)">
        <span v-if="task.status === 'done'">✓</span>
        <span v-else-if="task.status === 'in_progress'">…</span>
        <span v-else></span>
      </button>
      <span class="ptl-text" :class="`ptl-text-${task.status}`">
        {{ task.text }}
      </span>
      <span class="ptl-id" v-if="task.id">{{ task.id }}</span>

      <PlanTaskList
        v-if="task.subtasks?.length"
        :tasks="task.subtasks"
        :depth="depth + 1"
        @toggle="$emit('toggle', $event[0], $event[1])"
      />
    </li>
  </ul>
</template>

<script setup>
defineProps({
  tasks: { type: Array, required: true },
  depth: { type: Number, default: 0 },
})
const emit = defineEmits(['toggle'])

const NEXT = {
  pending:     'in_progress',
  in_progress: 'done',
  done:        'pending',
}

function cycle(task) {
  emit('toggle', task.id, NEXT[task.status] || 'pending')
}

function cycleHint(status) {
  return `${status} → ${NEXT[status] || 'pending'}`
}
</script>

<style scoped>
.ptl {
  list-style: none;
  margin: 0;
  padding: 0;
}
.ptl-row {
  display: grid;
  grid-template-columns: 18px 1fr auto;
  align-items: center;
  gap: 6px 8px;
  padding: 3px 0;
  position: relative;
}
.ptl-row > .ptl {
  grid-column: 1 / -1;
  margin-left: 18px;
  border-left: 1px solid var(--border, rgba(255,255,255,0.08));
  padding-left: 10px;
  margin-top: 2px;
}

.ptl-tick {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  border: 1.5px solid var(--text-3, #888);
  background: none;
  display: grid;
  place-items: center;
  cursor: pointer;
  font-size: 10px;
  color: var(--text-3);
  transition: all 120ms;
  padding: 0;
}
.ptl-tick:hover { border-color: var(--text-1, #ededf2); }

.ptl-pending     { color: var(--text-3, #888); }
.ptl-in_progress {
  color: var(--accent, #6c63ff);
  border-color: var(--accent, #6c63ff);
  background: var(--accent-dim, rgba(108, 99, 255, 0.12));
  animation: ptl-pulse 1.6s ease-in-out infinite;
}
.ptl-done {
  color: white;
  background: var(--green, #3dd68c);
  border-color: var(--green, #3dd68c);
}
@keyframes ptl-pulse {
  0%, 100% { transform: scale(1); }
  50%      { transform: scale(1.08); }
}

.ptl-text {
  font-size: 12.5px;
  color: var(--text-1, #ededf2);
  line-height: 1.4;
}
.ptl-text-done {
  color: var(--text-3, #888);
  text-decoration: line-through;
  text-decoration-color: rgba(136, 136, 162, 0.5);
}
.ptl-text-in_progress { color: var(--text-1); font-weight: 500; }

.ptl-id {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 9.5px;
  color: var(--text-3);
  background: var(--surface-2, #1c1c28);
  padding: 1px 5px;
  border-radius: 3px;
  white-space: nowrap;
}
</style>

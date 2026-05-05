<template>
  <div v-if="plan && plan.tasks?.length" class="plan-panel" :class="{ collapsed }">
    <header class="plan-head">
      <button class="plan-toggle" @click="collapsed = !collapsed"
              :aria-label="collapsed ? 'Expand plan' : 'Collapse plan'">
        <span class="plan-glyph">{{ collapsed ? '▸' : '▾' }}</span>
        <span class="plan-title">Plan</span>
        <span class="plan-progress">{{ doneLeaves }}/{{ totalLeaves }}</span>
        <div class="plan-bar" :title="`${pct}% complete`">
          <div class="plan-bar-fill" :style="{ width: pct + '%' }"/>
        </div>
      </button>

      <div v-if="!collapsed" class="plan-actions">
        <button class="plan-btn plan-btn-accept" @click="$emit('accept')"
                title="Tell the agent the plan is good — proceed">
          Accept
        </button>
        <button class="plan-btn plan-btn-edit" @click="editing = true"
                title="Send feedback to the agent so it tweaks the plan">
          Edit
        </button>
        <button class="plan-btn plan-btn-reject" @click="$emit('reject')"
                title="Reject this plan and ask the agent to start over">
          Reject
        </button>
      </div>
    </header>

    <section v-if="!collapsed" class="plan-body">
      <div v-if="plan.goal" class="plan-goal">
        <span class="plan-label">GOAL</span>
        <p>{{ plan.goal }}</p>
      </div>

      <div v-if="plan.requirements?.length" class="plan-reqs">
        <span class="plan-label">REQUIREMENTS</span>
        <ul>
          <li v-for="req in plan.requirements" :key="req">{{ req }}</li>
        </ul>
      </div>

      <div class="plan-tasks">
        <span class="plan-label">TASKS</span>
        <PlanTaskList :tasks="plan.tasks" :depth="0" @toggle="onToggle"/>
      </div>
    </section>

    <!-- Inline edit-feedback form ------------------------------------- -->
    <div v-if="editing" class="plan-edit-form">
      <textarea
        v-model="feedback"
        class="plan-edit-input"
        rows="3"
        placeholder="Tell the agent what to change — e.g. 'use TypeScript instead of JS', 'add a build step', 'drop t3.2'"
        ref="feedbackInput"
      />
      <div class="plan-edit-actions">
        <button class="plan-btn" @click="cancelEdit">Cancel</button>
        <button class="plan-btn plan-btn-accept" :disabled="!feedback.trim()"
                @click="submitEdit">Send to agent</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import PlanTaskList from './PlanTaskList.vue'

const props = defineProps({
  plan: { type: Object, default: null },
})
const emit = defineEmits(['accept', 'reject', 'edit-feedback', 'toggle-task'])

const collapsed = ref(false)
const editing = ref(false)
const feedback = ref('')
const feedbackInput = ref(null)

watch(editing, async (v) => {
  if (v) {
    await nextTick()
    feedbackInput.value?.focus()
  }
})

function _walkLeaves(tasks) {
  const out = []
  for (const t of tasks ?? []) {
    if (t?.subtasks?.length) {
      out.push(..._walkLeaves(t.subtasks))
    } else if (t) {
      out.push(t)
    }
  }
  return out
}

const leaves = computed(() => _walkLeaves(props.plan?.tasks ?? []))
const totalLeaves = computed(() => leaves.value.length || (props.plan?.tasks?.length ?? 0))
const doneLeaves = computed(() => leaves.value.filter(t => t.status === 'done').length)
const pct = computed(() => {
  if (!totalLeaves.value) return 0
  return Math.round(100 * doneLeaves.value / totalLeaves.value)
})

function onToggle(taskId, nextStatus) {
  emit('toggle-task', taskId, nextStatus)
}

function cancelEdit() {
  feedback.value = ''
  editing.value = false
}

function submitEdit() {
  const text = feedback.value.trim()
  if (!text) return
  emit('edit-feedback', text)
  feedback.value = ''
  editing.value = false
}
</script>

<style scoped>
.plan-panel {
  background: var(--surface-1, #14141d);
  border: 1px solid var(--border, rgba(255,255,255,0.08));
  border-radius: var(--radius, 9px);
  margin: 8px 12px;
  overflow: hidden;
  font-size: 13px;
  transition: border-color 200ms;
}
.plan-panel:hover {
  border-color: var(--border-strong, rgba(255,255,255,0.15));
}

.plan-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
}
.plan-panel.collapsed .plan-head { border-bottom: none; }

.plan-toggle {
  background: none;
  border: none;
  font: inherit;
  color: inherit;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0;
  cursor: pointer;
  flex: 1;
  text-align: left;
  min-width: 0;
}
.plan-glyph { color: var(--text-3, #888); font-size: 11px; }
.plan-title { font-weight: 600; color: var(--text-1, #ededf2); }
.plan-progress {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 11px;
  color: var(--text-3, #888);
  font-variant-numeric: tabular-nums;
}
.plan-bar {
  flex: 1;
  height: 4px;
  background: var(--surface-2, #1c1c28);
  border-radius: 999px;
  overflow: hidden;
  max-width: 240px;
}
.plan-bar-fill {
  height: 100%;
  background: var(--accent, #6c63ff);
  transition: width 220ms cubic-bezier(0.16, 1, 0.3, 1);
  border-radius: 999px;
}

.plan-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.plan-btn {
  background: none;
  border: 1px solid var(--border, rgba(255,255,255,0.08));
  color: var(--text-2, #8888a2);
  font: inherit;
  font-size: 11.5px;
  padding: 4px 10px;
  border-radius: var(--radius-sm, 5px);
  cursor: pointer;
  transition: all 120ms;
}
.plan-btn:hover { color: var(--text-1, #ededf2); border-color: var(--border-strong); }
.plan-btn-accept { color: var(--green, #3dd68c); border-color: var(--green, #3dd68c); }
.plan-btn-accept:hover { background: var(--green-dim, rgba(61, 214, 140, 0.12)); }
.plan-btn-accept:disabled { opacity: 0.4; cursor: not-allowed; }
.plan-btn-edit { color: var(--accent, #6c63ff); border-color: var(--accent, #6c63ff); }
.plan-btn-edit:hover { background: var(--accent-dim, rgba(108, 99, 255, 0.12)); }
.plan-btn-reject { color: var(--red, #e05c5c); border-color: var(--red, #e05c5c); }
.plan-btn-reject:hover { background: var(--red-dim, rgba(224, 92, 92, 0.12)); }

.plan-body {
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.plan-label {
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-3, #888);
  display: block;
  margin-bottom: 4px;
}

.plan-goal p {
  margin: 0;
  font-size: 13px;
  color: var(--text-1, #ededf2);
  line-height: 1.5;
}

.plan-reqs ul {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.plan-reqs li {
  color: var(--text-2, #8888a2);
  line-height: 1.5;
}

.plan-edit-form {
  padding: 10px 14px 12px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--surface-2, #1c1c28);
}
.plan-edit-input {
  font: inherit;
  font-size: 12.5px;
  background: var(--surface-1, #14141d);
  color: var(--text-1, #ededf2);
  border: 1px solid var(--border, rgba(255,255,255,0.08));
  border-radius: var(--radius-sm, 5px);
  padding: 8px 10px;
  resize: vertical;
  min-height: 60px;
  outline: none;
  transition: border-color 120ms;
}
.plan-edit-input:focus { border-color: var(--accent, #6c63ff); }
.plan-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}
</style>

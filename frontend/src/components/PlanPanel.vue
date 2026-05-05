<template>
  <div v-if="plan && plan.tasks?.length" class="plan-panel" :class="{ collapsed }">
    <header class="plan-head">
      <button class="plan-toggle" @click="collapsed = !collapsed"
              :aria-label="collapsed ? 'Expand plan' : 'Collapse plan'">
        <div class="plan-icon" aria-hidden="true">P</div>
        <div class="plan-meta">
          <span class="plan-title">Plan</span>
          <span class="plan-subtitle">{{ doneLeaves }}/{{ totalLeaves }} tasks</span>
        </div>
        <div class="plan-bar-wrap" :title="`${pct}% complete`">
          <div class="plan-bar"><div class="plan-bar-fill" :style="{ width: pct + '%' }"/></div>
          <span class="plan-pct">{{ pct }}%</span>
        </div>
        <span class="plan-chevron" :class="{ open: !collapsed }">▾</span>
      </button>

      <div v-if="!collapsed" class="plan-actions">
        <button class="plan-btn plan-btn-reject" @click="$emit('reject')"
                title="Reject this plan and ask the agent to start over">
          ✕ Reject
        </button>
        <button class="plan-btn plan-btn-edit" @click="editing = true"
                title="Send feedback to the agent so it tweaks the plan">
          ✎ Edit
        </button>
        <button class="plan-btn plan-btn-accept" @click="$emit('accept')"
                title="Tell the agent the plan is good — proceed">
          ✓ Approve
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
/*
 * Plan panel — v0 design system port. Header: P-avatar + title +
 * progress bar + actions. Body: GOAL / REQUIREMENTS / TASKS sections
 * with caps-spaced labels, comfortable whitespace, hairline dividers.
 */
.plan-panel {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 14px;
  margin: 8px 12px;
  overflow: hidden;
  font-size: 13px;
  transition: border-color 200ms var(--spring);
}
.plan-panel:hover { border-color: var(--border-strong); }

.plan-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.plan-panel.collapsed .plan-head { border-bottom: none; }

.plan-toggle {
  background: none;
  border: none;
  font: inherit;
  color: inherit;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0;
  cursor: pointer;
  flex: 1;
  text-align: left;
  min-width: 0;
}

.plan-icon {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--accent-dim);
  color: var(--accent);
  display: grid;
  place-items: center;
  font-weight: 600;
  font-size: 13px;
  letter-spacing: -0.02em;
}

.plan-meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.plan-title {
  font-weight: 600;
  font-size: 13.5px;
  color: var(--text-1);
  letter-spacing: -0.005em;
}
.plan-subtitle {
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

.plan-bar-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  margin-right: 4px;
}
.plan-bar {
  width: 96px;
  height: 6px;
  background: var(--surface-2);
  border-radius: 999px;
  overflow: hidden;
}
.plan-bar-fill {
  height: 100%;
  background: var(--success);
  transition: width 280ms var(--spring);
  border-radius: 999px;
}
.plan-pct {
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  min-width: 32px;
  text-align: right;
}
.plan-chevron {
  font-size: 11px;
  color: var(--text-3);
  transition: transform 200ms var(--spring);
}
.plan-chevron.open { transform: rotate(180deg); }
@media (max-width: 640px) {
  .plan-bar-wrap { display: none; }
}

.plan-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.plan-btn {
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-2);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 140ms var(--spring);
  white-space: nowrap;
}
.plan-btn:hover {
  color: var(--text-1);
  border-color: var(--border-strong);
  transform: translateY(-1px);
}
.plan-btn-accept {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.plan-btn-accept:hover {
  background: var(--accent-2);
  border-color: var(--accent-2);
  color: #fff;
}
.plan-btn-accept:disabled { opacity: 0.5; cursor: not-allowed; }
.plan-btn-edit { color: var(--accent); border-color: var(--accent); background: transparent; }
.plan-btn-edit:hover {
  background: var(--accent-dim);
  color: var(--accent);
}
.plan-btn-reject {
  color: var(--text-3);
  border-color: var(--border);
  background: transparent;
}
.plan-btn-reject:hover {
  color: var(--error);
  border-color: var(--error);
  background: var(--red-dim);
}

.plan-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.plan-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  color: var(--text-3);
  display: block;
  margin-bottom: 6px;
  text-transform: uppercase;
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

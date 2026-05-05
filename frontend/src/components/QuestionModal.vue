<template>
  <Teleport to="body">
    <div class="overlay" v-if="props.questions.length > 0">
      <div
        class="modal"
        v-for="q in props.questions"
        :key="q.request_id"
      >
        <!-- Header chip -->
        <div class="modal-header">
          <span class="icon">❓</span>
          <span class="title">Chika has a question</span>
          <span v-if="q.header" class="header-chip">{{ q.header }}</span>
        </div>

        <!-- Question text -->
        <p class="question-text">{{ q.question }}</p>

        <!-- Options -->
        <div class="options">
          <button
            v-for="(opt, i) in q.options"
            :key="i"
            class="option"
            :class="{ 'selected': isSelected(q, i) }"
            @click="toggle(q, i)"
          >
            <div class="option-head">
              <span class="option-dot" />
              <span class="option-label">{{ opt.label }}</span>
            </div>
            <div v-if="opt.description" class="option-desc">{{ opt.description }}</div>
          </button>
        </div>

        <!-- Notes -->
        <textarea
          v-model="notes[q.request_id]"
          class="notes"
          placeholder="Notes (optional)…"
          rows="2"
        />

        <!-- Submit -->
        <div class="actions">
          <button
            class="btn primary"
            :disabled="!canSubmit(q)"
            @click="submit(q)"
          >
            {{ q.multi_select ? 'Submit' : 'Confirm' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  questions: { type: Array, required: true },
})
const emit = defineEmits(['answer'])

// Per-question selection state (indices)
const selections = ref({})  // request_id → Set<index> (or single index wrapped)
const notes       = ref({})

function isSelected(q, i) {
  const sel = selections.value[q.request_id]
  if (!sel) return false
  return sel.has(i)
}

function toggle(q, i) {
  if (!selections.value[q.request_id]) {
    selections.value[q.request_id] = new Set()
  }
  const sel = selections.value[q.request_id]
  if (q.multi_select) {
    if (sel.has(i)) sel.delete(i)
    else sel.add(i)
  } else {
    sel.clear()
    sel.add(i)
  }
  // Trigger reactivity
  selections.value = { ...selections.value }
}

function canSubmit(q) {
  const sel = selections.value[q.request_id]
  return sel && sel.size > 0
}

function submit(q) {
  const sel = selections.value[q.request_id]
  if (!sel || sel.size === 0) return
  const indices = [...sel]
  const labels  = indices.map(i => q.options[i]?.label || '')
  const payload = q.multi_select
    ? {
        choice: labels.join(', '),
        choice_index: indices[0] ?? -1,
        choices: labels,
        choice_indices: indices,
        notes: notes.value[q.request_id] || '',
      }
    : {
        choice: labels[0] || '',
        choice_index: indices[0],
        notes: notes.value[q.request_id] || '',
      }
  emit('answer', q.request_id, payload)
  // Clear local state for this question
  delete selections.value[q.request_id]
  delete notes.value[q.request_id]
}
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 24px;
  backdrop-filter: blur(2px);
}
.modal {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 24px 28px;
  width: min(540px, 100%);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.18);
  animation: pop 160ms var(--spring);
}
:root.dark .modal {
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
}
@keyframes pop {
  from { transform: scale(0.94); opacity: 0; }
  to   { transform: scale(1);    opacity: 1; }
}

.modal-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.icon        { font-size: 18px; }
.title {
  font-size: 13px;
  color: var(--text-2);
  font-weight: 600;
  letter-spacing: -0.01em;
}
.header-chip {
  margin-left: auto;
  font-size: 10px;
  background: var(--accent-dim);
  color: var(--accent);
  padding: 2px 8px;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 500;
}

.question-text {
  font-size: 15px;
  line-height: 1.5;
  color: var(--text-1);
  margin: 4px 0 18px;
  letter-spacing: -0.01em;
}

.options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 14px;
}
.option {
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-1);
  font: inherit;
  text-align: left;
  padding: 11px 13px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 140ms var(--spring);
}
.option:hover {
  border-color: var(--border-strong);
  transform: translateY(-1px);
}
.option.selected {
  background: var(--accent-dim);
  border-color: var(--accent);
}

.option-head {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  font-weight: 500;
}
.option-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid var(--text-3);
  display: inline-block;
  flex-shrink: 0;
  transition: all 140ms var(--spring);
}
.option:hover .option-dot { border-color: var(--accent); }
.option.selected .option-dot {
  background: var(--accent);
  border-color: var(--accent);
  box-shadow: inset 0 0 0 3px var(--surface-1);
}

.option-desc {
  margin-top: 4px;
  margin-left: 24px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.45;
}
.option.selected .option-desc { color: var(--text-2); }

.notes {
  width: 100%;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-1);
  border-radius: 8px;
  padding: 9px 11px;
  font: inherit;
  font-size: 12.5px;
  resize: vertical;
  margin-bottom: 14px;
  transition: border-color 140ms var(--spring);
}
.notes:focus {
  outline: none;
  border-color: var(--accent);
}

.actions {
  display: flex;
  justify-content: flex-end;
}
.btn {
  padding: 9px 20px;
  border: 1px solid var(--accent);
  border-radius: 8px;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 140ms var(--spring), border-color 140ms var(--spring);
}
.btn.primary {
  background: var(--accent);
  color: #fff;
}
.btn.primary:hover:not(:disabled) {
  background: var(--accent-2);
  border-color: var(--accent-2);
}
.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>

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
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: #1a1a24;
  border: 1px solid #2a2a38;
  border-radius: 14px;
  padding: 22px 24px;
  width: min(540px, 92vw);
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.45);
}
.modal-header {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 12px;
}
.icon        { font-size: 18px; }
.title       { font-size: 13px; color: #b0b0c8; font-weight: 600; }
.header-chip {
  margin-left: auto;
  font-size: 10px;
  background: #2a2a40;
  color: #a6a6c8;
  padding: 2px 8px;
  border-radius: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.question-text {
  font-size: 15px;
  line-height: 1.45;
  color: #e8e8f0;
  margin: 4px 0 16px;
}

.options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 14px;
}
.option {
  background: #12121a;
  border: 1px solid #2a2a38;
  color: #d0d0e0;
  text-align: left;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.option:hover {
  background: #18182a;
  border-color: #3a3a50;
}
.option.selected {
  background: #2a2550;
  border-color: #6c63ff;
}
.option-head {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 13px;
  font-weight: 500;
}
.option-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1.5px solid #6c63ff;
  display: inline-block;
}
.option.selected .option-dot { background: #6c63ff; }
.option-desc {
  margin-top: 4px;
  margin-left: 19px;
  font-size: 11.5px;
  color: #9898b0;
  line-height: 1.4;
}

.notes {
  width: 100%;
  background: #12121a;
  border: 1px solid #2a2a38;
  color: #e8e8f0;
  border-radius: 8px;
  padding: 7px 9px;
  font-size: 12px;
  font-family: inherit;
  resize: vertical;
  margin-bottom: 12px;
}
.notes:focus {
  outline: none;
  border-color: #6c63ff;
}

.actions {
  display: flex;
  justify-content: flex-end;
}
.btn {
  padding: 8px 18px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, opacity 0.15s;
}
.btn.primary {
  background: #6c63ff;
  color: #fff;
}
.btn.primary:hover:not(:disabled) { background: #7a71ff; }
.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>

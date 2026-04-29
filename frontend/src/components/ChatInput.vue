<template>
  <div class="input-bar">
    <div class="input-box" :class="{ focused, disabled: disabled && !streaming }">
      <textarea
        ref="textarea"
        v-model="text"
        :disabled="disabled && !streaming"
        placeholder="Message Chika…"
        rows="1"
        @keydown.enter.exact.prevent="submit"
        @keydown.enter.shift.exact="newline"
        @input="autoResize"
        @focus="focused = true"
        @blur="focused = false"
      />

      <!-- Stop button shown while streaming -->
      <button
        v-if="streaming"
        class="stop-btn"
        @click="$emit('stop')"
        title="Stop generation (Esc)"
        aria-label="Stop generation"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
          <rect x="2" y="2" width="10" height="10" rx="2"/>
        </svg>
      </button>

      <!-- Send button shown otherwise -->
      <button
        v-else
        class="send-btn"
        :disabled="disabled || !text.trim()"
        @click="submit"
        title="Send (Enter)"
        aria-label="Send message"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="19" x2="12" y2="5"/>
          <polyline points="5 12 12 5 19 12"/>
        </svg>
      </button>
    </div>
    <div class="input-hint">Shift+Enter for newline · Esc to stop</div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  disabled:  Boolean,
  streaming: Boolean,
})
const emit = defineEmits(['send', 'stop'])

const text     = ref('')
const textarea = ref(null)
const focused  = ref(false)

function submit() {
  const msg = text.value.trim()
  if (!msg || props.disabled) return
  emit('send', msg)
  text.value = ''
  nextTick(() => autoResize())
}

function newline() {
  text.value += '\n'
  nextTick(() => autoResize())
}

function autoResize() {
  const el = textarea.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 180) + 'px'
}

function onKeydown(e) {
  if (e.key === 'Escape' && props.streaming) {
    emit('stop')
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.input-bar {
  flex-shrink: 0;
  padding: 10px 16px 14px;
  background: var(--bg, #09090d);
  border-top: 1px solid var(--border, rgba(255,255,255,0.07));
}

.input-box {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: var(--surface-1, #111117);
  border: 1.5px solid var(--border, rgba(255,255,255,0.07));
  border-radius: var(--radius-lg, 14px);
  padding: 9px 10px 9px 14px;
  transition: border-color 180ms var(--ease, cubic-bezier(0.16, 1, 0.3, 1)),
              box-shadow 180ms var(--ease, cubic-bezier(0.16, 1, 0.3, 1));
}

.input-box.focused {
  border-color: var(--accent, #6c63ff);
  box-shadow: 0 0 0 3px var(--accent-dim, rgba(108,99,255,0.15));
}

.input-box.disabled {
  opacity: 0.5;
}

textarea {
  flex: 1;
  resize: none;
  background: none;
  border: none;
  outline: none;
  font-family: inherit;
  font-size: 14px;
  color: var(--text-1, #ededf2);
  line-height: 1.6;
  min-height: 24px;
  max-height: 180px;
  padding: 0;
  letter-spacing: -0.004em;
}

textarea::placeholder {
  color: var(--text-3, #4f4f6a);
}

textarea:disabled {
  cursor: not-allowed;
}

.send-btn {
  width: 34px;
  height: 34px;
  border-radius: var(--radius, 9px);
  border: none;
  background: var(--accent, #6c63ff);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 150ms, opacity 150ms, transform 100ms;
}

.send-btn:not(:disabled):hover { background: #7c74ff; }
.send-btn:not(:disabled):active { transform: scale(0.93); }
.send-btn:disabled {
  background: var(--surface-3, #20202a);
  color: var(--text-3, #4f4f6a);
  cursor: not-allowed;
}

.stop-btn {
  width: 34px;
  height: 34px;
  border-radius: var(--radius, 9px);
  border: 1.5px solid var(--border, rgba(255,255,255,0.12));
  background: var(--surface-2, #18181f);
  color: var(--text-2, #a0a0b8);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 150ms, color 150ms, transform 100ms;
}

.stop-btn:hover {
  background: var(--surface-3, #20202a);
  color: var(--text-1, #ededf2);
}

.stop-btn:active { transform: scale(0.93); }

.input-hint {
  margin-top: 5px;
  padding-left: 4px;
  font-size: 11px;
  color: var(--text-3, #4f4f6a);
  user-select: none;
}
</style>

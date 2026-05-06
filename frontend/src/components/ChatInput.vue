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
        <svg width="13" height="13" viewBox="0 0 14 14" fill="currentColor">
          <rect x="3" y="3" width="8" height="8" rx="1.5"/>
        </svg>
        <span>Stop</span>
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
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
          <path d="M12.5 7L1.5 1.5V5.5L7 7L1.5 8.5V12.5L12.5 7Z" fill="currentColor"/>
        </svg>
        <span>Send</span>
      </button>
    </div>
    <div class="input-hint">Press Enter to send · Shift+Enter for newline · Esc to stop</div>
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
  if (msg.length > 32_000) return
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
  padding: 12px 16px 16px;
  background: var(--bg);
  border-top: 1px solid var(--border);
}

.input-box {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 12px 12px 12px 16px;
  transition: border-color 240ms cubic-bezier(0.32, 0.72, 0, 1),
              box-shadow 240ms cubic-bezier(0.32, 0.72, 0, 1),
              background 240ms cubic-bezier(0.32, 0.72, 0, 1);
}

.input-box:hover { border-color: var(--border-strong); }

.input-box.focused {
  border-color: color-mix(in srgb, var(--accent) 50%, transparent);
  background: color-mix(in srgb, var(--surface-1) 96%, var(--accent) 4%);
  box-shadow: 0 0 0 3px var(--accent-dim);
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
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 14px;
  border-radius: 10px;
  border: none;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: #fff;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.005em;
  flex-shrink: 0;
  box-shadow: 0 4px 14px color-mix(in srgb, var(--accent) 30%, transparent);
  transition: background 240ms cubic-bezier(0.32, 0.72, 0, 1),
              transform 120ms cubic-bezier(0.32, 0.72, 0, 1),
              box-shadow 240ms cubic-bezier(0.32, 0.72, 0, 1);
}

.send-btn:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 18px color-mix(in srgb, var(--accent) 40%, transparent);
}
.send-btn:not(:disabled):active { transform: translateY(0) scale(0.97); }
.send-btn:disabled {
  background: var(--surface-2);
  color: var(--text-3);
  cursor: not-allowed;
  box-shadow: none;
}

.stop-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-2);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.005em;
  flex-shrink: 0;
  transition: color 240ms cubic-bezier(0.32, 0.72, 0, 1),
              border-color 240ms cubic-bezier(0.32, 0.72, 0, 1),
              background 240ms cubic-bezier(0.32, 0.72, 0, 1),
              transform 120ms cubic-bezier(0.32, 0.72, 0, 1);
}

.stop-btn:hover {
  border-color: var(--error);
  color: var(--error);
  background: color-mix(in srgb, var(--error) 8%, transparent);
}

.stop-btn:active { transform: scale(0.96); }

.input-hint {
  margin-top: 6px;
  padding-left: 4px;
  font-size: 11px;
  color: var(--text-3);
  user-select: none;
}
</style>

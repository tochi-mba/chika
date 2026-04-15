<template>
  <div class="chat-input">
    <textarea
      ref="textarea"
      v-model="text"
      :disabled="disabled"
      placeholder="Message Chika…"
      rows="1"
      @keydown.enter.exact.prevent="submit"
      @keydown.enter.shift.exact="newline"
      @input="autoResize"
    />
    <button :disabled="disabled || !text.trim()" @click="submit">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="22" y1="2" x2="11" y2="13"/>
        <polygon points="22 2 15 22 11 13 2 9 22 2"/>
      </svg>
    </button>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'

const props = defineProps({ disabled: Boolean })
const emit  = defineEmits(['send'])

const text     = ref('')
const textarea = ref(null)

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
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}
</script>

<style scoped>
.chat-input {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 12px 16px;
  background: #16161a;
  border-top: 1px solid #2a2a35;
}
textarea {
  flex: 1;
  resize: none;
  background: #1e1e28;
  border: 1px solid #2a2a35;
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 14px;
  color: #e8e8f0;
  line-height: 1.5;
  min-height: 40px;
  max-height: 200px;
  outline: none;
  transition: border-color 0.15s;
}
textarea:focus { border-color: #6c63ff; }
textarea:disabled { opacity: 0.4; cursor: not-allowed; }
button {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: #6c63ff;
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s, opacity 0.15s;
}
button:disabled { background: #333; opacity: 0.4; cursor: not-allowed; }
button:not(:disabled):hover { background: #7c72ff; }
button svg { width: 18px; height: 18px; }
</style>

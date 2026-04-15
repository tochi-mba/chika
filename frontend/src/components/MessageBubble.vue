<template>
  <div class="message" :class="message.role">
    <div class="bubble">
      <span class="text" v-html="formattedText" />
      <span v-if="message.streaming" class="cursor" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  message: { type: Object, required: true }
})

// Very simple markdown: bold, code, newlines
function escape(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
}

const formattedText = computed(() => {
  let t = escape(props.message.text || '')
  // Code blocks
  t = t.replace(/```[\s\S]*?```/g, m => `<pre><code>${m.slice(3, -3).replace(/^[^\n]*\n/, '')}</code></pre>`)
  // Inline code
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>')
  // Bold
  t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  // Newlines
  t = t.replace(/\n/g, '<br/>')
  return t
})
</script>

<style scoped>
.message {
  display: flex;
  padding: 6px 16px;
}
.message.user     { justify-content: flex-end; }
.message.assistant { justify-content: flex-start; }

.bubble {
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.6;
  word-wrap: break-word;
}
.message.user .bubble {
  background: #6c63ff;
  color: #fff;
  border-bottom-right-radius: 4px;
}
.message.assistant .bubble {
  background: #1e1e28;
  color: #e8e8f0;
  border-bottom-left-radius: 4px;
  border: 1px solid #2a2a35;
}

.cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  background: #6c63ff;
  margin-left: 2px;
  vertical-align: text-bottom;
  animation: blink 0.8s steps(1) infinite;
}
@keyframes blink { 0%,100% { opacity:1 } 50% { opacity:0 } }

:deep(code) { background: #111; padding: 1px 5px; border-radius: 4px; font-family: monospace; font-size: 13px; }
:deep(pre)  { background: #111; padding: 10px; border-radius: 8px; margin: 6px 0; overflow-x: auto; }
:deep(pre code) { padding: 0; background: none; }
:deep(strong) { font-weight: 600; }
</style>

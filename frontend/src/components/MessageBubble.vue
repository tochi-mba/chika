<template>
  <div v-if="message.role === 'compaction'" class="compaction-divider">
    <div class="compaction-line" />
    <div class="compaction-label">
      <span class="compaction-icon">⚡</span>
      Context compacted — {{ message.removed }} messages summarised
    </div>
    <div class="compaction-line" />
  </div>
  <div v-else class="message" :class="message.role">
    <div class="bubble">
      <!-- Extended-thinking panel (collapsible, only on assistant bubbles) -->
      <details v-if="message.role === 'assistant' && message.thinking" class="thinking">
        <summary>
          <span class="thinking-icon">🧠</span>
          <span>Reasoning</span>
          <span class="thinking-meta">{{ message.thinking.length }} chars</span>
        </summary>
        <pre class="thinking-body">{{ message.thinking }}</pre>
      </details>

      <span class="text" v-html="formattedText" />
      <span v-if="message.streaming" class="cursor" />

      <!-- Grounding warnings (ungrounded URLs, fabricated citations) -->
      <div v-if="message.role === 'assistant' && message.warnings?.length" class="warnings">
        <div
          v-for="(w, i) in message.warnings"
          :key="i"
          class="warning"
          :class="w.severity || 'medium'"
        >
          <div class="warning-head">
            <span class="warning-icon">⚠</span>
            <span class="warning-reason">{{ formatReason(w.reason) }}</span>
          </div>
          <div class="warning-msg">{{ w.message }}</div>
          <div v-if="w.urls?.length" class="warning-urls">
            <div v-for="u in w.urls" :key="u">{{ u }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  message: { type: Object, required: true }
})

function formatReason(r) {
  if (!r) return 'Warning'
  return r.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

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

.compaction-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  margin: 4px 0;
}
.compaction-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(to right, transparent, #3a3a50, transparent);
}
.compaction-label {
  font-size: 11px;
  color: #6c63ff99;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 5px;
  user-select: none;
}
.compaction-icon { font-size: 12px; }

/* ── Thinking panel ─────────────────────────────────────────────────────── */
.thinking {
  margin-bottom: 8px;
  border-radius: 8px;
  background: #12121a;
  border: 1px solid #2a2a35;
  font-size: 12px;
}
.thinking summary {
  cursor: pointer;
  padding: 6px 10px;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #8a8aa5;
  user-select: none;
}
.thinking summary::-webkit-details-marker { display: none; }
.thinking summary:hover { color: #c0c0d8; }
.thinking-icon { font-size: 13px; }
.thinking-meta {
  margin-left: auto;
  font-size: 10px;
  opacity: 0.7;
  font-family: monospace;
}
.thinking-body {
  margin: 0;
  padding: 8px 12px 12px;
  font-family: ui-monospace, 'SF Mono', Consolas, monospace;
  font-size: 11.5px;
  color: #a0a0c0;
  white-space: pre-wrap;
  word-wrap: break-word;
  border-top: 1px solid #2a2a35;
  line-height: 1.55;
}

/* ── Grounding warnings ─────────────────────────────────────────────────── */
.warnings {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.warning {
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12px;
  border: 1px solid;
}
.warning.high {
  background: #2b1a1a;
  border-color: #9a4646;
  color: #f0caca;
}
.warning.medium {
  background: #2b241a;
  border-color: #9a7e46;
  color: #f0e0ca;
}
.warning-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  margin-bottom: 3px;
}
.warning-icon { font-size: 13px; }
.warning-msg { line-height: 1.5; opacity: 0.9; }
.warning-urls {
  margin-top: 6px;
  font-family: ui-monospace, 'SF Mono', Consolas, monospace;
  font-size: 11px;
  opacity: 0.8;
  word-break: break-all;
}
</style>

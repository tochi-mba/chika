<template>
  <div v-if="message.role === 'compaction'" class="compaction-divider">
    <div class="compaction-line" />
    <div class="compaction-label">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
      Context compacted — {{ message.removed }} messages summarised
    </div>
    <div class="compaction-line" />
  </div>

  <div v-else class="message" :class="[message.role, { 'is-streaming': message.streaming }]">
    <div class="avatar" :class="message.role + '-avatar'" aria-hidden="true">
      <ChikaMark
        v-if="message.role === 'assistant'"
        :size="18"
        :state="message.streaming ? 'streaming' : 'idle'"
      />
      <span v-else class="avatar-letter">U</span>
    </div>
    <div class="bubble" :class="message.role + '-bubble'">

      <!-- Inline tool activity timeline (above thinking + text) -->
      <InlineActivity
        v-if="message.role === 'assistant' && message.toolEvents?.length"
        :tool-events="message.toolEvents"
        :streaming="message.streaming"
      />

      <!-- Extended-thinking panel -->
      <details v-if="message.role === 'assistant' && message.thinking" class="thinking">
        <summary>
          <svg class="thinking-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
          <span>Reasoning</span>
          <span class="thinking-meta">{{ message.thinking.length }} chars</span>
        </summary>
        <pre class="thinking-body">{{ message.thinking }}</pre>
      </details>

      <!-- Main text content -->
      <div v-if="message.text" class="prose" v-html="formattedText" />
      <div
        v-else-if="message.streaming && !message.toolEvents?.length"
        class="thinking-indicator"
      >
        <ChikaMark :size="14" state="streaming" />
        <span>Thinking…</span>
      </div>
      <span v-if="message.streaming && message.text" class="cursor" />

      <!-- Browser screenshots (from browser_screenshot tool results) -->
      <div v-if="screenshotResults.length" class="screenshots">
        <div
          v-for="shot in screenshotResults"
          :key="shot._ts"
          class="screenshot-block"
        >
          <img
            :src="`data:image/${shot.format || 'png'};base64,${shot.image}`"
            class="screenshot-img"
            alt="Browser screenshot"
          />
          <div class="screenshot-meta">{{ shot.title || '' }}{{ shot.url ? ' · ' + shot.url : '' }}</div>
        </div>
      </div>

      <!-- Grounding warnings -->
      <div v-if="message.role === 'assistant' && message.warnings?.length" class="warnings">
        <div
          v-for="(w, i) in message.warnings"
          :key="i"
          class="warning"
          :class="w.severity || 'medium'"
        >
          <div class="warning-head">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
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
import InlineActivity from './InlineActivity.vue'
import ChikaMark from './ChikaMark.vue'

const props = defineProps({
  message: { type: Object, required: true }
})

// Extract screenshot tool results from the toolEvents array
const screenshotResults = computed(() => {
  if (!props.message.toolEvents) return []
  return props.message.toolEvents
    .filter(e => e.type === 'tool_result' && e.tool === 'browser_screenshot' && e.result?.image)
    .map(e => e.result)
})

function formatReason(r) {
  if (!r) return 'Warning'
  return r.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// ── Markdown renderer ─────────────────────────────────────────────────────────
function escape(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

const formattedText = computed(() => {
  let text = props.message.text || ''

  // 1. Extract fenced code blocks before escaping (preserve raw code)
  const codeBlocks = []
  text = text.replace(/```([\w-]*)\r?\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = codeBlocks.length
    const content = escape(code.replace(/\n$/, ''))
    const label = lang
      ? `<div class="code-label">${escape(lang)}</div>`
      : ''
    codeBlocks.push(
      `<div class="code-block">${label}<pre><code>${content}</code></pre></div>`
    )
    return `\x00CB${idx}\x00`
  })

  // 2. Escape remaining HTML
  text = escape(text)

  // 3. Inline code
  text = text.replace(/`([^`\n]+)`/g, '<code>$1</code>')

  // 4. Line-by-line: headings, lists, HR
  const lines = text.split('\n')
  const out = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]

    if (/^### /.test(line))      { out.push(`<h3>${line.slice(4)}</h3>`); i++; continue }
    if (/^## /.test(line))       { out.push(`<h2>${line.slice(3)}</h2>`); i++; continue }
    if (/^# /.test(line))        { out.push(`<h1>${line.slice(2)}</h1>`); i++; continue }
    if (/^-{3,}$/.test(line.trim())) { out.push('<hr>'); i++; continue }

    if (/^[-*] /.test(line)) {
      const items = []
      while (i < lines.length && /^[-*] /.test(lines[i])) {
        items.push(`<li>${lines[i].slice(2)}</li>`)
        i++
      }
      out.push(`<ul>${items.join('')}</ul>`)
      continue
    }

    if (/^\d+\. /.test(line)) {
      const items = []
      while (i < lines.length && /^\d+\. /.test(lines[i])) {
        items.push(`<li>${lines[i].replace(/^\d+\. /, '')}</li>`)
        i++
      }
      out.push(`<ol>${items.join('')}</ol>`)
      continue
    }

    out.push(line)
    i++
  }
  text = out.join('\n')

  // 5. Inline bold, italic, links
  text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  text = text.replace(/\*([^*\n]+)\*/g, '<em>$1</em>')
  text = text.replace(/_([^_\n]+)_/g, '<em>$1</em>')
  text = text.replace(
    /\[([^\]\n]+)\]\((https?:\/\/[^)\n]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  )

  // 6. Restore code blocks
  codeBlocks.forEach((block, idx) => {
    text = text.replace(`\x00CB${idx}\x00`, block)
  })

  // 7. Newlines → <br> (outside block elements)
  text = text.replace(/\n/g, '<br>')

  return text
})
</script>

<style scoped>
/* ── Message layout — avatar + bubble row ──────────────────────────────── */
.message {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 6px 20px;
}
.message.user      { flex-direction: row-reverse; }
.message.assistant { flex-direction: row; }

.avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  margin-top: 2px;
  transition: transform 240ms cubic-bezier(0.32, 0.72, 0, 1);
}
.assistant-avatar {
  /* primary/10 — subtle accent tint that reads as a "Chika" badge
     without competing with the trefoil glyph inside */
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  color: var(--accent);
  border: 1px solid color-mix(in srgb, var(--accent) 18%, transparent);
  transition: transform 240ms cubic-bezier(0.32, 0.72, 0, 1),
              box-shadow 240ms cubic-bezier(0.32, 0.72, 0, 1);
}
.message.is-streaming .assistant-avatar {
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 14%, transparent);
  animation: assistant-pulse 1.6s ease-in-out infinite;
}
@keyframes assistant-pulse {
  0%, 100% { box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 12%, transparent); }
  50%      { box-shadow: 0 0 0 6px color-mix(in srgb, var(--accent) 20%, transparent); }
}

.thinking-indicator {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-3);
  letter-spacing: -0.005em;
}
.user-avatar {
  background: var(--accent);
  color: #fff;
  box-shadow: 0 4px 14px color-mix(in srgb, var(--accent) 30%, transparent);
}
.avatar-letter {
  font-weight: 600;
  font-size: 12px;
  letter-spacing: -0.01em;
}

/* ── Bubbles ─────────────────────────────────────────────────────────────── */
.bubble {
  max-width: 80%;
  padding: 14px 18px;
  font-size: 14px;
  line-height: 1.65;
  word-wrap: break-word;
  letter-spacing: -0.004em;
}

/* Assistant: card surface + border + asymmetric top-left corner so the
   bubble visually points at the avatar (matches the canonical design). */
.assistant-bubble {
  background: var(--surface-1, var(--surface, #14161c));
  color: var(--text-1, var(--text, #ededf2));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  border-radius: 16px;
  border-top-left-radius: 6px;
  transition: border-color 240ms cubic-bezier(0.32, 0.72, 0, 1);
}
.assistant-bubble:hover {
  border-color: var(--border-strong, var(--border-hover, rgba(255, 255, 255, 0.10)));
}

/* User: accent-filled, asymmetric top-right corner. */
.user-bubble {
  background: linear-gradient(135deg, var(--accent), var(--accent-2, #7c70ff));
  color: #fff;
  border-radius: 16px;
  border-top-right-radius: 6px;
  box-shadow: 0 4px 16px color-mix(in srgb, var(--accent) 25%, transparent);
}

/* ── Streaming cursor ─────────────────────────────────────────────────────── */
.cursor, .cursor-only {
  display: inline-block;
  width: 6px;
  height: 1em;
  background: var(--accent, #6c63ff);
  margin-left: 3px;
  vertical-align: text-bottom;
  border-radius: 2px;
  animation: blink 0.9s steps(1) infinite;
}
.cursor-only {
  display: block;
  margin: 2px 0;
}
@keyframes blink { 0%, 100% { opacity: 1 } 50% { opacity: 0 } }

/* ── Prose (markdown output) ──────────────────────────────────────────────── */
.prose :deep(h1) {
  font-size: 1.2em;
  font-weight: 600;
  letter-spacing: -0.02em;
  margin: 14px 0 6px;
  color: var(--text-1, #ededf2);
}
.prose :deep(h2) {
  font-size: 1.05em;
  font-weight: 600;
  letter-spacing: -0.015em;
  margin: 12px 0 5px;
  color: var(--text-1, #ededf2);
}
.prose :deep(h3) {
  font-size: 1em;
  font-weight: 500;
  margin: 10px 0 4px;
  color: var(--text-1, #ededf2);
}
.prose :deep(ul),
.prose :deep(ol) {
  padding-left: 20px;
  margin: 5px 0;
}
.prose :deep(li) {
  margin: 3px 0;
  line-height: 1.65;
}
.prose :deep(strong) { font-weight: 600; }
.prose :deep(em)     { font-style: italic; opacity: 0.9; }
.prose :deep(a) {
  color: var(--accent);
  text-decoration: none;
  transition: color 120ms;
}
.prose :deep(a:hover) {
  color: var(--accent-2);
  text-decoration: underline;
}
.prose :deep(hr) {
  border: none;
  border-top: 1px solid var(--border, rgba(255,255,255,0.07));
  margin: 14px 0;
}
.prose :deep(.code-block) {
  position: relative;
  margin: 10px 0;
}
.prose :deep(.code-label) {
  position: absolute;
  top: 8px;
  right: 10px;
  font-size: 10px;
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  color: var(--text-3, #4f4f6a);
  letter-spacing: 0.03em;
  user-select: none;
  pointer-events: none;
}
.prose :deep(pre) {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 5px);
  padding: 12px 14px;
  margin: 10px 0;
  overflow-x: auto;
}
.prose :deep(code) {
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 12.5px;
  line-height: 1.6;
}
/* Inline code (not in pre) */
.prose :deep(:not(pre) > code) {
  background: var(--surface-2);
  border: 1px solid var(--border);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12.5px;
  color: var(--accent);
}
/* User bubble overrides — bubble already has dark accent bg, so code blocks
   need a slightly darker tint and lighter borders to stay legible. */
.user-bubble .prose :deep(a) {
  color: rgba(255, 255, 255, 0.92);
  text-decoration: underline;
  text-decoration-color: rgba(255, 255, 255, 0.4);
}
.user-bubble .prose :deep(code),
.user-bubble .prose :deep(pre) {
  background: rgba(0, 0, 0, 0.22);
  border-color: rgba(255, 255, 255, 0.18);
  color: rgba(255, 255, 255, 0.92);
}

/* ── Thinking panel ──────────────────────────────────────────────────────── */
.thinking {
  margin-bottom: 10px;
  border-radius: var(--radius-sm, 5px);
  background: var(--surface-2);
  border: 1px solid var(--border);
  font-size: 12px;
}
.thinking summary {
  cursor: pointer;
  padding: 6px 10px;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-3, #4f4f6a);
  user-select: none;
  transition: color 120ms;
}
.thinking summary::-webkit-details-marker { display: none; }
.thinking summary:hover { color: var(--text-2, #8888a2); }
.thinking-icon { flex-shrink: 0; }
.thinking-meta {
  margin-left: auto;
  font-size: 10px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  opacity: 0.6;
}
.thinking-body {
  margin: 0;
  padding: 8px 12px 12px;
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 11.5px;
  color: var(--text-2, #8888a2);
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid var(--border, rgba(255,255,255,0.07));
  line-height: 1.55;
}

/* ── Warnings ────────────────────────────────────────────────────────────── */
.warnings {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.warning {
  border-radius: var(--radius-sm, 5px);
  padding: 8px 10px;
  font-size: 12px;
  border: 1px solid;
}
.warning.high {
  background: color-mix(in srgb, var(--error) 10%, transparent);
  border-color: color-mix(in srgb, var(--error) 30%, transparent);
  color: var(--error);
}
.warning.medium {
  background: color-mix(in srgb, var(--warn) 10%, transparent);
  border-color: color-mix(in srgb, var(--warn) 30%, transparent);
  color: var(--warn);
}
.warning-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
  margin-bottom: 4px;
}
.warning-reason { font-size: 12px; }
.warning-msg { line-height: 1.5; opacity: 0.9; }
.warning-urls {
  margin-top: 5px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px;
  opacity: 0.75;
  word-break: break-all;
}

/* ── Screenshots ─────────────────────────────────────────────────────────── */
.screenshots {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
}
.screenshot-block {
  border-radius: var(--radius-sm, 5px);
  overflow: hidden;
  border: 1px solid var(--border, rgba(255,255,255,0.07));
}
.screenshot-img {
  width: 100%;
  display: block;
  border-radius: var(--radius-sm, 5px) var(--radius-sm, 5px) 0 0;
  max-height: 400px;
  object-fit: cover;
  object-position: top;
}
.screenshot-meta {
  padding: 5px 8px;
  font-size: 10px;
  color: var(--text-3, #4f4f6a);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  background: rgba(0,0,0,0.2);
}

/* ── Compaction divider ──────────────────────────────────────────────────── */
.compaction-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 20px;
  margin: 4px 0;
}
.compaction-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(to right, transparent, var(--border-strong, rgba(255,255,255,0.12)), transparent);
}
.compaction-label {
  font-size: 11px;
  color: var(--text-3, #4f4f6a);
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 5px;
  user-select: none;
}
</style>

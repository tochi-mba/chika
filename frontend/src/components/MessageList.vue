<template>
  <div class="message-list-wrapper">
    <div class="message-list" ref="container" @scroll="onScroll">
      <div v-if="messages.length === 0" class="empty">
        <ChikaMark :size="48" state="idle" class="empty-mark" />
        <h2 class="empty-heading">How can I help?</h2>
        <p class="empty-sub">
          I can browse the web, write and execute code, manage files, and
          help you accomplish complex tasks. Just ask.
        </p>
        <div class="quick-prompts">
          <button
            v-for="p in quickPrompts"
            :key="p"
            class="quick-prompt"
            @click="$emit('quick-prompt', p)"
          >{{ p }}</button>
        </div>
      </div>
      <MessageBubble v-for="msg in messages" :key="msg.id" :message="msg" />
      <div ref="anchor" style="height: 1px;" />
    </div>

    <!-- Jump to bottom FAB — inside wrapper so position:absolute works -->
    <Transition name="fab">
      <button
        v-if="showFab"
        class="jump-btn"
        @click="scrollToBottom(true)"
        aria-label="Jump to bottom"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
        <span>Jump to bottom</span>
      </button>
    </Transition>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import MessageBubble from './MessageBubble.vue'
import ChikaMark from './ChikaMark.vue'

const props = defineProps({
  messages:    { type: Array,   default: () => [] },
  isStreaming: { type: Boolean, default: false },
})

defineEmits(['quick-prompt'])

const quickPrompts = [
  'Help me debug this error',
  'Create a new component',
  'Search the web for…',
  'Explain this code',
]

const container = ref(null)
const anchor    = ref(null)
const showFab   = ref(false)

function isNearBottom() {
  const el = container.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

function onScroll() {
  showFab.value = !isNearBottom()
}

function scrollToBottom(smooth = false) {
  nextTick(() => {
    anchor.value?.scrollIntoView({ behavior: smooth ? 'smooth' : 'instant' })
    showFab.value = false
  })
}

// Auto-scroll only when near bottom or actively streaming
watch(
  () => props.messages,
  () => {
    nextTick(() => {
      if (isNearBottom() || props.isStreaming) {
        anchor.value?.scrollIntoView({ behavior: 'instant' })
        showFab.value = false
      } else {
        showFab.value = true
      }
    })
  },
  { deep: true }
)
</script>

<style scoped>
.message-list-wrapper {
  flex: 1;
  overflow: hidden;
  position: relative;
  display: flex;
  flex-direction: column;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 28px 0 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--text-3);
  padding: 48px 32px 80px;
  text-align: center;
}
.empty-mark { margin-bottom: 8px; }
.empty-heading {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  color: var(--text-1);
  letter-spacing: -0.02em;
}
.empty-sub {
  margin: 0;
  font-size: 14px;
  color: var(--text-2);
  max-width: 440px;
  line-height: 1.55;
  letter-spacing: -0.005em;
}

.quick-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 24px;
  justify-content: center;
}

.quick-prompt {
  padding: 8px 16px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-2);
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  letter-spacing: -0.005em;
  transition: color 240ms cubic-bezier(0.32, 0.72, 0, 1),
              background 240ms cubic-bezier(0.32, 0.72, 0, 1),
              border-color 240ms cubic-bezier(0.32, 0.72, 0, 1),
              transform 200ms cubic-bezier(0.32, 0.72, 0, 1);
}
.quick-prompt:hover {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 6%, var(--surface-1));
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  transform: translateY(-1px);
}

/* Jump to bottom button */
.jump-btn {
  position: absolute;
  bottom: 14px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 7px 14px 7px 11px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-2);
  cursor: pointer;
  white-space: nowrap;
  font-family: inherit;
  letter-spacing: -0.005em;
  transition: background 240ms cubic-bezier(0.32, 0.72, 0, 1),
              color 240ms cubic-bezier(0.32, 0.72, 0, 1),
              border-color 240ms cubic-bezier(0.32, 0.72, 0, 1),
              transform 200ms cubic-bezier(0.32, 0.72, 0, 1),
              box-shadow 240ms cubic-bezier(0.32, 0.72, 0, 1);
  z-index: 10;
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.18),
              0 0 0 1px color-mix(in srgb, var(--accent) 4%, transparent);
  backdrop-filter: blur(8px);
}
.jump-btn:hover {
  background: var(--surface-2);
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  transform: translateX(-50%) translateY(-1px);
}

/* FAB enter/leave transition */
.fab-enter-active,
.fab-leave-active {
  transition: opacity 200ms cubic-bezier(0.32, 0.72, 0, 1),
              transform 240ms cubic-bezier(0.32, 0.72, 0, 1);
}
.fab-enter-from,
.fab-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(8px) scale(0.96);
}
</style>

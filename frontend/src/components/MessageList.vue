<template>
  <div class="message-list-wrapper">
    <div class="message-list" ref="container" @scroll="onScroll">
      <div v-if="messages.length === 0" class="empty">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="none" stroke="#4f4f6a" stroke-width="1.5" stroke-linejoin="round"/>
        </svg>
        <p>Send a message to start</p>
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

const props = defineProps({
  messages:    { type: Array,   default: () => [] },
  isStreaming: { type: Boolean, default: false },
})

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
  gap: 12px;
  color: var(--text-3, #4f4f6a);
  padding-bottom: 80px;
}
.empty p {
  font-size: 13px;
  letter-spacing: -0.01em;
}

/* Jump to bottom button */
.jump-btn {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 5px;
  background: var(--surface-2, #18181f);
  border: 1px solid var(--border-strong, rgba(255,255,255,0.12));
  border-radius: 999px;
  padding: 6px 13px 6px 10px;
  font-size: 12px;
  color: var(--text-2, #8888a2);
  cursor: pointer;
  white-space: nowrap;
  font-family: inherit;
  transition: background 150ms, color 150ms, border-color 150ms;
  z-index: 10;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}
.jump-btn:hover {
  background: var(--surface-3, #20202a);
  color: var(--text-1, #ededf2);
  border-color: rgba(108,99,255,0.4);
}

/* FAB enter/leave transition */
.fab-enter-active,
.fab-leave-active {
  transition: opacity 180ms, transform 220ms var(--ease, cubic-bezier(0.16, 1, 0.3, 1));
}
.fab-enter-from,
.fab-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(10px);
}
</style>

<template>
  <div class="state-indicator" :class="{ compact, 'is-active': isActive }">
    <div class="triangles" aria-hidden="true">
      <span
        v-for="(t, i) in triangles"
        :key="i"
        class="tri"
        :class="{ on: isActive && i === activeIndex }"
      >{{ t }}</span>
    </div>
    <span v-if="!compact && showVerb" class="verb">{{ isActive ? verb : 'Ready' }}</span>
    <span
      v-if="!compact && showTimer && isActive"
      class="timer"
    >{{ formatTime(elapsedSeconds) }}</span>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import { useChatStore } from '../stores/chat'
import { useSystemStore } from '../stores/system'

defineProps({
  compact:   { type: Boolean, default: false },
  showVerb:  { type: Boolean, default: true },
  showTimer: { type: Boolean, default: true },
})

const chat   = useChatStore()
const system = useSystemStore()

const triangles = ['◣', '▲', '◢']
const activeIndex = ref(0)
const elapsedSeconds = ref(0)

const isActive = computed(() => chat.isStreaming || !!system.activeWorkflow)

const verb = computed(() => {
  if (chat.isStreaming) return 'Streaming'
  if (system.activeWorkflow?.name) return system.activeWorkflow.name
  if (system.activeWorkflow) return 'Working'
  return 'Ready'
})

let triTimer = null
let timeTimer = null
let startedAt = 0

watch(isActive, (active) => {
  if (active) {
    startedAt = Date.now()
    elapsedSeconds.value = 0
    triTimer = setInterval(() => {
      activeIndex.value = (activeIndex.value + 1) % 3
    }, 700)
    timeTimer = setInterval(() => {
      elapsedSeconds.value = Math.floor((Date.now() - startedAt) / 1000)
    }, 1000)
  } else {
    if (triTimer) { clearInterval(triTimer); triTimer = null }
    if (timeTimer) { clearInterval(timeTimer); timeTimer = null }
    activeIndex.value = 0
    elapsedSeconds.value = 0
  }
}, { immediate: true })

onUnmounted(() => {
  if (triTimer)  clearInterval(triTimer)
  if (timeTimer) clearInterval(timeTimer)
})

function formatTime(s) {
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${String(r).padStart(2, '0')}`
}
</script>

<style scoped>
.state-indicator {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 11px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  transition: border-color 240ms cubic-bezier(0.32, 0.72, 0, 1),
              background 240ms cubic-bezier(0.32, 0.72, 0, 1);
}
.state-indicator.is-active {
  border-color: color-mix(in srgb, var(--accent) 28%, var(--border));
  background: color-mix(in srgb, var(--accent) 5%, var(--surface-2));
}
.state-indicator.compact {
  padding: 0;
  background: none;
  border: none;
  gap: 4px;
}

.triangles {
  display: inline-flex;
  gap: 3px;
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1;
}
.state-indicator.compact .triangles { font-size: 11px; gap: 2px; }

.tri {
  color: var(--text-3);
  opacity: 0.32;
  transition: color 200ms cubic-bezier(0.32, 0.72, 0, 1),
              opacity 200ms cubic-bezier(0.32, 0.72, 0, 1),
              transform 200ms cubic-bezier(0.32, 0.72, 0, 1);
}
.tri.on {
  color: var(--accent);
  opacity: 1;
  transform: scale(1.12);
}

.verb {
  font-size: 12.5px;
  color: var(--text-1);
  font-weight: 500;
  letter-spacing: -0.005em;
  min-width: 70px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.timer {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  margin-left: auto;
}
</style>

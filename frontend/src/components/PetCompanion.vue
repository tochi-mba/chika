<template>
  <div
    v-if="active && active.id"
    class="pet-companion"
    :class="{ 'pet-working': state === 'working' || state === 'thinking',
              'pet-celebrate': state === 'celebrate',
              'pet-sad': state === 'sad',
              'pet-bubble-open': !!bubble }"
    :style="{ '--pet-accent': active.accent || 'var(--accent)' }"
    @click="$emit('open-settings', 'pet')"
    :title="`${active.name} — click to change`"
  >
    <transition name="bubble">
      <div v-if="bubble" class="pet-bubble">{{ bubble }}</div>
    </transition>

    <div class="pet-body">
      <pre v-if="currentFrame" class="pet-ascii">{{ currentFrame }}</pre>
      <span v-else class="pet-emoji">{{ active.emoji || '🐾' }}</span>
      <div class="pet-shadow"/>
    </div>

    <div class="pet-name">{{ shortName }}</div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useSystemStore } from '../stores/system'

defineEmits(['open-settings'])

const system = useSystemStore()

const catalogue = ref([])
const defaultId = ref('cat')

async function loadCatalogue() {
  try {
    const token = localStorage.getItem('chika_api_key') || ''
    const headers = token ? { 'Authorization': `Bearer ${token}` } : {}
    const res = await fetch('/api/pets', { headers })
    if (!res.ok) return
    const data = await res.json()
    catalogue.value = data.pets || []
    defaultId.value = data.default || 'cat'
  } catch {/* silent */}
}
onMounted(loadCatalogue)

const active = computed(() => {
  const id = system.profile.pet_id || defaultId.value
  return catalogue.value.find(p => p.id === id) || null
})

const shortName = computed(() => active.value?.name?.split(' ')?.[0] || '')

// Bubble auto-dismiss after 4s of inactivity. The store updates petState
// on every relevant event so we just mirror it locally.
const bubble = ref('')
let bubbleTimer = null

watch(() => system.petState.bubble, (next) => {
  if (next) {
    bubble.value = next
    if (bubbleTimer) clearTimeout(bubbleTimer)
    bubbleTimer = setTimeout(() => { bubble.value = '' }, 4000)
  }
})

onUnmounted(() => {
  if (bubbleTimer) clearTimeout(bubbleTimer)
  if (frameTimer)  clearInterval(frameTimer)
})

const state = computed(() => system.petState.state || 'idle')

// ── ASCII frame cycling ───────────────────────────────────────────────
// The backend ships per-state frame arrays for each pet (see chika/_cli/pets.py
// and /api/pets). We mirror the CLI's animator: tick faster while the pet is
// "working" so typing animations actually look like typing, slower while idle
// so blinks don't seizure-flash. Switching state resets the frame index so
// the first frame of the new state always appears immediately.
const frameIdx = ref(0)
let frameTimer = null

const currentFrames = computed(() => {
  const frames = active.value?.frames
  if (!frames || typeof frames !== 'object') return []
  return frames[state.value] || frames.idle || []
})

const currentFrame = computed(() => {
  const list = currentFrames.value
  if (!list.length) return ''
  return list[frameIdx.value % list.length]
})

function startTicker() {
  if (frameTimer) clearInterval(frameTimer)
  // Idle: 700ms (slow blink). Working: 200ms (fast typing). Other: 350ms.
  const delay = state.value === 'working' ? 200
              : state.value === 'idle'    ? 700
              : 350
  frameTimer = setInterval(() => {
    frameIdx.value = (frameIdx.value + 1) % Math.max(currentFrames.value.length, 1)
  }, delay)
}

watch(state, () => {
  frameIdx.value = 0
  startTicker()
}, { immediate: false })

watch(currentFrames, () => {
  // Catalogue may load after mount — kick off the ticker once frames arrive.
  if (currentFrames.value.length && !frameTimer) startTicker()
})

onMounted(() => {
  // Fire after the catalogue fetch resolves; if it's already cached the
  // computed re-evaluates immediately.
  startTicker()
})
</script>

<style scoped>
.pet-companion {
  position: fixed;
  right: 18px;
  bottom: 70px;
  z-index: 90;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  padding: 8px;
  user-select: none;
  transition: transform 200ms var(--ease, cubic-bezier(0.16, 1, 0.3, 1));
}
.pet-companion:hover {
  transform: translateY(-2px);
}

.pet-body {
  position: relative;
  width: auto;
  min-width: 84px;
  height: auto;
  min-height: 56px;
  display: grid;
  place-items: center;
  animation: pet-bob 3.5s ease-in-out infinite;
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.12));
}
:root.dark .pet-body { filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.3)); }

.pet-emoji {
  font-size: 40px;
  line-height: 1;
  display: block;
  transform-origin: 50% 80%;
}

/* ASCII pet rendering — same artwork the CLI shows. Monospace, tight
   line-height, accent-tinted on hover, and crucially `white-space: pre`
   so spaces in the artwork survive intact. */
.pet-ascii {
  margin: 0;
  font-family: var(--font-mono, ui-monospace, "SF Mono", "JetBrains Mono", monospace);
  font-size: 9.5px;
  line-height: 10px;
  letter-spacing: 0;
  color: var(--text-1);
  white-space: pre;
  user-select: none;
  text-shadow: 0 0 6px color-mix(in srgb, var(--accent) 22%, transparent);
  transition: color 200ms var(--spring);
}
.pet-companion.pet-celebrate .pet-ascii { color: var(--success); }
.pet-companion.pet-sad       .pet-ascii { color: var(--error); opacity: 0.85; }
.pet-companion.pet-working   .pet-ascii { color: var(--pet-accent, var(--accent)); }

.pet-shadow {
  position: absolute;
  bottom: -4px;
  left: 50%;
  width: 38px;
  height: 6px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.22);
  filter: blur(3px);
  transform: translateX(-50%);
  animation: pet-shadow 3.5s ease-in-out infinite;
}
:root.dark .pet-shadow { background: rgba(0, 0, 0, 0.45); }

.pet-name {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-3);
  background: var(--surface-1);
  padding: 3px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  font-family: var(--font-mono);
}

/* ── Speech bubble ───────────────────────────────────────────────────── */
.pet-bubble {
  position: absolute;
  bottom: 100%;
  right: -8px;
  margin-bottom: 8px;
  background: var(--pet-accent, var(--accent));
  color: #fff;
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 12px;
  white-space: nowrap;
  max-width: 220px;
  text-overflow: ellipsis;
  overflow: hidden;
  font-weight: 500;
  letter-spacing: -0.01em;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.18);
}
:root.dark .pet-bubble { box-shadow: 0 8px 20px rgba(0, 0, 0, 0.4); }

.pet-bubble::after {
  content: '';
  position: absolute;
  bottom: -5px;
  right: 24px;
  width: 10px;
  height: 10px;
  background: var(--pet-accent, var(--accent));
  transform: rotate(45deg);
  border-radius: 2px;
}

/* ── State animations ────────────────────────────────────────────────── */
@keyframes pet-bob {
  0%, 100% { transform: translateY(0); }
  50%      { transform: translateY(-4px); }
}
@keyframes pet-shadow {
  0%, 100% { transform: translateX(-50%) scale(1.0); opacity: 0.35; }
  50%      { transform: translateX(-50%) scale(0.85); opacity: 0.18; }
}

.pet-working .pet-body {
  animation: pet-work 0.55s ease-in-out infinite alternate;
}
@keyframes pet-work {
  from { transform: translateY(-2px) rotate(-6deg); }
  to   { transform: translateY( 0px) rotate( 6deg); }
}

.pet-celebrate .pet-body {
  animation: pet-bounce 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) 3;
}
@keyframes pet-bounce {
  0%, 100% { transform: translateY(0)    scale(1);   }
  35%      { transform: translateY(-14px) scale(1.06); }
  70%      { transform: translateY(0)    scale(0.96); }
}

.pet-sad .pet-emoji {
  filter: grayscale(0.5);
  animation: pet-sad-wobble 1.6s ease-in-out infinite;
}
@keyframes pet-sad-wobble {
  0%, 100% { transform: rotate(-3deg) translateY(0); }
  50%      { transform: rotate( 3deg) translateY(2px); }
}

/* Glow ring while a tool is running */
.pet-working .pet-body::before,
.pet-celebrate .pet-body::before {
  content: '';
  position: absolute;
  inset: -6px;
  border-radius: 50%;
  border: 2px solid var(--pet-accent, var(--accent));
  opacity: 0.55;
  animation: pet-glow 1.4s ease-in-out infinite;
}
@keyframes pet-glow {
  0%, 100% { transform: scale(0.92); opacity: 0.55; }
  50%      { transform: scale(1.06); opacity: 0.20; }
}

/* Bubble enter/leave */
.bubble-enter-from, .bubble-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.9);
}
.bubble-enter-active, .bubble-leave-active {
  transition: opacity 240ms ease, transform 240ms cubic-bezier(0.34, 1.56, 0.64, 1);
}
</style>

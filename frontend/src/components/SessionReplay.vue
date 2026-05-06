<template>
  <!--
    SessionReplay — replays a recorded session (ADR-35) into the
    current chat surface. Lists known sessions, lets the user pick
    one, scrubs through the timeline, and dispatches events into
    the engine event handler — the same path live events take.

    Backend contract:
      GET  /api/sessions          -> { sessions: [{id, started_at, message_count}, ...] }
      GET  /api/sessions/<id>     -> { events: [{type, ts, ...}, ...] }
  -->
  <Teleport to="body">
    <div v-if="open" class="overlay" @click.self="$emit('close')">
      <div class="replay" role="dialog" aria-modal="true" aria-label="Session replay">
        <header class="header">
          <h2 class="title">Session replay</h2>
          <button class="close" @click="$emit('close')" aria-label="Close">✕</button>
        </header>

        <div class="body">
          <!-- Session picker -->
          <aside class="picker">
            <p class="picker-label">Recorded sessions</p>
            <ul class="session-list">
              <li
                v-for="s in sessions"
                :key="s.id"
                :class="{ active: selectedId === s.id }"
                @click="selectSession(s.id)"
              >
                <span class="session-id">{{ s.id }}</span>
                <span class="session-meta">
                  {{ s.message_count }} events
                  <span v-if="s.started_at">· {{ formatDate(s.started_at) }}</span>
                </span>
              </li>
              <li v-if="sessions.length === 0 && !loading" class="empty">
                no recorded sessions yet — chat once, then try again.
              </li>
              <li v-else-if="loading" class="empty">loading…</li>
            </ul>
          </aside>

          <!-- Timeline + controls -->
          <main class="stage">
            <div v-if="!selectedId" class="placeholder">
              pick a session on the left.
            </div>
            <template v-else>
              <div class="timeline">
                <div class="scrubber">
                  <input
                    type="range"
                    min="0"
                    :max="events.length"
                    :value="cursor"
                    @input="onScrub($event)"
                    aria-label="Replay timeline"
                  />
                </div>
                <div class="ticks">
                  <span>{{ cursor }} / {{ events.length }} events</span>
                  <span class="elapsed">{{ formatElapsed() }}</span>
                </div>
              </div>

              <div class="controls">
                <button class="btn" @click="rewind" :disabled="cursor === 0">
                  ⟲ rewind
                </button>
                <button class="btn primary" @click="togglePlay" :disabled="events.length === 0">
                  {{ playing ? '⏸ pause' : '▶ play' }}
                </button>
                <button class="btn" @click="step" :disabled="cursor >= events.length">
                  ⤃ step
                </button>
                <label class="speed">
                  Speed
                  <select v-model.number="speed">
                    <option :value="0.25">0.25×</option>
                    <option :value="0.5">0.5×</option>
                    <option :value="1">1×</option>
                    <option :value="2">2×</option>
                    <option :value="4">4×</option>
                    <option :value="0">instant</option>
                  </select>
                </label>
              </div>

              <div class="event-preview">
                <p class="preview-label">Event @ cursor</p>
                <pre v-if="events[cursor - 1]" class="preview-pre">{{
                  formatEvent(events[cursor - 1])
                }}</pre>
                <p v-else class="empty">— start of session —</p>
              </div>

              <div class="histogram">
                <p class="preview-label">Event types</p>
                <ul class="histogram-list">
                  <li v-for="[type, count] in eventHistogram" :key="type">
                    <span class="hist-type">{{ type }}</span>
                    <span class="hist-bar">
                      <span class="hist-fill" :style="{ width: histPct(count) + '%' }"></span>
                    </span>
                    <span class="hist-count">{{ count }}</span>
                  </li>
                </ul>
              </div>
            </template>
          </main>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  /**
   * Function called for each event during playback. The chat-store's
   * dispatch shape (event-typed) is the natural fit. Tests inject
   * a jest.fn() to assert dispatch order.
   */
  dispatch: { type: Function, required: false, default: null },
})
defineEmits(['close'])

const sessions = ref([])
const loading = ref(false)
const selectedId = ref(null)
const events = ref([])
const cursor = ref(0)
const playing = ref(false)
const speed = ref(1)

let playTimer = null

async function loadSessions() {
  loading.value = true
  try {
    const res = await fetch('/api/sessions')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    sessions.value = data.sessions || []
  } catch (err) {
    console.warn('[chika] sessions list failed:', err)
    sessions.value = []
  } finally {
    loading.value = false
  }
}

async function selectSession(id) {
  selectedId.value = id
  events.value = []
  cursor.value = 0
  stopPlay()
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(id)}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    events.value = data.events || []
  } catch (err) {
    console.warn('[chika] session load failed:', err)
    events.value = []
  }
}

function step() {
  if (cursor.value >= events.value.length) return
  const ev = events.value[cursor.value]
  cursor.value += 1
  if (props.dispatch && ev) {
    try { props.dispatch(ev) } catch (err) {
      console.warn('[chika] replay dispatch raised:', err)
    }
  }
}

function rewind() {
  stopPlay()
  cursor.value = 0
}

function togglePlay() {
  if (playing.value) {
    stopPlay()
  } else {
    startPlay()
  }
}

function startPlay() {
  if (events.value.length === 0) return
  if (cursor.value >= events.value.length) cursor.value = 0
  playing.value = true
  scheduleNext()
}

function stopPlay() {
  playing.value = false
  if (playTimer) {
    clearTimeout(playTimer)
    playTimer = null
  }
}

function scheduleNext() {
  if (!playing.value || cursor.value >= events.value.length) {
    stopPlay()
    return
  }
  // Speed=0 means "instant" — flush in a single tick.
  if (speed.value === 0) {
    while (cursor.value < events.value.length) step()
    stopPlay()
    return
  }
  step()
  // Inter-event delay: derive from timestamps in the event log if
  // present; otherwise use a fixed 80 ms cadence so the UI animates.
  const prev = events.value[cursor.value - 2]
  const cur = events.value[cursor.value - 1]
  let delay = 80
  if (prev && cur && prev.ts && cur.ts) {
    const dt = (Date.parse(cur.ts) - Date.parse(prev.ts))
    if (Number.isFinite(dt) && dt > 0) {
      delay = Math.min(2000, dt) / Math.max(0.01, speed.value)
    } else {
      delay = 80 / Math.max(0.01, speed.value)
    }
  } else {
    delay = 80 / Math.max(0.01, speed.value)
  }
  playTimer = setTimeout(scheduleNext, delay)
}

function onScrub(e) {
  stopPlay()
  const target = Number(e.target.value)
  // Forward scrub: dispatch any newly-passed events.
  // Backward scrub: caller can reset by hitting rewind.
  while (cursor.value < target) step()
  cursor.value = target
}

function formatDate(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleString()
  } catch { return iso }
}

function formatElapsed() {
  if (events.value.length < 2 || cursor.value === 0) return '—'
  const first = events.value[0]
  const ev = events.value[cursor.value - 1]
  if (!first?.ts || !ev?.ts) return '—'
  const diff = Math.max(0, (Date.parse(ev.ts) - Date.parse(first.ts)) / 1000)
  if (diff < 60) return `${diff.toFixed(1)}s`
  return `${(diff / 60).toFixed(1)}m`
}

function formatEvent(ev) {
  if (!ev) return ''
  return JSON.stringify(ev, null, 2)
}

const eventHistogram = computed(() => {
  const counts = new Map()
  for (const e of events.value) {
    const t = (e && e.type) || 'unknown'
    counts.set(t, (counts.get(t) || 0) + 1)
  }
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])
})

function histPct(count) {
  const max = events.value.length || 1
  return Math.min(100, (count / max) * 100)
}

watch(() => props.open, (open) => {
  if (open) loadSessions()
  if (!open) stopPlay()
})

onMounted(() => {
  if (props.open) loadSessions()
})

onBeforeUnmount(stopPlay)
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(11, 12, 16, 0.7);
  backdrop-filter: blur(8px);
  z-index: 60;
  display: grid;
  place-items: center;
}

.replay {
  width: min(1100px, 95vw);
  height: min(720px, 90vh);
  background: var(--surface, #14161c);
  border: 1px solid var(--border-hover, rgba(255, 255, 255, 0.10));
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.4);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 22px;
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.06));
}
.title { font-size: 16px; font-weight: 600; letter-spacing: -0.01em; }
.close {
  background: none; border: none;
  color: var(--muted, #a8a8b8);
  padding: 4px 10px; border-radius: 6px;
  font-size: 18px; cursor: pointer;
}
.close:hover { background: rgba(255, 255, 255, 0.05); }

.body { flex: 1; display: grid; grid-template-columns: 280px 1fr; min-height: 0; }
.picker {
  border-right: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  padding: 14px 16px;
  overflow-y: auto;
}
.picker-label, .preview-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted, #a8a8b8);
  margin: 0 0 8px;
}
.session-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.session-list li {
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 12.5px;
  color: var(--muted, #a8a8b8);
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid transparent;
}
.session-list li:hover { background: rgba(255, 255, 255, 0.03); color: var(--text, #ededf2); }
.session-list li.active {
  background: rgba(108, 99, 255, 0.08);
  border-color: rgba(108, 99, 255, 0.3);
  color: var(--text, #ededf2);
}
.session-id {
  font-family: var(--font-mono, "SF Mono", Menlo, monospace);
  font-size: 11.5px;
}
.session-meta { font-size: 11px; color: var(--dim, #6b6b85); }
.empty { color: var(--muted, #a8a8b8); font-size: 12px; padding: 8px 10px; font-style: italic; }

.stage {
  padding: 18px 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
}
.placeholder { color: var(--muted, #a8a8b8); padding: 32px 0; text-align: center; }

.timeline { display: flex; flex-direction: column; gap: 6px; }
.scrubber input[type="range"] { width: 100%; accent-color: var(--accent, #6c63ff); }
.ticks {
  display: flex;
  justify-content: space-between;
  color: var(--muted, #a8a8b8);
  font-size: 11px;
  font-family: var(--font-mono, "SF Mono", Menlo, monospace);
}
.elapsed { color: var(--accent, #6c63ff); }

.controls {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
  flex-wrap: wrap;
}
.btn {
  background: var(--bg, #0b0c10);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  color: var(--text, #ededf2);
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.18s ease;
}
.btn:hover:not(:disabled) {
  border-color: var(--border-hover, rgba(255, 255, 255, 0.10));
  background: var(--surface-2, #1a1d25);
}
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn.primary {
  background: linear-gradient(135deg, var(--accent, #6c63ff), var(--accent-2, #7c70ff));
  border-color: transparent;
  color: white;
}

.speed {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--muted, #a8a8b8);
}
.speed select {
  background: var(--bg, #0b0c10);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  color: var(--text, #ededf2);
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
}

.event-preview { display: flex; flex-direction: column; gap: 6px; }
.preview-pre {
  background: var(--bg, #0b0c10);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  border-radius: 8px;
  padding: 12px 14px;
  font-family: var(--font-mono, "SF Mono", Menlo, monospace);
  font-size: 12px;
  max-height: 220px;
  overflow: auto;
  margin: 0;
}

.histogram { display: flex; flex-direction: column; gap: 6px; }
.histogram-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
.histogram-list li {
  display: grid;
  grid-template-columns: 160px 1fr 48px;
  gap: 10px;
  align-items: center;
  font-size: 12px;
}
.hist-type { font-family: var(--font-mono, monospace); color: var(--muted, #a8a8b8); }
.hist-bar {
  height: 8px;
  background: var(--bg, #0b0c10);
  border-radius: 4px;
  overflow: hidden;
}
.hist-fill {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--accent, #6c63ff), var(--accent-2, #7c70ff));
}
.hist-count { text-align: right; font-family: var(--font-mono, monospace); color: var(--dim, #6b6b85); }

@media (max-width: 720px) {
  .body { grid-template-columns: 1fr; }
  .picker { max-height: 180px; }
}

@media (prefers-reduced-motion: reduce) {
  .replay *, .replay { transition: none !important; animation: none !important; }
}
</style>

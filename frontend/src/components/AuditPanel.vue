<template>
  <!--
    Audit panel — surfaces the contents of data/audit.jsonl
    (ADR-34) in a Linear-inbox-style scannable list.

    Backend fetch: GET /api/audit?limit=200
      Returns: { entries: [{ts, kind, actor, tool, category, decision, ...}, ...] }

    Filters are client-side (lists are small — typical user has < 1000
    audit lines per session). Search is substring across tool +
    category + reason fields.
  -->
  <div class="audit-panel" v-if="open">
    <header class="audit-header">
      <h2 class="title">Activity log</h2>
      <button class="close" @click="$emit('close')" aria-label="Close audit panel">✕</button>
    </header>

    <div class="audit-controls">
      <div class="filter-row">
        <label class="filter">
          <span>Kind</span>
          <select v-model="filterKind">
            <option value="all">all</option>
            <option value="approval">approval</option>
            <option value="permission_change">permission change</option>
            <option value="tool_run">tool run</option>
            <option value="grant_expired">grant expired</option>
          </select>
        </label>
        <label class="filter">
          <span>Actor</span>
          <select v-model="filterActor">
            <option value="all">all</option>
            <option value="user">user</option>
            <option value="system">system</option>
          </select>
        </label>
        <label class="filter search">
          <span>Search</span>
          <input
            v-model="search"
            type="search"
            placeholder="tool, category, reason…"
            aria-label="Filter audit entries by text"
          />
        </label>
      </div>
      <div class="meta">
        <span>{{ filtered.length }} of {{ entries.length }} entries</span>
        <button class="refresh" @click="refresh" :disabled="loading">
          {{ loading ? 'loading…' : 'refresh' }}
        </button>
      </div>
    </div>

    <div class="audit-body">
      <p v-if="loading && entries.length === 0" class="empty">loading…</p>
      <p v-else-if="entries.length === 0" class="empty">no audit entries yet.</p>
      <p v-else-if="filtered.length === 0" class="empty">no matches.</p>

      <ul v-else class="entry-list">
        <li
          v-for="(entry, idx) in filtered"
          :key="entryKey(entry, idx)"
          :class="['entry', `kind-${entry.kind}`, `decision-${entry.decision || 'none'}`]"
        >
          <span class="dot" :title="entry.kind"></span>
          <span class="kind">{{ kindLabel(entry.kind) }}</span>
          <span class="actor">{{ entry.actor || '—' }}</span>
          <span v-if="entry.tool" class="tool">{{ entry.tool }}</span>
          <span v-if="entry.category" class="category">{{ entry.category }}</span>
          <span v-if="entry.decision" :class="['decision', entry.decision]">{{ entry.decision }}</span>
          <span v-if="entry.ttl_minutes" class="ttl">{{ entry.ttl_minutes }}m</span>
          <span v-if="entry.reason" class="reason" :title="entry.reason">
            {{ truncate(entry.reason, 60) }}
          </span>
          <time class="ts" :datetime="entry.ts">{{ formatRelative(entry.ts) }}</time>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
})
defineEmits(['close'])

const entries = ref([])
const loading = ref(false)
const filterKind = ref('all')
const filterActor = ref('all')
const search = ref('')

async function refresh() {
  loading.value = true
  try {
    const res = await fetch('/api/audit?limit=200')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    entries.value = (data.entries || []).slice().reverse()
  } catch (err) {
    console.warn('[chika] audit fetch failed:', err)
    entries.value = []
  } finally {
    loading.value = false
  }
}

watch(() => props.open, (open) => {
  if (open && entries.value.length === 0) refresh()
})

onMounted(() => {
  if (props.open) refresh()
})

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  return entries.value.filter((e) => {
    if (filterKind.value !== 'all' && e.kind !== filterKind.value) return false
    if (filterActor.value !== 'all' && e.actor !== filterActor.value) return false
    if (!q) return true
    const haystack = [e.tool, e.category, e.reason, e.decision]
      .filter(Boolean).join(' ').toLowerCase()
    return haystack.includes(q)
  })
})

function entryKey(entry, idx) {
  return `${entry.ts || idx}-${entry.kind}-${entry.tool || ''}-${idx}`
}

function kindLabel(kind) {
  return ({
    approval:          'approval',
    permission_change: 'perm change',
    tool_run:          'tool run',
    grant_expired:     'grant expired',
  })[kind] || kind || '—'
}

function formatRelative(ts) {
  if (!ts) return '—'
  const t = Date.parse(ts)
  if (Number.isNaN(t)) return ts
  const diffSec = Math.floor((Date.now() - t) / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  return `${Math.floor(diffSec / 86400)}d ago`
}

function truncate(s, n) {
  if (!s) return ''
  return s.length > n ? s.slice(0, n) + '…' : s
}
</script>

<style scoped>
.audit-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(640px, 90vw);
  background: var(--surface, #14161c);
  border-left: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  display: flex;
  flex-direction: column;
  z-index: 50;
  font-family: var(--font-sans, -apple-system, sans-serif);
}

.audit-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.06));
}

.title { font-size: 16px; font-weight: 600; letter-spacing: -0.01em; }
.close {
  background: none;
  border: none;
  color: var(--muted, #a8a8b8);
  font-size: 18px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
}
.close:hover { background: rgba(255, 255, 255, 0.05); }

.audit-controls {
  padding: 14px 22px;
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.filter-row { display: flex; gap: 12px; flex-wrap: wrap; }
.filter {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--muted, #a8a8b8);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.filter select, .filter input {
  background: var(--bg, #0b0c10);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  color: var(--text, #ededf2);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 13px;
  text-transform: none;
  letter-spacing: 0;
}
.filter.search { flex: 1; min-width: 180px; }

.meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--muted, #a8a8b8);
}
.refresh {
  background: none;
  border: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  color: var(--muted, #a8a8b8);
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}
.refresh:hover { color: var(--text, #ededf2); }
.refresh:disabled { opacity: 0.5; cursor: not-allowed; }

.audit-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}
.empty {
  padding: 32px 22px;
  color: var(--muted, #a8a8b8);
  text-align: center;
  font-size: 13px;
}

.entry-list { list-style: none; padding: 0; margin: 0; }
.entry {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 22px;
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.04));
  font-size: 12.5px;
  font-family: var(--font-mono, "SF Mono", Menlo, monospace);
}
.entry:hover { background: rgba(255, 255, 255, 0.02); }

.dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--muted, #a8a8b8);
  flex-shrink: 0;
}
.kind-approval .dot          { background: #6c63ff; }
.kind-permission_change .dot { background: #e0b35c; }
.kind-tool_run .dot          { background: #3dd68c; }
.kind-grant_expired .dot     { background: #6b6b85; }

.kind {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted, #a8a8b8);
  min-width: 88px;
}
.actor {
  color: var(--dim, #6b6b85);
  min-width: 56px;
}
.tool {
  color: var(--accent, #6c63ff);
  font-weight: 500;
}
.category {
  color: var(--muted, #a8a8b8);
}
.decision {
  font-weight: 500;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
}
.decision.approve, .decision.ok { background: rgba(61, 214, 140, 0.12); color: #3dd68c; }
.decision.deny, .decision.error { background: rgba(224, 92, 92, 0.12); color: #e05c5c; }
.decision.skip                  { background: rgba(108, 99, 255, 0.12); color: #6c63ff; }
.decision.ask                   { background: rgba(168, 168, 184, 0.12); color: #a8a8b8; }

.ttl {
  font-size: 11px;
  color: var(--warn, #e0b35c);
  background: rgba(224, 179, 92, 0.08);
  padding: 1px 6px;
  border-radius: 4px;
}

.reason {
  flex: 1;
  color: var(--muted, #a8a8b8);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: var(--font-sans, sans-serif);
  font-size: 12px;
}

.ts {
  font-size: 11px;
  color: var(--dim, #6b6b85);
  margin-left: auto;
  flex-shrink: 0;
}

@media (prefers-reduced-motion: reduce) {
  .audit-panel * { transition: none !important; }
}
</style>

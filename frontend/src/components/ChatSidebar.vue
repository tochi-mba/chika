<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <span class="header-label">Chats</span>
      <button class="new-btn" @click="$emit('new-chat')" title="New chat">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        New chat
      </button>
    </div>

    <div class="chat-list" v-if="chatList.length > 0">
      <div
        v-for="chat in chatList"
        :key="chat.id"
        class="chat-item"
        :class="{ active: chat.id === currentSessionId }"
        @click="$emit('load-chat', chat.id)"
      >
        <div class="chat-item-row">
          <div class="chat-item-title">{{ chat.title || 'New chat' }}</div>
          <span class="chat-item-time">{{ timeAgo(chat.updated_at) }}</span>
        </div>
        <button
          class="delete-btn"
          @click.stop="$emit('delete-chat', chat.id)"
          title="Delete"
          aria-label="Delete chat"
        >
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
    </div>

    <div class="empty-state" v-else-if="!loading">No chats yet</div>
    <div class="empty-state" v-else>Loading…</div>
  </aside>
</template>

<script setup>
defineProps({
  chatList:         { type: Array,   default: () => [] },
  currentSessionId: { type: String,  default: '' },
  loading:          { type: Boolean, default: false },
})
defineEmits(['new-chat', 'load-chat', 'delete-chat'])

function timeAgo(ts) {
  if (!ts) return ''
  const diff = Date.now() / 1000 - ts
  if (diff < 60)    return 'now'
  if (diff < 3600)  return Math.floor(diff / 60) + 'm'
  if (diff < 86400) return Math.floor(diff / 3600) + 'h'
  return Math.floor(diff / 86400) + 'd'
}
</script>

<style scoped>
.sidebar {
  width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border-right: 1px solid var(--border);
  overflow: hidden;
}

/* ── Header ─────────────────────────────────────────────────────────────── */
.sidebar-header {
  padding: 14px 14px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.header-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-3);
}

.new-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-2);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 140ms var(--spring);
  white-space: nowrap;
}
.new-btn:hover {
  color: var(--accent);
  border-color: var(--accent);
  background: var(--accent-dim);
}

/* ── Chat list ──────────────────────────────────────────────────────────── */
.chat-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.chat-item {
  position: relative;
  padding: 9px 10px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 2px;
  transition: background 120ms var(--spring);
  border-left: 2px solid transparent;
}
.chat-item:hover { background: var(--surface-2); }
.chat-item.active {
  background: var(--accent-dim);
  border-left-color: var(--accent);
}

.chat-item-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
}

.chat-item-title {
  font-size: 13px;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
  padding-right: 18px;
  line-height: 1.4;
}
.chat-item.active .chat-item-title {
  color: var(--accent);
  font-weight: 500;
}
.chat-item:hover:not(.active) .chat-item-title { color: var(--text-1); }

.chat-item-time {
  font-size: 11px;
  color: var(--text-3);
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.delete-btn {
  position: absolute;
  top: 50%;
  right: 6px;
  transform: translateY(-50%);
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  border-radius: 4px;
  opacity: 0;
  transition: opacity 100ms, color 100ms, background 100ms;
}
.chat-item:hover .delete-btn { opacity: 1; }
.delete-btn:hover {
  color: var(--error);
  background: color-mix(in srgb, var(--error) 12%, transparent);
}

/* ── Empty / loading ────────────────────────────────────────────────────── */
.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--text-3);
}
</style>

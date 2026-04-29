<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <div class="wordmark">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="#6c63ff" stroke="#6c63ff" stroke-width="1" stroke-linejoin="round"/>
        </svg>
        <span class="wordmark-text">Chika</span>
      </div>
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
  background: var(--surface-1, #111117);
  border-right: 1px solid var(--border, rgba(255,255,255,0.07));
  overflow: hidden;
}

/* ── Header ─────────────────────────────────────────────────────────────── */
.sidebar-header {
  padding: 14px 12px 10px;
  border-bottom: 1px solid var(--border, rgba(255,255,255,0.07));
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.wordmark {
  display: flex;
  align-items: center;
  gap: 6px;
}
.wordmark-text {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--text-1, #ededf2);
}

.new-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 9px;
  background: none;
  border: 1px solid var(--border, rgba(255,255,255,0.07));
  border-radius: var(--radius-sm, 5px);
  color: var(--text-3, #4f4f6a);
  font-size: 12px;
  cursor: pointer;
  font-family: inherit;
  transition: color 150ms, border-color 150ms;
  white-space: nowrap;
}
.new-btn:hover {
  color: var(--accent, #6c63ff);
  border-color: var(--accent, #6c63ff);
}

/* ── Chat list ──────────────────────────────────────────────────────────── */
.chat-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px 6px;
}

.chat-item {
  position: relative;
  padding: 7px 8px;
  border-radius: var(--radius-sm, 5px);
  cursor: pointer;
  margin-bottom: 1px;
  transition: background 120ms;
  border-left: 2px solid transparent;
}
.chat-item:hover { background: var(--surface-2, #18181f); }
.chat-item.active {
  background: var(--accent-dim, rgba(108,99,255,0.15));
  border-left-color: var(--accent, #6c63ff);
}

.chat-item-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
}

.chat-item-title {
  font-size: 13px;
  color: var(--text-2, #8888a2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
  padding-right: 18px;
  line-height: 1.4;
}
.chat-item.active .chat-item-title { color: var(--text-1, #ededf2); }
.chat-item:hover:not(.active) .chat-item-title { color: var(--text-1, #ededf2); }

.chat-item-time {
  font-size: 11px;
  color: var(--text-3, #4f4f6a);
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
  color: var(--text-3, #4f4f6a);
  cursor: pointer;
  border-radius: 4px;
  opacity: 0;
  transition: opacity 100ms, color 100ms, background 100ms;
}
.chat-item:hover .delete-btn { opacity: 1; }
.delete-btn:hover {
  color: var(--red, #e05c5c);
  background: rgba(224, 92, 92, 0.1);
}

/* ── Empty / loading ────────────────────────────────────────────────────── */
.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--text-3, #4f4f6a);
}
</style>

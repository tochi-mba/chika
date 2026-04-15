<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <button class="new-chat-btn" @click="$emit('new-chat')" title="New chat">
        <span>+</span> New chat
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
        <div class="chat-item-title">{{ chat.title || 'New chat' }}</div>
        <div class="chat-item-meta">
          <span class="chat-item-time">{{ timeAgo(chat.updated_at) }}</span>
          <span class="chat-item-count">{{ chat.message_count }} msg</span>
        </div>
        <div v-if="chat.preview" class="chat-item-preview">{{ chat.preview }}</div>
        <button
          class="delete-btn"
          @click.stop="$emit('delete-chat', chat.id)"
          title="Delete chat"
        >×</button>
      </div>
    </div>

    <div class="empty-state" v-else-if="!loading">
      <span>No chats yet</span>
    </div>
    <div class="loading-state" v-else>
      <span>Loading…</span>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  chatList:         { type: Array,  default: () => [] },
  currentSessionId: { type: String, default: '' },
  loading:          { type: Boolean, default: false },
})
defineEmits(['new-chat', 'load-chat', 'delete-chat'])

function timeAgo(ts) {
  if (!ts) return ''
  const diff = Date.now() / 1000 - ts
  if (diff < 60)     return 'just now'
  if (diff < 3600)   return Math.floor(diff / 60) + 'm ago'
  if (diff < 86400)  return Math.floor(diff / 3600) + 'h ago'
  return Math.floor(diff / 86400) + 'd ago'
}
</script>

<style scoped>
.sidebar {
  width: 220px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #0b0b10;
  border-right: 1px solid #1e1e28;
  overflow: hidden;
}

.sidebar-header {
  padding: 8px;
  border-bottom: 1px solid #1e1e28;
  flex-shrink: 0;
}

.new-chat-btn {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: #1a1a24;
  border: 1px solid #2a2a38;
  border-radius: 8px;
  color: #c8c8d8;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.new-chat-btn:hover {
  background: #22223a;
  border-color: #4a4a6a;
}
.new-chat-btn span {
  font-size: 18px;
  line-height: 1;
  color: #7c6fff;
}

.chat-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}
.chat-list::-webkit-scrollbar { width: 4px; }
.chat-list::-webkit-scrollbar-track { background: transparent; }
.chat-list::-webkit-scrollbar-thumb { background: #2a2a38; border-radius: 2px; }

.chat-item {
  position: relative;
  padding: 10px 10px 8px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 2px;
  transition: background 0.12s;
}
.chat-item:hover { background: #141420; }
.chat-item.active { background: #1a1a2e; }
.chat-item.active::before {
  content: '';
  position: absolute;
  left: 0; top: 6px; bottom: 6px;
  width: 3px;
  background: #7c6fff;
  border-radius: 0 2px 2px 0;
}

.chat-item-title {
  font-size: 13px;
  color: #d8d8e8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 3px;
  padding-right: 18px;
}
.chat-item.active .chat-item-title { color: #e8e8f8; }

.chat-item-meta {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: #444;
}

.chat-item-preview {
  font-size: 11px;
  color: #3a3a52;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 3px;
}

.delete-btn {
  position: absolute;
  top: 6px; right: 6px;
  width: 18px; height: 18px;
  display: flex; align-items: center; justify-content: center;
  background: none;
  border: none;
  color: #333;
  font-size: 16px;
  cursor: pointer;
  border-radius: 4px;
  opacity: 0;
  transition: opacity 0.1s, color 0.1s;
  line-height: 1;
}
.chat-item:hover .delete-btn { opacity: 1; }
.delete-btn:hover { color: #e05555; }

.empty-state, .loading-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #333;
}
</style>

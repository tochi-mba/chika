<template>
  <aside class="sidebar" :class="{ collapsed }">
    <!-- Brand header -->
    <div class="sidebar-brand">
      <div class="brand">
        <ChikaMark :size="22" :state="markState" />
        <span v-if="!collapsed" class="brand-name">Chika</span>
      </div>
      <button
        v-if="!collapsed"
        class="brand-collapse"
        @click="$emit('toggle-collapse')"
        :aria-label="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        title="Collapse"
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path d="M10 12L6 8L10 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>

    <!-- New chat -->
    <div class="sidebar-new">
      <button
        class="new-btn"
        :class="{ 'icon-only': collapsed }"
        @click="$emit('new-chat')"
        :title="collapsed ? 'New chat' : ''"
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path d="M8 3V13M3 8H13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
        </svg>
        <span v-if="!collapsed">New chat</span>
      </button>
    </div>

    <!-- Chat list -->
    <div class="chat-list-wrap">
      <div v-if="!collapsed && chatList.length > 0" class="chat-list">
        <button
          v-for="chat in chatList"
          :key="chat.id"
          class="chat-item"
          :class="{ active: chat.id === currentSessionId }"
          @click="$emit('load-chat', chat.id)"
          :title="chat.title || 'New chat'"
        >
          <span class="chat-item-title">{{ chat.title || 'New chat' }}</span>
          <span class="chat-item-time">{{ timeAgo(chat.updated_at) }}</span>
          <button
            class="delete-btn"
            @click.stop="$emit('delete-chat', chat.id)"
            title="Delete chat"
            aria-label="Delete chat"
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </button>
      </div>
      <div v-else-if="!collapsed && !loading" class="empty-state">No conversations yet</div>
      <div v-else-if="!collapsed" class="empty-state">Loading…</div>
    </div>

    <!-- State indicator -->
    <div v-if="!collapsed" class="sidebar-state">
      <StateIndicator :show-verb="true" :show-timer="true" />
    </div>

    <!-- Pet slot (rendered by parent so the floating fallback isn't duplicated) -->
    <div class="sidebar-pet" :class="{ collapsed }">
      <slot name="pet" />
    </div>

    <!-- Profile + settings footer -->
    <div class="sidebar-footer" :class="{ collapsed }">
      <div v-if="!collapsed && profile?.name" class="footer-info">
        <span class="footer-name">{{ profile.name }}</span>
        <span v-if="workspacePath" class="footer-path" :title="workspacePath">{{ workspacePath }}</span>
      </div>
      <button
        class="footer-icon"
        @click="$emit('open-settings')"
        title="Settings"
        aria-label="Settings"
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path d="M8 10C9.10457 10 10 9.10457 10 8C10 6.89543 9.10457 6 8 6C6.89543 6 6 6.89543 6 8C6 9.10457 6.89543 10 8 10Z" stroke="currentColor" stroke-width="1.5"/>
          <path d="M13.5 8C13.5 7.67 13.47 7.35 13.42 7.03L14.82 5.97C14.94 5.88 14.97 5.72 14.9 5.58L13.55 3.22C13.48 3.08 13.32 3.03 13.18 3.08L11.54 3.74C11.07 3.38 10.54 3.09 9.97 2.89L9.72 1.16C9.7 1 9.56 0.88 9.4 0.88H6.6C6.44 0.88 6.3 1 6.28 1.16L6.03 2.89C5.46 3.09 4.93 3.38 4.46 3.74L2.82 3.08C2.68 3.03 2.52 3.08 2.45 3.22L1.1 5.58C1.03 5.72 1.06 5.88 1.18 5.97L2.58 7.03C2.53 7.35 2.5 7.67 2.5 8C2.5 8.33 2.53 8.65 2.58 8.97L1.18 10.03C1.06 10.12 1.03 10.28 1.1 10.42L2.45 12.78C2.52 12.92 2.68 12.97 2.82 12.92L4.46 12.26C4.93 12.62 5.46 12.91 6.03 13.11L6.28 14.84C6.3 15 6.44 15.12 6.6 15.12H9.4C9.56 15.12 9.7 15 9.72 14.84L9.97 13.11C10.54 12.91 11.07 12.62 11.54 12.26L13.18 12.92C13.32 12.97 13.48 12.92 13.55 12.78L14.9 10.42C14.97 10.28 14.94 10.12 14.82 10.03L13.42 8.97C13.47 8.65 13.5 8.33 13.5 8Z" stroke="currentColor" stroke-width="1.5"/>
        </svg>
      </button>
      <button
        v-if="collapsed"
        class="footer-icon"
        @click="$emit('toggle-collapse')"
        title="Expand sidebar"
        aria-label="Expand sidebar"
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path d="M6 4L10 8L6 12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useChatStore } from '../stores/chat'
import ChikaMark from './ChikaMark.vue'
import StateIndicator from './StateIndicator.vue'

const props = defineProps({
  chatList:         { type: Array,   default: () => [] },
  currentSessionId: { type: String,  default: '' },
  loading:          { type: Boolean, default: false },
  collapsed:        { type: Boolean, default: false },
  profile:          { type: Object,  default: () => ({}) },
  workspacePath:    { type: String,  default: '' },
})

defineEmits(['new-chat', 'load-chat', 'delete-chat', 'toggle-collapse', 'open-settings'])

const chat = useChatStore()
const markState = computed(() => chat.isStreaming ? 'streaming' : 'idle')

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
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border-right: 1px solid var(--border);
  overflow: hidden;
  transition: width 220ms cubic-bezier(0.32, 0.72, 0, 1);
}
.sidebar.collapsed { width: 64px; }

/* ── Brand header ───────────────────────────────────────────────────────── */
.sidebar-brand {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.sidebar.collapsed .sidebar-brand { justify-content: center; padding: 0; }

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.brand-name {
  font-weight: 600;
  font-size: 14.5px;
  letter-spacing: -0.015em;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
}

.brand-collapse {
  width: 28px;
  height: 28px;
  background: none;
  border: none;
  border-radius: 7px;
  color: var(--text-3);
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: color 200ms cubic-bezier(0.32, 0.72, 0, 1),
              background 200ms cubic-bezier(0.32, 0.72, 0, 1);
}
.brand-collapse:hover { color: var(--text-1); background: var(--surface-2); }

/* ── New chat ───────────────────────────────────────────────────────────── */
.sidebar-new { padding: 12px; flex-shrink: 0; }
.sidebar.collapsed .sidebar-new { padding: 12px 8px; }

.new-btn {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 9px;
  color: var(--text-2);
  font: inherit;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  letter-spacing: -0.005em;
  transition: color 200ms cubic-bezier(0.32, 0.72, 0, 1),
              background 200ms cubic-bezier(0.32, 0.72, 0, 1),
              border-color 200ms cubic-bezier(0.32, 0.72, 0, 1),
              transform 200ms cubic-bezier(0.32, 0.72, 0, 1);
}
.new-btn:hover {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
  background: color-mix(in srgb, var(--accent) 6%, var(--surface-2));
  transform: translateY(-1px);
}
.new-btn.icon-only { justify-content: center; padding: 8px 0; }

/* ── Chat list ──────────────────────────────────────────────────────────── */
.chat-list-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px 8px;
}
.sidebar.collapsed .chat-list-wrap { display: none; }

.chat-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.chat-item {
  position: relative;
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 8px 12px;
  background: none;
  border: none;
  border-radius: 8px;
  font: inherit;
  text-align: left;
  cursor: pointer;
  color: var(--text-2);
  width: 100%;
  transition: background 200ms cubic-bezier(0.32, 0.72, 0, 1),
              color 200ms cubic-bezier(0.32, 0.72, 0, 1);
}
.chat-item:hover { background: var(--surface-2); color: var(--text-1); }
.chat-item.active {
  background: var(--surface-2);
  color: var(--text-1);
}
.chat-item.active .chat-item-title { font-weight: 500; }

.chat-item-title {
  flex: 1;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding-right: 18px;
  line-height: 1.4;
}

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
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  border-radius: 5px;
  opacity: 0;
  transition: opacity 200ms cubic-bezier(0.32, 0.72, 0, 1),
              color 200ms cubic-bezier(0.32, 0.72, 0, 1),
              background 200ms cubic-bezier(0.32, 0.72, 0, 1);
}
.chat-item:hover .delete-btn { opacity: 1; }
.delete-btn:hover {
  color: var(--error);
  background: color-mix(in srgb, var(--error) 12%, transparent);
}

.empty-state {
  font-size: 12px;
  color: var(--text-3);
  text-align: center;
  padding: 24px 16px;
}

/* ── State indicator section ────────────────────────────────────────────── */
.sidebar-state {
  padding: 10px 12px;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}

/* ── Pet slot ───────────────────────────────────────────────────────────── */
/* overflow:visible so the speech bubble (positioned bottom:100% inside
   PetCompanion) can grow upward without being clipped. */
.sidebar-pet {
  padding: 14px 12px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: center;
  flex-shrink: 0;
  overflow: visible;
  position: relative;
}
.sidebar-pet.collapsed { padding: 10px 0; }

/* ── Footer ─────────────────────────────────────────────────────────────── */
.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}
.sidebar-footer.collapsed { justify-content: center; padding: 10px 0; }

.footer-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.footer-name {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-transform: capitalize;
  letter-spacing: -0.005em;
}
.footer-path {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  direction: rtl;
  text-align: left;
}

.footer-icon {
  width: 30px;
  height: 30px;
  background: none;
  border: none;
  border-radius: 7px;
  color: var(--text-3);
  cursor: pointer;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  transition: color 200ms cubic-bezier(0.32, 0.72, 0, 1),
              background 200ms cubic-bezier(0.32, 0.72, 0, 1);
}
.footer-icon:hover { color: var(--text-1); background: var(--surface-2); }
</style>

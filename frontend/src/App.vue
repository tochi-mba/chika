<template>
  <div class="app">
    <header class="header">
      <div class="brand">
        <svg class="brand-logo" width="18" height="18" viewBox="0 0 24 24" fill="none">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="#6c63ff" stroke="#6c63ff" stroke-width="1.5" stroke-linejoin="round"/>
        </svg>
        <span class="brand-name">Chika</span>
      </div>

      <div class="header-center">
        <ProfileSwitcher @switch="switchProfile" />
        <span v-if="chat.title" class="chat-title">{{ chat.title }}</span>
      </div>

      <div class="header-right">
        <span
          v-if="system.extensionConnected"
          class="conn-indicator ext-indicator"
          title="Browser extension connected"
        />
        <span class="conn-indicator" :class="{ connected: system.connected }" :title="system.connected ? 'Connected' : 'Disconnected'" />

        <!-- Autonomy toggle + permissions popover -->
        <div class="perm-wrap" ref="permWrapRef">
          <button
            class="icon-btn"
            :class="{ 'icon-btn--autonomous': system.autonomy === 'autonomous', 'icon-btn--active': permOpen }"
            @click="permOpen = !permOpen"
            :title="system.autonomy === 'autonomous' ? 'Autonomous — click to configure permissions' : 'Supervised — click to configure permissions'"
          >
            <!-- Lock: supervised -->
            <svg v-if="system.autonomy !== 'autonomous'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
            <!-- Unlock: autonomous -->
            <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
              <path d="M7 11V7a5 5 0 0 1 9.9-1"/>
            </svg>
          </button>

          <!-- Permissions popover -->
          <div v-if="permOpen" class="perm-popover">
            <div class="perm-header">AI Permissions</div>

            <!-- Global preset -->
            <div class="perm-preset">
              <button
                class="perm-preset-btn"
                :class="{ active: system.autonomy === 'supervised' }"
                @click="setGlobalAutonomy('supervised')"
              >Supervised</button>
              <button
                class="perm-preset-btn"
                :class="{ active: system.autonomy === 'autonomous' }"
                @click="setGlobalAutonomy('autonomous')"
              >Autonomous</button>
            </div>
            <p class="perm-hint">Or configure per category:</p>

            <!-- Per-category rows -->
            <div
              v-for="(label, cat) in system.permissionCategories"
              :key="cat"
              class="perm-row"
            >
              <span class="perm-label">{{ label }}</span>
              <div class="perm-toggle">
                <button
                  class="perm-opt"
                  :class="{ active: effectivePerm(cat) === 'ask' }"
                  @click="setCategoryPerm(cat, 'ask')"
                >Ask</button>
                <button
                  class="perm-opt"
                  :class="{ active: effectivePerm(cat) === 'skip' }"
                  @click="setCategoryPerm(cat, 'skip')"
                >Skip</button>
              </div>
            </div>
          </div>
        </div>

        <!-- Theme toggle -->
        <button class="icon-btn" @click="theme.toggle()" :title="theme.isDark ? 'Switch to light mode' : 'Switch to dark mode'">
          <!-- Moon: currently dark, click to go light -->
          <svg v-if="theme.isDark" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
          <!-- Sun: currently light, click to go dark -->
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="5"/>
            <line x1="12" y1="1" x2="12" y2="3"/>
            <line x1="12" y1="21" x2="12" y2="23"/>
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
            <line x1="1" y1="12" x2="3" y2="12"/>
            <line x1="21" y1="12" x2="23" y2="12"/>
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
          </svg>
        </button>

        <!-- Panel toggle — always reachable even when panel is closed -->
        <button
          class="icon-btn"
          :class="{ 'icon-btn--active': !panelCollapsed }"
          @click="panelCollapsed = !panelCollapsed"
          :title="panelCollapsed ? 'Open panel' : 'Close panel'"
        >
          <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">
            <rect x="1" y="1" width="13" height="13" rx="2"/>
            <line x1="9.5" y1="1.5" x2="9.5" y2="13.5"/>
          </svg>
        </button>

        <button class="reset-btn" @click="reset" title="Reset chat">Reset</button>
      </div>
    </header>

    <!-- Connection error banner -->
    <div v-if="system.connectionError" class="error-banner">
      <span>{{ system.connectionError }}</span>
      <button class="error-dismiss" @click="system.setConnectionError(null)" aria-label="Dismiss">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>

    <ApprovalModal
      :approvals="system.pendingApprovals"
      @approve="(id, pwd) => approve(id, true, pwd)"
      @deny="id => approve(id, false, '')"
    />

    <QuestionModal
      :questions="system.pendingQuestions"
      @answer="(id, payload) => answerQuestion(id, payload)"
    />

    <div class="body">
      <ChatSidebar
        :chat-list="chats.chatList"
        :current-session-id="chat.sessionId"
        :loading="false"
        @new-chat="newChat"
        @load-chat="loadChat"
        @delete-chat="deleteChat"
      />

      <div class="chat-col">
        <MessageList :messages="chat.messages" :is-streaming="chat.isStreaming" />
        <ChatInput :disabled="chat.isStreaming" :streaming="chat.isStreaming" @send="send" @stop="stop" />
      </div>

      <div class="panel-col" :class="{ collapsed: panelCollapsed }">
        <SystemPanel :collapsed="panelCollapsed" @toggle="panelCollapsed = !panelCollapsed" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, watchEffect, onMounted, onUnmounted } from 'vue'
import { useChika }       from './composables/useChika'
import { useChatStore }   from './stores/chat'
import { useChatsStore }  from './stores/chats'
import { useSystemStore } from './stores/system'
import { useThemeStore }  from './stores/theme'
import MessageList        from './components/MessageList.vue'
import ChatInput          from './components/ChatInput.vue'
import SystemPanel        from './components/SystemPanel.vue'
import ApprovalModal      from './components/ApprovalModal.vue'
import QuestionModal      from './components/QuestionModal.vue'
import ProfileSwitcher    from './components/ProfileSwitcher.vue'
import ChatSidebar        from './components/ChatSidebar.vue'

const chat   = useChatStore()
const chats  = useChatsStore()
const system = useSystemStore()
const theme  = useThemeStore()

// Apply/remove .light class on <html> so :root.light tokens take effect globally
watchEffect(() => {
  document.documentElement.classList.toggle('light', !theme.isDark)
})

const storedKey = localStorage.getItem('chika_api_key') || ''
const { send, stop, reset, approve, answerQuestion, switchProfile, loadChat, newChat, deleteChat, patchSettings } = useChika(storedKey)

// ── Permissions popover ────────────────────────────────────────────────────

const permOpen = ref(false)
const permWrapRef = ref(null)

function effectivePerm(cat) {
  const explicit = system.toolPermissions[cat]
  if (explicit) return explicit
  return system.autonomy === 'autonomous' ? 'skip' : 'ask'
}

async function setGlobalAutonomy(val) {
  try {
    await patchSettings({ autonomy: val })
  } catch { /* logged */ }
}

async function setCategoryPerm(cat, perm) {
  try {
    await patchSettings({ tool_permissions: { [cat]: perm } })
  } catch { /* logged */ }
}

function onOutsideClick(e) {
  if (permWrapRef.value && !permWrapRef.value.contains(e.target)) {
    permOpen.value = false
  }
}
onMounted(() => document.addEventListener('mousedown', onOutsideClick))
onUnmounted(() => document.removeEventListener('mousedown', onOutsideClick))

// Panel collapsed state — persisted across sessions
const panelCollapsed = ref(localStorage.getItem('chika_panel_open') === 'false')
watch(panelCollapsed, v => localStorage.setItem('chika_panel_open', v ? 'false' : 'true'))
</script>

<style>
/* ── Design tokens — dark (default) ────────────────────────────────────── */
:root {
  --bg:           #09090d;
  --surface-0:    #050508;  /* terminal / always-dark areas */
  --surface-1:    #111117;
  --surface-2:    #18181f;
  --surface-3:    #20202a;
  --border:       rgba(255, 255, 255, 0.07);
  --border-strong: rgba(255, 255, 255, 0.12);
  --accent:       #6c63ff;
  --accent-dim:   rgba(108, 99, 255, 0.15);
  --text-1:       #ededf2;
  --text-2:       #8888a2;
  --text-3:       #4f4f6a;
  --green:        #3dd68c;
  --green-dim:    rgba(61, 214, 140, 0.12);
  --red:          #e05c5c;
  --red-dim:      rgba(224, 92, 92, 0.12);
  --yellow:       #e0b35c;
  --radius-sm:    5px;
  --radius:       9px;
  --radius-lg:    14px;
  --ease:         cubic-bezier(0.16, 1, 0.3, 1);
  --ease-out:     cubic-bezier(0.0, 0, 0.2, 1);
  --font-mono:    'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
}

/* ── Light mode overrides ───────────────────────────────────────────────── */
:root.light {
  --bg:            #f5f5f8;
  /* surface-0 intentionally stays dark — used for terminals and code */
  --surface-1:     #ffffff;
  --surface-2:     #f0f0f5;
  --surface-3:     #e7e7ed;
  --border:        rgba(0, 0, 0, 0.08);
  --border-strong: rgba(0, 0, 0, 0.15);
  --accent-dim:    rgba(108, 99, 255, 0.09);
  --text-1:        #111124;
  --text-2:        #52526e;
  --text-3:        #9898b2;
  --green:         #1a9652;
  --green-dim:     rgba(26, 150, 82, 0.1);
  --red:           #c43434;
  --red-dim:       rgba(196, 52, 52, 0.1);
  --yellow:        #a07020;
}
</style>

<style scoped>
/* ── Root layout ─────────────────────────────────────────────────────────── */
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--bg);
}

/* ── Header ──────────────────────────────────────────────────────────────── */
.header {
  display: flex;
  align-items: center;
  padding: 0 16px;
  height: 46px;
  background: var(--surface-1);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  gap: 12px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
}
.brand-logo { flex-shrink: 0; }
.brand-name {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--text-1);
}

.header-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  min-width: 0;
}
.chat-title {
  font-size: 11px;
  color: var(--text-3);
  max-width: 300px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.conn-indicator {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-3);
  transition: background 0.4s, box-shadow 0.4s;
}
.conn-indicator.connected {
  background: var(--green);
  box-shadow: 0 0 5px rgba(61, 214, 140, 0.5);
}
.ext-indicator {
  background: #9d7fff;
  box-shadow: 0 0 5px rgba(157, 127, 255, 0.45);
}

.icon-btn {
  width: 28px;
  height: 28px;
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-2);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 150ms, background 150ms;
  padding: 0;
  flex-shrink: 0;
}
.icon-btn:hover {
  color: var(--text-1);
  background: var(--surface-2);
}
.icon-btn--active {
  color: var(--accent);
}
.icon-btn--autonomous {
  color: var(--yellow);
}

/* ── Permissions popover ────────────────────────────────────────────────── */
.perm-wrap {
  position: relative;
}

.perm-popover {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: 280px;
  background: var(--surface-1);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  z-index: 200;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.perm-header {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  margin-bottom: 2px;
}

.perm-preset {
  display: flex;
  gap: 6px;
}

.perm-preset-btn {
  flex: 1;
  padding: 5px 0;
  font-size: 12px;
  font-family: inherit;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: none;
  color: var(--text-2);
  cursor: pointer;
  transition: all 120ms;
}
.perm-preset-btn:hover {
  border-color: var(--border-strong);
  color: var(--text-1);
}
.perm-preset-btn.active {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-dim);
}

.perm-hint {
  font-size: 11px;
  color: var(--text-3);
  margin: 0;
}

.perm-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.perm-label {
  font-size: 12px;
  color: var(--text-2);
  flex: 1;
  min-width: 0;
}

.perm-toggle {
  display: flex;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
  flex-shrink: 0;
}

.perm-opt {
  padding: 3px 10px;
  font-size: 11px;
  font-family: inherit;
  border: none;
  background: none;
  color: var(--text-3);
  cursor: pointer;
  transition: all 100ms;
}
.perm-opt + .perm-opt {
  border-left: 1px solid var(--border);
}
.perm-opt:hover {
  color: var(--text-2);
  background: var(--surface-2);
}
.perm-opt.active {
  background: var(--accent-dim);
  color: var(--accent);
}

.reset-btn {
  background: none;
  border: 1px solid var(--border);
  color: var(--text-3);
  font-size: 12px;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: color 150ms, border-color 150ms;
  font-family: inherit;
}
.reset-btn:hover {
  color: var(--text-2);
  border-color: var(--border-strong);
}

/* ── Error banner ─────────────────────────────────────────────────────────── */
.error-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 18px;
  background: rgba(224, 92, 92, 0.1);
  border-bottom: 1px solid rgba(224, 92, 92, 0.25);
  color: #f09898;
  font-size: 13px;
  flex-shrink: 0;
}
.error-dismiss {
  background: none;
  border: none;
  color: #f09898;
  cursor: pointer;
  padding: 2px;
  opacity: 0.7;
  line-height: 1;
  display: flex;
  align-items: center;
}
.error-dismiss:hover { opacity: 1; }

/* ── Body layout ─────────────────────────────────────────────────────────── */
.body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.chat-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.panel-col {
  flex: 0 0 300px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: flex-basis 220ms var(--ease);
}
.panel-col.collapsed {
  flex-basis: 0;
}
</style>

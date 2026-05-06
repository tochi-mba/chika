<template>
  <div class="app-root">
  <ProfileGate
    v-if="!profileUnlocked"
    :api-key="storedKey"
    :session-id="chat.sessionId || ''"
    @unlocked="onProfileUnlocked"
  />
  <div class="app" v-show="profileUnlocked">
    <header class="header">
      <div class="header-left">
        <ProfileSwitcher @switch="switchProfile" />
        <span v-if="chat.title" class="chat-title">{{ chat.title }}</span>
      </div>

      <div class="header-spacer"></div>

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

        <!-- Settings -->
        <button
          class="icon-btn"
          :class="{ 'icon-btn--active': settingsOpen }"
          @click="openSettings('provider')"
          title="Settings — provider, environment, permissions, pet"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
        </button>

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
      @approve="onApprove"
      @deny="id => approve(id, false, '')"
    />

    <SettingsModal
      :open="settingsOpen"
      :api-key="storedKey"
      :initial-tab="settingsInitialTab"
      @close="settingsOpen = false"
      @patch-settings="patchSettings"
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
        :collapsed="sidebarCollapsed"
        :profile="system.profile"
        :workspace-path="system.profile.workspace_path || system.profile.workspace || ''"
        @new-chat="newChat"
        @load-chat="loadChat"
        @delete-chat="deleteChat"
        @toggle-collapse="sidebarCollapsed = !sidebarCollapsed"
        @open-settings="openSettings('provider')"
      >
        <template #pet>
          <PetCompanion @open-settings="(t) => openSettings(t)" />
        </template>
      </ChatSidebar>

      <div class="chat-col">
        <PlanPanel
          :plan="activePlan"
          @accept="onPlanAccept"
          @reject="onPlanReject"
          @edit-feedback="onPlanEditFeedback"
          @toggle-task="onPlanTaskToggle"
        />
        <MessageList
          :messages="chat.messages"
          :is-streaming="chat.isStreaming"
          @quick-prompt="send"
        />
        <ChatInput :disabled="chat.isStreaming" :streaming="chat.isStreaming" @send="send" @stop="stop" />
      </div>

      <div class="panel-col" :class="{ collapsed: panelCollapsed }">
        <SystemPanel :collapsed="panelCollapsed" @toggle="panelCollapsed = !panelCollapsed" />
      </div>
    </div>
  </div>
  </div>
</template>

<script setup>
import { ref, watch, watchEffect, onMounted, onUnmounted, computed } from 'vue'
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
import SettingsModal      from './components/SettingsModal.vue'
import PetCompanion       from './components/PetCompanion.vue'
import PlanPanel          from './components/PlanPanel.vue'
import ProfileGate        from './components/ProfileGate.vue'

const chat   = useChatStore()
const chats  = useChatsStore()
const system = useSystemStore()
const theme  = useThemeStore()

// Apply/remove .dark class on <html> so :root.dark tokens take effect
// globally. Light is the BASE (no class) — light is the default,
// dark is opt-in via the .dark variant.
watchEffect(() => {
  document.documentElement.classList.toggle('dark', theme.isDark)
})

const storedKey = localStorage.getItem('chika_api_key') || ''
const { send, stop, reset, approve, answerQuestion, switchProfile, loadChat, newChat, deleteChat, patchSettings, connect } = useChika(storedKey)

// Bridge ApprovalModal's emit signature to ``approve()``. The modal
// emits a string (legacy password) OR an object (workspace ``{scope}``
// or plan_review ``{action, feedback?, reason?}``). ``approve()``
// detects both shapes — but only if we pass the object as its second
// argument, NOT bury it inside ``password``. This was the bug behind
// "Allow for session" silently being treated as a confirm + binary
// approval; the scope field never made it onto the WS payload.
function onApprove(id, payload) {
  if (payload !== null && typeof payload === 'object') {
    approve(id, payload)
  } else {
    approve(id, true, payload || '')
  }
}

// ── Profile gate ──────────────────────────────────────────────────────────
// We never default-load — the user must pick a profile (and pass its
// password if set) before the chat surface mounts. localStorage caches
// the choice for the rest of the browser session so refresh doesn't
// re-prompt mid-task. Logging out (or clearing storage) re-opens the gate.
function _shouldSkipProfileGate() {
  // Three escape hatches, evaluated in order:
  //   1. Persisted unlock from a previous gate sign-in (sessionStorage)
  //   2. Test-only window flag set by Playwright's addInitScript
  //   3. ``?skip_gate=1`` URL query param (no setup overhead, used by
  //      Playwright tests as the most reliable bypass — addInitScript
  //      timing was racing Vue's first ref-read on Chromium 130+).
  try {
    if (sessionStorage.getItem('chika_profile_unlocked') === '1') return true
  } catch {/* SSR-safe */}
  if (typeof window !== 'undefined' && window.__chikaProfileUnlocked === true) {
    return true
  }
  try {
    const qs = new URLSearchParams(window.location.search)
    if (qs.get('skip_gate') === '1') return true
  } catch {/* SSR-safe */}
  return false
}

const profileUnlocked = ref(_shouldSkipProfileGate())
function onProfileUnlocked(_profile) {
  sessionStorage.setItem('chika_profile_unlocked', '1')
  profileUnlocked.value = true
}

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

// ── Plan panel ────────────────────────────────────────────────────────────
// The plan lives as `$plan` in the variable store and arrives via
// variable_set events. Re-derive it from the system store every render so
// edits stay live as the agent calls plan_update / plan_edit.
const activePlan = computed(() => {
  const v = system.variables['plan']
  if (!v) return null
  // The store carries `value_preview` (a JSON-serialised snippet) for some
  // var types; the actual structured payload lives on `value`.
  const payload = v.value ?? v.value_preview ?? null
  if (!payload) return null
  if (typeof payload === 'string') {
    try { return JSON.parse(payload) } catch { return null }
  }
  return payload
})

function onPlanAccept() {
  // Tell the agent the plan is good — re-uses the auto-continue trigger
  // shape so the rest of the engine treats it as a normal user nudge.
  send("Plan looks good. Proceed.")
}

function onPlanReject() {
  send("I don't like this plan — drop it and propose a different one.")
}

function onPlanEditFeedback(text) {
  // Send the user's feedback verbatim, prefixed so the LLM clearly sees
  // it as a plan tweak (the system prompt rule for plan_edit picks it up).
  send(`[plan-edit feedback] ${text}`)
}

function onPlanTaskToggle(taskId, nextStatus) {
  // Manual user tick. Send as a structured nudge — the agent will call
  // plan_update on the backend in response.
  send(`[plan-task] mark ${taskId} as ${nextStatus}`)
}

// Panel collapsed state — persisted across sessions
const panelCollapsed = ref(localStorage.getItem('chika_panel_open') === 'false')
watch(panelCollapsed, v => localStorage.setItem('chika_panel_open', v ? 'false' : 'true'))

// Sidebar collapsed state — persisted likewise
const sidebarCollapsed = ref(localStorage.getItem('chika_sidebar_collapsed') === 'true')
watch(sidebarCollapsed, v => localStorage.setItem('chika_sidebar_collapsed', v ? 'true' : 'false'))

// Settings modal
const settingsOpen = ref(false)
const settingsInitialTab = ref('provider')

function openSettings(tab) {
  settingsInitialTab.value = tab || 'provider'
  settingsOpen.value = true
}
</script>

<style>
/* ── Design tokens — light (default — matches OS prefers-color-scheme) ── */
/*
 * Tokens unified across every surface — Vue web app, extension
 * popup, CLI Rich theme — so all three speak the same colour
 * vocabulary. Light is the BASE; ``:root.dark`` (and the App.vue
 * watchEffect that toggles it) flips into dark mode. Aliases like
 * ``--green``, ``--red``, ``--yellow`` and ``--accent-dim`` exist
 * so prior components keep rendering — they resolve to the
 * canonical names.
 */
:root {
  --bg:            #fafafb;
  --surface-0:     #050508;        /* always-dark — terminals + code blocks */
  --surface-1:     #ffffff;
  --surface-2:     #f4f4f7;
  --surface-3:     #e8e8ee;
  --border:        rgba(0, 0, 0, 0.08);
  --border-strong: rgba(0, 0, 0, 0.14);
  --text-1:        #0e0e14;
  --text-2:        #4a4a5c;
  --text-3:        #8a8a9a;
  --accent:        #6c63ff;
  --accent-2:      #7c70ff;
  --accent-dim:    rgba(108, 99, 255, 0.10);
  --success:       #3dd68c;
  --warn:          #e0b35c;
  --error:         #e05c5c;
  /* Legacy aliases — kept so older components don't need a sweep. */
  --green:         var(--success);
  --green-dim:     rgba(61, 214, 140, 0.10);
  --red:           var(--error);
  --red-dim:       rgba(224, 92, 92, 0.10);
  --yellow:        var(--warn);

  --radius-sm:     6px;
  --radius:        10px;
  --radius-lg:     14px;
  --spring:        cubic-bezier(0.16, 1, 0.3, 1);
  --ease:          var(--spring);
  --ease-out:      cubic-bezier(0.0, 0, 0.2, 1);
  --font-mono:     'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
}

/* ── Dark mode (default for users with a dark OS preference) ─────────── */
:root.dark {
  --bg:            #0e0e14;
  --surface-1:     #161620;
  --surface-2:     #1f1f2c;
  --surface-3:     #2a2a38;
  --border:        rgba(255, 255, 255, 0.08);
  --border-strong: rgba(255, 255, 255, 0.14);
  --text-1:        #ededf2;
  --text-2:        #a8a8b8;
  --text-3:        #6b6b85;
  --accent-dim:    rgba(108, 99, 255, 0.16);
  --green-dim:     rgba(61, 214, 140, 0.14);
  --red-dim:       rgba(224, 92, 92, 0.14);
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
  height: 52px;
  background: var(--surface-1);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  gap: 14px;
}

/* The brand mark + wordmark moved into the sidebar (matches the
   reference's three-column layout). The top-bar now just hosts
   per-chat metadata + global controls. */
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.header-spacer { flex: 1; min-width: 0; }
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
  width: 32px;
  height: 32px;
  background: none;
  border: none;
  border-radius: 8px;
  color: var(--text-2);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 150ms var(--spring), background 150ms var(--spring);
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

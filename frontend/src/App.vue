<template>
  <div class="app">
    <header class="header">
      <div class="brand">
        <span class="brand-icon">⚡</span>
        <span class="brand-name">Chika</span>
        <span class="brand-version">v2</span>
      </div>
      <div class="header-center">
        <ProfileSwitcher @switch="switchProfile" />
        <span class="chat-title-label" v-if="chat.title">{{ chat.title }}</span>
      </div>
      <div class="header-right">
        <span class="conn-dot" :class="{ connected: system.connected }" />
        <span class="conn-label">{{ system.connected ? 'connected' : 'disconnected' }}</span>
        <button class="clear-btn" @click="reset" title="Reset chat">✕ Reset</button>
      </div>
    </header>

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

      <div class="chat-panel">
        <MessageList :messages="chat.messages" />
        <ChatInput :disabled="chat.isStreaming" @send="send" />
      </div>

      <div class="system-panel-wrapper">
        <SystemPanel />
      </div>
    </div>
  </div>
</template>

<script setup>
import { useChika }       from './composables/useChika'
import { useChatStore }   from './stores/chat'
import { useChatsStore }  from './stores/chats'
import { useSystemStore } from './stores/system'
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

const storedKey = localStorage.getItem('chika_api_key') || ''
const { send, reset, approve, answerQuestion, switchProfile, loadChat, newChat, deleteChat } = useChika(storedKey)
</script>

<style scoped>
.app { display: flex; flex-direction: column; height: 100vh; overflow: hidden; }

.header {
  display: flex; align-items: center;
  padding: 0 16px; height: 48px;
  background: #0f0f15; border-bottom: 1px solid #2a2a35;
  flex-shrink: 0; gap: 16px;
}
.brand { display: flex; align-items: center; gap: 6px; }
.brand-icon { font-size: 18px; }
.brand-name { font-size: 16px; font-weight: 700; color: #e8e8f0; }
.brand-version { font-size: 11px; color: #555; background: #1e1e28; padding: 1px 6px; border-radius: 8px; }

.header-center {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; gap: 2px;
}
.chat-title-label {
  font-size: 11px; color: #555;
  max-width: 280px; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}

.header-right { display: flex; align-items: center; gap: 8px; }
.conn-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #444; transition: background 0.3s;
}
.conn-dot.connected { background: #40d080; box-shadow: 0 0 6px #40d08088; }
.conn-label { font-size: 11px; color: #555; }
.clear-btn {
  background: none; border: 1px solid #2a2a35;
  color: #666; font-size: 11px; padding: 4px 10px;
  border-radius: 6px; cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.clear-btn:hover { color: #aaa; border-color: #555; }

.body { display: flex; flex: 1; overflow: hidden; }

.chat-panel {
  flex: 1; display: flex; flex-direction: column;
  overflow: hidden; border-right: 1px solid #2a2a35; min-width: 0;
}
.system-panel-wrapper {
  flex: 0 0 380px; overflow: hidden; display: flex; flex-direction: column;
}
</style>

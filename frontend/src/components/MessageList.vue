<template>
  <div class="message-list" ref="container">
    <div v-if="messages.length === 0" class="empty">
      <div class="logo">⚡</div>
      <p>Chika is ready. Send a message to start.</p>
    </div>
    <MessageBubble v-for="msg in messages" :key="msg.id" :message="msg" />
    <div ref="anchor" />
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import MessageBubble from './MessageBubble.vue'

const props = defineProps({ messages: Array })
const container = ref(null)
const anchor    = ref(null)

watch(() => props.messages, () => {
  nextTick(() => anchor.value?.scrollIntoView({ behavior: 'smooth' }))
}, { deep: true })
</script>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.message-list::-webkit-scrollbar { width: 6px; }
.message-list::-webkit-scrollbar-track { background: transparent; }
.message-list::-webkit-scrollbar-thumb { background: #2a2a35; border-radius: 3px; }

.empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #555;
}
.logo { font-size: 48px; }
.empty p { font-size: 14px; }
</style>

import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useChatStore = defineStore('chat', () => {
  const messages     = ref([])
  const title        = ref('')
  const sessionId    = ref('')
  const isStreaming  = ref(false)
  const streamingText = ref('')

  function addUserMessage(text) {
    messages.value.push({ id: Date.now(), role: 'user', text, streaming: false })
  }

  function startAssistantMessage() {
    streamingText.value = ''
    isStreaming.value = true
    messages.value.push({ id: Date.now() + 1, role: 'assistant', text: '', streaming: true })
  }

  function appendToken(text) {
    streamingText.value += text
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') last.text += text
  }

  function finaliseAssistantMessage() {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') last.streaming = false
    isStreaming.value = false
    streamingText.value = ''
  }

  function addCompactionMessage(event) {
    const compactionMsg = {
      id: Date.now(),
      role: 'compaction',
      removed: event.removed || 0,
      kept: event.kept || 0,
      summary: event.summary_preview || '',
      streaming: false,
    }
    // If the last message is an empty streaming assistant bubble (added optimistically
    // on send before any tokens arrive), insert the compaction divider before it so it
    // appears between the user message and the assistant response.
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant' && last.streaming && last.text === '') {
      messages.value.splice(messages.value.length - 1, 0, compactionMsg)
    } else {
      messages.value.push(compactionMsg)
    }
  }

  // Called when server sends session_info — replaces all state
  function restoreSession(data) {
    sessionId.value   = data.session_id || ''
    title.value       = data.title || ''
    isStreaming.value = false
    streamingText.value = ''
    messages.value = (data.messages || []).map((m, i) => ({
      id: i,
      role: m.role,
      text: m.text || '',
      streaming: false,
    }))
  }

  function setTitle(t) {
    title.value = t
  }

  function clear() {
    messages.value  = []
    title.value     = ''
    sessionId.value = ''
    isStreaming.value   = false
    streamingText.value = ''
  }

  return {
    messages, title, sessionId, isStreaming, streamingText,
    addUserMessage, startAssistantMessage, appendToken,
    finaliseAssistantMessage, addCompactionMessage, restoreSession, setTitle, clear,
  }
})

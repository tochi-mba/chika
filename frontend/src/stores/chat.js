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
    messages.value.push({
      id: Date.now() + 1,
      role: 'assistant',
      text: '',
      thinking: '',          // extended-thinking reasoning (collapsible)
      warnings: [],          // validation_warning events attached to this reply
      toolEvents: [],        // workflow/tool events shown inline in the bubble
      streaming: true,
    })
  }
  

  // Attach a tool/workflow event to the active assistant message.
  // Called for: workflow_start, step_start, tool_call, tool_result,
  // step_done, workflow_done, loop_iteration, condition_eval, variable_set
  //
  // tool_call events start as `pending: true` so the renderer can show a
  // spinner. The matching tool_result (same step_id) flips them to
  // `pending: false`. This gives the user a live signal during long-running
  // tools (npm-create scaffolds, web fetches, browser scrapes) where the
  // gap between call and result was previously dead air.
  function attachToolEvent(event) {
    const last = messages.value[messages.value.length - 1]
    if (last?.role !== 'assistant') return
    const stamped = { ...event, _ts: Date.now() }

    if (event.type === 'tool_result' && event.step_id) {
      // Flip the matching pending tool_call (if any) and append the result.
      last.toolEvents = (last.toolEvents ?? []).map(ev => {
        if (ev.type === 'tool_call'
            && ev.step_id === event.step_id
            && ev.pending) {
          return { ...ev, pending: false, _doneAt: Date.now() }
        }
        return ev
      })
      last.toolEvents = [...last.toolEvents, stamped]
      return
    }

    if (event.type === 'tool_call') {
      stamped.pending = true
      stamped._startedAt = Date.now()
    }
    last.toolEvents = [...(last.toolEvents ?? []), stamped]
  }

  function appendToken(text) {
    streamingText.value += text
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') last.text += text
  }

  // Append a chunk of extended-thinking content to the current assistant bubble.
  // Shown in a collapsible reasoning panel.
  function appendThinking(text) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      last.thinking = (last.thinking || '') + text
    }
  }

  // Attach a validation_warning event (e.g. ungrounded URLs) to the current reply.
  function attachWarning(warning) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      last.warnings = [...(last.warnings || []), warning]
    }
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
    addUserMessage, startAssistantMessage, appendToken, appendThinking, attachWarning,
    attachToolEvent, finaliseAssistantMessage, addCompactionMessage, restoreSession, setTitle, clear,
  }
})

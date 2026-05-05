import { ref, onUnmounted } from 'vue'
import { useChatStore }   from '../stores/chat'
import { useChatsStore }  from '../stores/chats'
import { useSystemStore } from '../stores/system'

const DEVICE_KEY = 'chika_device_id'
const MAX_OFFLINE_QUEUE = 20

export function useChika(apiKey = '') {
  const chat   = useChatStore()
  const chats  = useChatsStore()
  const system = useSystemStore()

  const ws = ref(null)
  let reconnectTimer    = null
  let reconnectAttempts = 0
  // Bounded offline queue — flushed on reconnect (4.4)
  const offlineQueue = []

  function buildApiUrl(path) {
    const base = typeof __API_URL__ !== 'undefined' && __API_URL__
      ? __API_URL__
      : `${location.protocol}//${location.host}`
    return `${base.replace(/\/$/, '')}${path}`
  }

  function buildWsUrl() {
    const base   = typeof __API_URL__ !== 'undefined' && __API_URL__
      ? __API_URL__.replace(/^http/, 'ws')
      : `ws://${location.host}`
    const token    = apiKey || localStorage.getItem('chika_api_key') || ''
    const deviceId = sessionStorage.getItem(DEVICE_KEY) || ''
    const params   = new URLSearchParams()
    if (token)    params.set('token',  token)
    if (deviceId) params.set('device', deviceId)
    const qs = params.toString()
    return `${base}/ws/${qs ? '?' + qs : ''}`
  }

  async function patchSettings(patch) {
    const token = apiKey || localStorage.getItem('chika_api_key') || ''
    const headers = { 'Content-Type': 'application/json' }
    if (token) headers['Authorization'] = `Bearer ${token}`
    try {
      const res = await fetch(buildApiUrl('/api/settings'), {
        method: 'PATCH',
        headers,
        body: JSON.stringify(patch),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      system.setSettings(data)
      return data
    } catch (err) {
      console.error('[Chika] patchSettings failed:', err)
      throw err
    }
  }

  function connect() {
    if (ws.value && ws.value.readyState < 2) return
    const url = buildWsUrl()
    console.log('[Chika] Connecting to', url)
    const socket = new WebSocket(url)
    ws.value = socket

    socket.onopen = () => {
      console.log('[Chika] WS OPEN ✓')
      system.setConnected(true, chat.sessionId || '')
      system.setConnectionError(null)   // clear any displayed error banner (4.3)
      reconnectAttempts = 0
      clearTimeout(reconnectTimer)

      // Flush queued messages sent while offline (4.4)
      while (offlineQueue.length > 0) {
        const payload = offlineQueue.shift()
        socket.send(JSON.stringify(payload))
      }
    }

    socket.onclose = (e) => {
      console.warn('[Chika] WS CLOSED', e.code)
      system.setConnected(false, '')
      // Reset stuck isStreaming so the input isn't locked after a disconnect (4.1)
      chat.finaliseAssistantMessage()
      scheduleReconnect()
    }

    socket.onerror = () => {
      system.setConnected(false, '')
      system.setConnectionError('Connection lost. Reconnecting...')  // (4.3)
    }

    socket.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data)
        handleEvent(event)
      } catch (err) {
        console.error('[Chika] parse error', err)
      }
    }
  }

  function scheduleReconnect() {
    // Clear any pending timer before scheduling a new one — prevents
    // multiple concurrent reconnect loops piling up (4.2)
    clearTimeout(reconnectTimer)
    const delay = Math.min(1000 * 2 ** reconnectAttempts, 30000)
    reconnectAttempts++
    reconnectTimer = setTimeout(connect, delay)
  }

  function handleEvent(event) {
    system.pushEvent(event)

    switch (event.type) {
      case 'session_info':
        // Server tells us who we are — store the opaque device token
        if (event.device_id) sessionStorage.setItem(DEVICE_KEY, event.device_id)
        chat.restoreSession(event)
        system.setConnected(true, event.session_id || '')
        break

      case 'chat_list':
        chats.setChats(event)
        break

      case 'chat_title':
        chat.setTitle(event.title)
        break

      case 'token':
        chat.appendToken(event.text)
        break

      case 'thinking':
        // Extended-thinking delta: stream into the collapsible reasoning
        // panel on the current assistant bubble.
        chat.appendThinking(event.text || '')
        break

      case 'thinking_end':
        // The content_block boundary — no-op on the UI side, thinking panel
        // is already rendered from accumulated text. Swallow silently so it
        // doesn't fall through to the default handler.
        break

      case 'validation_warning':
        // Post-response grounding check flagged something (ungrounded URLs,
        // citations without retrieval). Attach to the current bubble.
        chat.attachWarning(event)
        break

      case 'done':
        chat.finaliseAssistantMessage()
        break

      case 'error':
        chat.appendToken(`\n\n[Error: ${event.message}]`)
        chat.finaliseAssistantMessage()
        break

      case 'compaction':
        chat.addCompactionMessage(event)
        break

      case 'workflow_start':
      case 'step_start':
      case 'tool_call':
      case 'tool_result':
      case 'step_done':
      case 'workflow_done':
      case 'loop_iteration':
      case 'condition_eval':
      case 'variable_set':
        chat.attachToolEvent(event)
        break

      case 'extension_status':
        system.setExtensionConnected(!!event.connected)
        break

      case 'ext_chat_turn':
        // Extension popup started a new chat turn — mirror it to the main
        // frontend so it appears naturally in the conversation in real time.
        // display_text is the user's original message (without tab context).
        chat.addUserMessage(event.user_text + ' ↗')
        chat.startAssistantMessage()
        break

      case 'browser_watch_trigger':
        // Push as a tool event so it appears inline in the chat
        chat.attachToolEvent(event)
        break

      case 'settings_info':
      case 'settings_update':
        system.setSettings(event)
        break
    }
  }

  function _wsSend(payload) {
    if (!ws.value || ws.value.readyState !== WebSocket.OPEN) {
      // Buffer up to MAX_OFFLINE_QUEUE messages; drop if full and notify user (4.4)
      if (offlineQueue.length < MAX_OFFLINE_QUEUE) {
        offlineQueue.push(payload)
      } else {
        system.setConnectionError('Message dropped: offline queue is full. Please wait for reconnection.')
      }
      connect()
      return
    }
    ws.value.send(JSON.stringify(payload))
  }

  function send(text) {
    chat.addUserMessage(text)
    chat.startAssistantMessage()
    _wsSend({ type: 'user_message', text })
  }

  function stop() {
    _wsSend({ type: 'stop' })
  }

  function newChat() {
    chat.clear()
    system.clearSession()
    _wsSend({ type: 'new_chat' })
  }

  function loadChat(chatId) {
    chat.clear()
    system.clearSession()
    _wsSend({ type: 'switch_chat', chat_id: chatId })
  }

  function deleteChat(chatId) {
    _wsSend({ type: 'delete_chat', chat_id: chatId })
  }

  function switchProfile(name) {
    _wsSend({ type: 'switch_profile_request', name })
  }

  function approve(request_id, approved, password = '') {
    // Four call shapes:
    //   approve(id, true)                 legacy boolean confirm
    //   approve(id, true, pwd)            password-gated approval
    //   approve(id, {scope: 'session'})   workspace_scope picker
    //   approve(id, {action: 'edit',
    //              feedback: 'change X'}) plan_review picker
    // We normalise here so the backend always receives a consistent
    // approval_response payload regardless of which modal fired it.
    system.resolveApproval(request_id)
    if (approved && typeof approved === 'object') {
      if ('scope' in approved) {
        _wsSend({
          type:       'approval_response',
          request_id,
          approved:   approved.scope !== 'deny',
          scope:      approved.scope,
          password:   '',
        })
        return
      }
      if ('action' in approved) {
        const action = approved.action
        _wsSend({
          type:       'approval_response',
          request_id,
          approved:   action !== 'deny',
          action,
          feedback:   approved.feedback || '',
          reason:     approved.reason   || '',
          password:   '',
        })
        return
      }
    }
    _wsSend({ type: 'approval_response', request_id, approved, password })
  }

  function answerQuestion(request_id, answer) {
    // answer: { choice, choice_index, choices?, choice_indices?, notes? }
    system.resolveQuestion(request_id)
    _wsSend({ type: 'user_question_response', request_id, ...answer })
  }

  function reset() {
    _wsSend({ type: 'reset' })
    chat.clear()
    system.clearSession()
  }

  function ping() {
    _wsSend({ type: 'ping' })
  }

  onUnmounted(() => {
    clearTimeout(reconnectTimer)
    ws.value?.close()
  })

  connect()

  return { send, stop, reset, ping, approve, answerQuestion, switchProfile, loadChat, newChat, deleteChat, patchSettings }
}

import { ref, onUnmounted } from 'vue'
import { useChatStore }   from '../stores/chat'
import { useChatsStore }  from '../stores/chats'
import { useSystemStore } from '../stores/system'

const DEVICE_KEY = 'chika_device_id'

export function useChika(apiKey = '') {
  const chat   = useChatStore()
  const chats  = useChatsStore()
  const system = useSystemStore()

  const ws = ref(null)
  let reconnectTimer    = null
  let reconnectAttempts = 0

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

  function connect() {
    if (ws.value && ws.value.readyState < 2) return
    const url = buildWsUrl()
    console.log('[Chika] Connecting to', url)
    const socket = new WebSocket(url)
    ws.value = socket

    socket.onopen = () => {
      console.log('[Chika] WS OPEN ✓')
      system.setConnected(true, chat.sessionId || '')
      reconnectAttempts = 0
      clearTimeout(reconnectTimer)
    }

    socket.onclose = (e) => {
      console.warn('[Chika] WS CLOSED', e.code)
      system.setConnected(false, '')
      scheduleReconnect()
    }

    socket.onerror = () => system.setConnected(false, '')

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
    }
  }

  function _wsSend(payload) {
    if (!ws.value || ws.value.readyState !== WebSocket.OPEN) {
      connect()
      setTimeout(() => _wsSend(payload), 500)
      return
    }
    ws.value.send(JSON.stringify(payload))
  }

  function send(text) {
    chat.addUserMessage(text)
    chat.startAssistantMessage()
    _wsSend({ type: 'user_message', text })
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
    system.resolveApproval(request_id)
    _wsSend({ type: 'approval_response', request_id, approved, password })
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

  return { send, reset, ping, approve, switchProfile, loadChat, newChat, deleteChat }
}

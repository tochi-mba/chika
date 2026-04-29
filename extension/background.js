/**
 * background.js — Chika Extension Service Worker
 *
 * Responsibilities:
 *   - Maintain WebSocket connection to /ws/extension/
 *   - Receive browser_command messages and dispatch to actions.js
 *   - Send browser_action_result / browser_action_error back
 *   - Maintain in-memory + persisted chat state for the popup
 *   - Route extension chat messages to/from the Chika server
 *   - Relay watch_trigger events from content scripts
 */

import * as ws      from './lib/ws_client.js'
import * as actions from './lib/actions.js'
import { isAllowedAction } from './lib/security.js'
import { getWatches, getSettings } from './lib/storage.js'

// ── Device identity ───────────────────────────────────────────────────────────
// Each extension instance has a stable device ID stored in chrome.storage.local.
// This lets the server route back to the same session across SW restarts.

async function getOrCreateDeviceId() {
  const data = await chrome.storage.local.get('extensionDeviceId')
  if (data.extensionDeviceId) return data.extensionDeviceId
  const id = 'ext_' + crypto.randomUUID().replace(/-/g, '')
  await chrome.storage.local.set({ extensionDeviceId: id })
  return id
}

// ── Chat state ────────────────────────────────────────────────────────────────
// In-memory (fast) + mirrored to chrome.storage.session (survives SW restarts).

const MAX_MESSAGES = 100

const chatState = {
  messages:         [],     // [{id, role, text, toolEvents: []}]
  isStreaming:      false,
  currentMsg:       null,   // in-progress assistant turn
  linkedSessionId:  '',
  linkedTitle:      '',
  linkedProfile:    '',
  pendingApprovals: [],     // [{request_id, tool, args, message, approval_type}]
  pendingQuestions: [],     // [{request_id, question, options, header, multi_select}]
  authError:        false,
  connected:        false,
}

// True once the server has sent linked_session on the CURRENT connection.
// Resets to false on every disconnect so a stale stored session ID from
// chrome.storage.session can't trick the popup into thinking it's ready.
let _sessionConfirmed = false

// ── Pending message queue ─────────────────────────────────────────────────────
// When a message is sent before linked_session arrives (SW restart race),
// we queue it here and flush automatically once the session is linked.

let _pendingMsg = null       // { text, includeTabText } | null
let _pendingMsgTimer = null  // timeout handle
const PENDING_TIMEOUT_MS = 8000

function _clearPendingMsg() {
  _pendingMsg = null
  if (_pendingMsgTimer) { clearTimeout(_pendingMsgTimer); _pendingMsgTimer = null }
}

async function loadChatState() {
  try {
    const data = await chrome.storage.session.get('chikaChat')
    if (data.chikaChat) {
      const saved = data.chikaChat
      chatState.messages        = saved.messages || []
      chatState.linkedSessionId = saved.linkedSessionId || ''
      chatState.linkedTitle     = saved.linkedTitle || ''
      chatState.linkedProfile   = saved.linkedProfile || ''
    }
  } catch (e) {
    console.warn('[Chika] Failed to load chat state:', e)
  }
}

async function persistChatState() {
  try {
    await chrome.storage.session.set({
      chikaChat: {
        // Strip transient _queued flags — pending messages are not persisted
        // because _pendingMsg is lost on SW restart anyway.
        messages:        chatState.messages
          .filter(m => !m._queued)
          .slice(-MAX_MESSAGES),
        linkedSessionId: chatState.linkedSessionId,
        linkedTitle:     chatState.linkedTitle,
        linkedProfile:   chatState.linkedProfile,
      },
    })
  } catch {}
}

function getPublicState() {
  return {
    messages:         chatState.messages,
    currentMsg:       chatState.currentMsg,
    isStreaming:      chatState.isStreaming,
    linkedSessionId:  chatState.linkedSessionId,
    linkedTitle:      chatState.linkedTitle,
    linkedProfile:    chatState.linkedProfile,
    pendingApprovals: chatState.pendingApprovals,
    pendingQuestions: chatState.pendingQuestions,
    authError:        chatState.authError,
    connected:        chatState.connected,
    // True only when WS is up AND the server has confirmed a session on
    // THIS connection via a linked_session message.  Resets on every
    // disconnect so a stale stored session ID can't prematurely unlock
    // the send button before the server confirms the new session.
    sessionReady:     !!(chatState.connected && _sessionConfirmed),
  }
}

function notifyPopup(type, payload = {}) {
  chrome.runtime.sendMessage({ type, ...payload }).catch(() => {})
}

// ── Connection status badge ───────────────────────────────────────────────────

function setBadge(connected) {
  chatState.connected = connected
  chrome.action.setBadgeBackgroundColor({ color: connected ? '#3dd68c' : '#e05c5c' })
  chrome.action.setBadgeText({ text: connected ? '' : '!' })
}

// ── Browser command dispatch ──────────────────────────────────────────────────

const DISPATCH = {
  get_tab_list:  args => actions.getTabList(args),
  get_active_tab:args => actions.getActiveTab(args),
  get_tab_text:  args => actions.getTabText(args),
  get_page_var:  args => actions.getPageVar(args),
  get_tab_dom:   args => actions.getTabDom(args),
  get_element:   args => actions.getElement(args),
  screenshot:    args => actions.takeScreenshot(args),
  navigate:      args => actions.navigate(args),
  open_tab:      args => actions.openTab(args),
  close_tab:     args => actions.closeTab(args),
  switch_tab:    args => actions.switchTab(args),
  click:         args => actions.clickElement(args),
  fill_input:    args => actions.fillInput(args),
  scroll:        args => actions.scrollPage(args),
  watch_element: args => actions.watchElement(args),
  unwatch:       args => actions.unwatchElement(args),
  list_watches:  args => actions.listWatches(args),
}

async function handleCommand(msg) {
  const { request_id, action, args = {} } = msg

  if (!isAllowedAction(action)) {
    ws.send({ type: 'browser_action_error', request_id, error: 'action_not_allowed',
              message: `Action '${action}' is not in the allowlist.` })
    return
  }

  const handler = DISPATCH[action]
  if (!handler) {
    ws.send({ type: 'browser_action_error', request_id, error: 'handler_not_found',
              message: `No handler for action '${action}'.` })
    return
  }

  try {
    const result = await handler(args)
    ws.send({ type: 'browser_action_result', request_id, result })
  } catch (err) {
    console.error(`[Chika] Action '${action}' threw:`, err)
    ws.send({ type: 'browser_action_error', request_id, error: 'handler_exception',
              message: err.message })
  }
}

// ── Active tab capture ────────────────────────────────────────────────────────
// Called before sending a chat message so Claude knows what tab the user is on.

async function captureActiveTab(includeText = false) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
    if (!tab) return null

    const result = { url: tab.url, title: tab.title, tabId: tab.id }

    if (includeText && tab.url
        && !tab.url.startsWith('chrome://')
        && !tab.url.startsWith('chrome-extension://')
        && !tab.url.startsWith('edge://')
        && !tab.url.startsWith('about:')) {
      try {
        const [{ result: text }] = await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          func: () => {
            const el = document.body
            if (!el) return ''
            return (el.innerText || el.textContent || '').slice(0, 3000)
          },
        })
        if (text) result.text = text
      } catch {
        // Restricted page — skip text, still send URL/title
      }
    }

    return result
  } catch {
    return null
  }
}

// ── WebSocket lifecycle ───────────────────────────────────────────────────────

ws.onConnect(async () => {
  setBadge(true)
  chatState.authError = false
  notifyPopup('connection_status', { connected: true })

  restoreWatches()

  // Identify ourselves — server links us to the most recent frontend session
  const deviceId = await getOrCreateDeviceId()
  console.log('[Chika] Sending extension_hello device_id=' + deviceId)
  ws.send({ type: 'extension_hello', device_id: deviceId })
})

ws.onDisconnect((code) => {
  setBadge(false)
  chatState.isStreaming      = false
  chatState.currentMsg       = null
  chatState.pendingApprovals = []
  chatState.pendingQuestions = []
  _sessionConfirmed = false  // server must re-confirm session on next connection
  notifyPopup('connection_status', { connected: false })

  if (code === 4001) {
    chatState.authError = true
    console.warn('[Chika] Auth failed (code 4001). Check API key in Options.')
    notifyPopup('auth_error')
  }
})

ws.onMessage(async (msg) => {

  // ── Browser RPC ─────────────────────────────────────────────────────────────
  if (msg.type === 'browser_command') {
    await handleCommand(msg)
    return
  }

  if (msg.type === 'extension_ready') {
    console.log('[Chika] Handshake OK. Protocol version:', msg.protocol_version)
    return
  }

  if (msg.type === 'ping') {
    ws.send({ type: 'pong' })
    return
  }

  // ── Session linking ─────────────────────────────────────────────────────────
  // Server pushes this whenever the linked frontend tab changes conversation.

  if (msg.type === 'linked_session') {
    const sessionChanged = msg.session_id !== chatState.linkedSessionId
    chatState.linkedSessionId = msg.session_id || ''
    chatState.linkedTitle     = msg.title || ''
    chatState.linkedProfile   = msg.profile || ''
    _sessionConfirmed = true  // server has confirmed a valid session for this connection
    console.log('[Chika] linked_session received session_id=' + chatState.linkedSessionId + ' sessionReady=true')

    // Load message history from server when session changes OR when we have
    // no local non-queued messages (e.g. fresh SW restart that lost session state).
    // Preserve any queued messages so they stay visible while flushing.
    const nonQueued = chatState.messages.filter(m => !m._queued)
    if ((sessionChanged || nonQueued.length === 0) && msg.messages && msg.messages.length > 0) {
      const queued = chatState.messages.filter(m => m._queued)
      chatState.messages = [
        ...msg.messages.map((m, i) => ({
          id: `hist_${i}`, role: m.role, text: m.text, toolEvents: [],
        })),
        ...queued,
      ]
      await persistChatState()
    }

    // Flush any message queued before the session was linked
    if (_pendingMsg && chatState.linkedSessionId) {
      const { text, includeTabText } = _pendingMsg
      _clearPendingMsg()
      // Small delay so all state is settled before dispatch
      setTimeout(() => _dispatchChatMessage(text, includeTabText), 30)
    }

    notifyPopup('state_update', { state: getPublicState() })
    return
  }

  // ── Chat streaming events ───────────────────────────────────────────────────

  if (msg.type === 'ext_chat_start') {
    chatState.isStreaming = true
    chatState.currentMsg  = {
      id:         'msg_' + Date.now(),
      role:       'assistant',
      text:       '',
      toolEvents: [],
    }
    notifyPopup('state_update', { state: getPublicState() })
    return
  }

  if (msg.type === 'token') {
    if (chatState.currentMsg) {
      chatState.currentMsg.text += msg.text || ''
    }
    notifyPopup('token', { text: msg.text || '' })
    return
  }

  if (msg.type === 'tool_call') {
    if (chatState.currentMsg) {
      chatState.currentMsg.toolEvents.push({
        kind: 'call',
        tool: msg.tool,
        args: msg.args,
        id:   msg.id || msg.step_id || (msg.tool + '_' + Date.now()),
      })
      notifyPopup('tool_event', { event: chatState.currentMsg.toolEvents.at(-1) })
    }
    return
  }

  if (msg.type === 'tool_result') {
    if (chatState.currentMsg) {
      chatState.currentMsg.toolEvents.push({
        kind:   'result',
        tool:   msg.tool,
        result: msg.result,
        error:  msg.error,
        id:     msg.id || (msg.tool + '_result'),
      })
      notifyPopup('tool_event', { event: chatState.currentMsg.toolEvents.at(-1) })
    }
    return
  }

  if (msg.type === 'ext_chat_done') {
    if (chatState.currentMsg) {
      chatState.messages.push(chatState.currentMsg)
      if (chatState.messages.length > MAX_MESSAGES) {
        chatState.messages = chatState.messages.slice(-MAX_MESSAGES)
      }
      chatState.currentMsg = null
    }
    chatState.isStreaming = false
    await persistChatState()
    notifyPopup('state_update', { state: getPublicState() })
    return
  }

  if (msg.type === 'ext_chat_error') {
    console.warn('[Chika] ext_chat_error:', msg.error_code, msg.message)
    chatState.isStreaming = false
    if (chatState.currentMsg && chatState.currentMsg.text) {
      // Partial response — keep it but mark as errored
      chatState.messages.push({ ...chatState.currentMsg, error: true })
    } else {
      // Error before any response started — push a visible error row so the
      // user sees it in the chat rather than just a transient toast
      chatState.messages.push({
        id:         'err_' + Date.now(),
        role:       'error',
        text:       msg.message || 'Something went wrong — please try again.',
        toolEvents: [],
      })
    }
    if (chatState.messages.length > MAX_MESSAGES) {
      chatState.messages = chatState.messages.slice(-MAX_MESSAGES)
    }
    chatState.currentMsg = null
    await persistChatState()
    notifyPopup('state_update', { state: getPublicState() })
    return
  }

  // ── Approval request from server ────────────────────────────────────────────

  if (msg.type === 'approval_required') {
    chatState.pendingApprovals.push({
      request_id:    msg.request_id,
      tool:          msg.tool,
      args:          msg.args,
      message:       msg.message,
      approval_type: msg.approval_type || 'confirm',
    })
    notifyPopup('approval_required', { approval: chatState.pendingApprovals.at(-1) })
    notifyPopup('state_update', { state: getPublicState() })
    return
  }

  // ── Question request from server ────────────────────────────────────────────

  if (msg.type === 'user_question') {
    chatState.pendingQuestions.push({
      request_id:   msg.request_id,
      question:     msg.question,
      options:      msg.options || [],
      header:       msg.header || '',
      multi_select: msg.multi_select || false,
    })
    notifyPopup('user_question', { question: chatState.pendingQuestions.at(-1) })
    notifyPopup('state_update', { state: getPublicState() })
    return
  }
})

// ── Send a chat message ───────────────────────────────────────────────────────

async function handleSendChatMessage(text, includeTabText) {
  text = (text || '').trim()
  if (!text) return { error: 'Empty message' }
  if (chatState.isStreaming) return { error: 'Chika is busy — wait for the current response to finish' }

  // Supersede any previously queued message
  _clearPendingMsg()

  // If WS is down or session not confirmed by server yet, queue the message.
  // It will be flushed automatically when linked_session arrives after reconnect.
  const needsQueue = !ws.isConnected() || !_sessionConfirmed
  if (needsQueue) {
    _pendingMsg = { text, includeTabText }

    // Timeout — give up and surface an error if the session never links
    _pendingMsgTimer = setTimeout(() => {
      _clearPendingMsg()
      // Remove the queued placeholder
      chatState.messages = chatState.messages.filter(m => !m._queued)
      chatState.messages.push({
        id:         'err_' + Date.now(),
        role:       'error',
        text:       'Could not reach Chika — check the extension is connected and try again.',
        toolEvents: [],
      })
      notifyPopup('state_update', { state: getPublicState() })
    }, PENDING_TIMEOUT_MS)

    // Show user message immediately as a queued placeholder
    chatState.messages.push({
      id:         'msg_' + Date.now(),
      role:       'user',
      text,
      toolEvents: [],
      _queued:    true,
    })
    notifyPopup('state_update', { state: getPublicState() })
    return { ok: true }
  }

  return _dispatchChatMessage(text, includeTabText)
}

// Internal: actually send the message over WS (session must be linked).
async function _dispatchChatMessage(text, includeTabText) {
  const deviceId   = await getOrCreateDeviceId()
  const active_tab = await captureActiveTab(includeTabText)

  // Confirm any queued placeholder for this text, or add a fresh user message
  const qIdx = chatState.messages.findLastIndex(m => m._queued && m.text === text)
  if (qIdx !== -1) {
    const { _queued, ...confirmed } = chatState.messages[qIdx]
    chatState.messages[qIdx] = confirmed
  } else {
    chatState.messages.push({ id: 'msg_' + Date.now(), role: 'user', text, toolEvents: [] })
  }
  notifyPopup('state_update', { state: getPublicState() })

  console.log('[Chika] Sending extension_chat_message session_id=' + chatState.linkedSessionId + ' text=' + text.slice(0, 40))
  const sent = ws.send({
    type:       'extension_chat_message',
    text,
    device_id:  deviceId,
    session_id: chatState.linkedSessionId,
    active_tab,
  })

  if (!sent) {
    // WS dropped between check and send — requeue so the message is
    // retried automatically when the connection is restored.
    _pendingMsg = { text, includeTabText }
    _pendingMsgTimer = setTimeout(() => {
      _clearPendingMsg()
      chatState.messages = chatState.messages.filter(m => m.text !== text || !m._queued)
      chatState.messages.push({
        id: 'err_' + Date.now(), role: 'error',
        text: 'Could not reach Chika — check the extension is connected and try again.',
        toolEvents: [],
      })
      notifyPopup('state_update', { state: getPublicState() })
    }, PENDING_TIMEOUT_MS)
    // Mark the confirmed message as queued again so popup shows pending state
    const idx = chatState.messages.findLastIndex(m => m.text === text && !m._queued && m.role === 'user')
    if (idx !== -1) chatState.messages[idx]._queued = true
    notifyPopup('state_update', { state: getPublicState() })
    return { ok: true }
  }

  return { ok: true }
}

// ── Content script + popup message relay ─────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (msg.type === 'watch_trigger') {
    ws.send({ type: 'browser_event', event: 'watch_trigger',
              watch_id: msg.watch_id, data: msg.data })

  } else if (msg.type === 'watch_cancelled') {
    ws.send({ type: 'browser_event', event: 'watch_cancelled',
              watch_id: msg.watch_id, reason: msg.reason ?? 'navigation' })

  } else if (msg.type === 'request_status') {
    sendResponse({ connected: ws.isConnected() })

  } else if (msg.type === 'request_chat_state') {
    sendResponse({ state: getPublicState() })

  } else if (msg.type === 'cancel_watch') {
    ws.send({ type: 'browser_event', event: 'watch_cancelled',
              watch_id: msg.watch_id, reason: 'user_cancelled' })

  } else if (msg.type === 'reconnect') {
    ws.disconnect()
    setTimeout(() => ws.connect(), 300)

  } else if (msg.type === 'send_chat_message') {
    handleSendChatMessage(msg.text, msg.includeTabText || false)
      .then(result => sendResponse(result))
      .catch(err  => sendResponse({ error: err.message }))
    return true  // keep channel open for async response

  } else if (msg.type === 'send_approval_response') {
    const idx = chatState.pendingApprovals.findIndex(a => a.request_id === msg.request_id)
    if (idx !== -1) chatState.pendingApprovals.splice(idx, 1)
    ws.send({
      type:       'extension_approval_response',
      request_id: msg.request_id,
      approved:   msg.approved,
      password:   msg.password || '',
    })
    notifyPopup('state_update', { state: getPublicState() })
    sendResponse({ ok: true })

  } else if (msg.type === 'send_question_response') {
    const idx = chatState.pendingQuestions.findIndex(q => q.request_id === msg.request_id)
    if (idx !== -1) chatState.pendingQuestions.splice(idx, 1)
    ws.send({
      type:            'extension_question_response',
      request_id:      msg.request_id,
      choice:          msg.choice,
      choice_index:    msg.choice_index ?? -1,
      choices:         msg.choices || [],
      choice_indices:  msg.choice_indices || [],
      notes:           msg.notes || '',
    })
    notifyPopup('state_update', { state: getPublicState() })
    sendResponse({ ok: true })
  }
})

// ── Watch restoration after SW restart ───────────────────────────────────────

async function restoreWatches() {
  const watches = await getWatches()
  const entries = Object.values(watches)
  if (entries.length === 0) return
  console.log(`[Chika] Restoring ${entries.length} watch(es) after SW restart…`)
  for (const { watch_id, tab_id, selector, debounce_ms } of entries) {
    if (!tab_id) continue
    const tab = await chrome.tabs.get(tab_id).catch(() => null)
    if (!tab) continue
    chrome.tabs.sendMessage(tab_id, {
      type:        'setup_watch',
      watch_id,
      selector,
      debounce_ms: debounce_ms ?? 1000,
    }).catch(() => {})
  }
}

// ── Tab/window lifecycle cleanup ──────────────────────────────────────────────

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const watches = await getWatches()
  for (const [watch_id, record] of Object.entries(watches)) {
    if (record.tab_id === tabId) {
      ws.send({ type: 'browser_event', event: 'watch_cancelled',
                watch_id, reason: 'tab_closed' })
      const { removeWatch } = await import('./lib/storage.js')
      await removeWatch(watch_id)
    }
  }
})

// ── Notifications (fallback approval when popup is closed) ───────────────────

chrome.notifications.onButtonClicked.addListener((notificationId) => {
  chrome.notifications.clear(notificationId)
})

// ── Startup ───────────────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(async () => {
  // Fired on install and extension update — no-op here since the module-level
  // loadChatState().then(ws.connect) below handles the initial connection.
})

// Single connection entry point — covers every SW start:
// install, update, browser restart, and Chrome killing/restarting the SW.
// onStartup / onInstalled are NOT used for the connect call to avoid
// creating duplicate sockets (both events fire on the same SW activation).
loadChatState().then(() => ws.connect())

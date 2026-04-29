/**
 * ws_client.js — WebSocket client with exponential-backoff reconnect
 *
 * Manages the persistent connection to Chika's /ws/extension/ endpoint.
 * Reconnects automatically on disconnect with backoff: 1s, 2s, 4s, 8s, max 30s.
 */

import { getSettings } from './storage.js'

let _ws = null
let _reconnectDelay = 1000
let _reconnecting = false
let _connecting = false      // true while the socket is in CONNECTING state
let _intentionalClose = false

// Callbacks wired up by background.js
let _onMessage  = null
let _onConnect  = null
let _onDisconnect = null

export function onMessage(fn)    { _onMessage    = fn }
export function onConnect(fn)    { _onConnect    = fn }
export function onDisconnect(fn) { _onDisconnect = fn }

export function isConnected() {
  return _ws !== null && _ws.readyState === WebSocket.OPEN
}

export function send(data) {
  if (!isConnected()) return false
  try {
    _ws.send(JSON.stringify(data))
    return true
  } catch {
    return false
  }
}

export async function connect() {
  if (isConnected() || _reconnecting || _connecting) return

  const settings = await getSettings()
  const { serverUrl, apiKey } = settings

  if (!serverUrl) {
    console.warn('[Chika] No server URL configured. Open options to set it.')
    return
  }

  // Build WebSocket URL: http→ws, https→wss
  const wsBase = serverUrl.replace(/^http/, 'ws').replace(/\/$/, '')
  const wsUrl  = apiKey
    ? `${wsBase}/ws/extension/?token=${encodeURIComponent(apiKey)}`
    : `${wsBase}/ws/extension/`

  _intentionalClose = false
  _connecting = true

  try {
    _ws = new WebSocket(wsUrl)
  } catch (err) {
    _connecting = false
    console.warn('[Chika] WebSocket construction failed:', err.message)
    _scheduleReconnect()
    return
  }

  _ws.onopen = () => {
    _connecting = false
    console.log('[Chika] Extension connected to', wsBase)
    _reconnectDelay = 1000  // reset backoff on successful connect
    _reconnecting = false
    if (_onConnect) _onConnect()
  }

  _ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data)
      if (msg.type === 'ping') {
        send({ type: 'pong' })
        return
      }
      if (_onMessage) _onMessage(msg)
    } catch {
      // ignore malformed messages
    }
  }

  _ws.onclose = (evt) => {
    _connecting = false
    _ws = null
    if (_onDisconnect) _onDisconnect(evt.code)
    if (!_intentionalClose) {
      console.log(`[Chika] Disconnected (code ${evt.code}). Reconnecting in ${_reconnectDelay}ms…`)
      _scheduleReconnect()
    }
  }

  _ws.onerror = () => {
    // onerror always precedes onclose, so we let onclose handle reconnect
  }
}

export function disconnect() {
  _intentionalClose = true
  _reconnecting = false
  _connecting = false
  if (_ws) {
    _ws.close()
    _ws = null
  }
}

function _scheduleReconnect() {
  if (_reconnecting) return
  _reconnecting = true
  setTimeout(async () => {
    _reconnecting = false
    await connect()
  }, _reconnectDelay)
  // Exponential backoff, capped at 30s
  _reconnectDelay = Math.min(_reconnectDelay * 2, 30_000)
}

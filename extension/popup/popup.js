/**
 * popup.js — Chika Extension popup chat UI
 *
 * Architecture:
 *   - background.js owns all state and WS communication
 *   - popup requests initial state via chrome.runtime.sendMessage
 *   - background broadcasts incremental updates (token, tool_event, state_update)
 *   - popup only does rendering; all sends go through background
 */

import { getSettings } from '../lib/storage.js'

// ── DOM refs ──────────────────────────────────────────────────────────────────

const statusDot        = document.getElementById('statusDot')
const sessionTitleEl   = document.getElementById('sessionTitle')
const authErrorBanner  = document.getElementById('authError')
const notConfigured    = document.getElementById('notConfigured')
const disconnectedView = document.getElementById('disconnectedView')
const disconnectedSub  = document.getElementById('disconnectedSub')
const retryBtn         = document.getElementById('retryBtn')
const chatView         = document.getElementById('chatView')
const msgList          = document.getElementById('msgList')
const chatInput        = document.getElementById('chatInput')
const sendBtn          = document.getElementById('sendBtn')
const stopBtn          = document.getElementById('stopBtn')
const tabCtxBtn        = document.getElementById('tabCtxBtn')

// ── Local state ───────────────────────────────────────────────────────────────

let state = null           // full state from background
let includeTabText = false  // whether to snapshot page text
let streamingText  = ''     // accumulated text for streaming message
let streamingEl    = null   // DOM node for the in-progress turn
let isAtBottom     = true   // track scroll position
let _pollTimer     = null   // interval ID for disconnected polling

// ── Retry / polling when disconnected ────────────────────────────────────────

function startDisconnectPolling() {
  stopDisconnectPolling()
  _pollTimer = setInterval(() => {
    chrome.runtime.sendMessage({ type: 'request_status' }, (res) => {
      if (chrome.runtime.lastError) return
      if (res?.connected) {
        stopDisconnectPolling()
        refreshState()
      }
    })
  }, 2000)
}

function stopDisconnectPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null }
}

function refreshState() {
  chrome.runtime.sendMessage({ type: 'request_chat_state' }, (response) => {
    if (chrome.runtime.lastError) return
    applyFullState(response?.state)
  })
}

retryBtn?.addEventListener('click', () => {
  retryBtn.textContent = 'Retrying…'
  retryBtn.disabled = true
  chrome.runtime.sendMessage({ type: 'reconnect' })
  // Re-enable after 2s in case connection doesn't come through
  setTimeout(() => {
    retryBtn.textContent = 'Retry'
    retryBtn.disabled = false
  }, 2000)
})

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  const settings = await getSettings()
  if (!settings.serverUrl) {
    showView('notConfigured')
    return
  }

  // Show the server URL in the disconnected hint so the user can verify config
  if (disconnectedSub) {
    disconnectedSub.textContent = `Connecting to ${settings.serverUrl}…`
  }

  // Profile gate: require an explicit pick on every popup open unless the
  // user already authenticated this session. We persist the unlocked flag
  // in chrome.storage.session so it lives only for the browser session.
  const sessionFlag = await chrome.storage.session.get('chika_profile_unlocked')
  if (!sessionFlag.chika_profile_unlocked) {
    await showProfileGate(settings)
    return
  }

  proceedToChat()
}

function proceedToChat() {
  chrome.runtime.sendMessage({ type: 'request_chat_state' }, (response) => {
    if (chrome.runtime.lastError) {
      showView('disconnected')
      startDisconnectPolling()
      return
    }
    if (response?.state?.authError) {
      showAuthError()
      return
    }
    applyFullState(response?.state)
    if (!response?.state?.connected) {
      startDisconnectPolling()
    }
  })
}

// ── Profile gate ─────────────────────────────────────────────────────────

async function showProfileGate(settings) {
  showView('profileGate')

  const listEl     = document.getElementById('profileList')
  const subEl      = document.getElementById('profileGateSub')
  const createBtn  = document.getElementById('profileCreateToggle')
  const pwdView    = document.getElementById('profilePwd')
  const createView = document.getElementById('profileCreate')
  const pwdInput   = document.getElementById('profilePwdInput')
  const pwdError   = document.getElementById('profilePwdError')
  const pwdBack    = document.getElementById('profilePwdBack')
  const pwdSubmit  = document.getElementById('profilePwdSubmit')
  const pwdName    = document.getElementById('profilePwdName')
  const pwdFallback = document.getElementById('profilePwdFallback')
  const newName    = document.getElementById('profileNewName')
  const newPwd     = document.getElementById('profileNewPwd')
  const createSubmit = document.getElementById('profileCreateSubmit')
  const createBack = document.getElementById('profileCreateBack')
  const createError = document.getElementById('profileCreateError')

  let profiles = []
  let chosen   = null

  function authHeaders() {
    const h = { 'Content-Type': 'application/json' }
    if (settings.apiKey) h['Authorization'] = `Bearer ${settings.apiKey}`
    return h
  }

  function buildUrl(path) {
    return `${settings.serverUrl.replace(/\/$/, '')}${path}`
  }

  async function fetchProfiles() {
    listEl.innerHTML = ''
    subEl.textContent = 'Loading profiles…'
    try {
      const res = await fetch(buildUrl('/api/profiles'), {
        headers: authHeaders(),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      profiles = data.profiles || []
      subEl.textContent = 'Pick a profile to load its memory + workspace.'
      profiles.forEach(renderProfileRow)
    } catch (err) {
      subEl.textContent = `Couldn't load profiles: ${err.message}`
    }
  }

  function renderProfileRow(p) {
    const li = document.createElement('li')
    li.className = 'profile-item'
    const btn = document.createElement('button')
    btn.className = 'profile-pick'
    btn.innerHTML = `
      <span class="profile-name"></span>
      <span class="profile-badge"></span>
      <span class="profile-arrow">→</span>`
    btn.querySelector('.profile-name').textContent = p.name
    btn.querySelector('.profile-badge').textContent = p.has_password ? '🔒' : ''
    btn.addEventListener('click', () => pickProfile(p))
    li.appendChild(btn)
    listEl.appendChild(li)
  }

  function pickProfile(p) {
    chosen = p
    if (!p.has_password) {
      submitSelect('')
      return
    }
    pwdName.textContent = `Password for ${p.name}`
    pwdError.style.display = 'none'
    pwdFallback.style.display = 'none'
    pwdInput.value = ''
    listEl.style.display = 'none'
    createBtn.style.display = 'none'
    pwdView.style.display = ''
    setTimeout(() => pwdInput.focus(), 0)
  }

  function backToPickList() {
    chosen = null
    listEl.style.display = ''
    createBtn.style.display = ''
    pwdView.style.display = 'none'
    createView.style.display = 'none'
  }

  async function submitSelect(pwd) {
    if (!chosen) return
    pwdError.style.display = 'none'
    try {
      const res = await fetch(buildUrl('/api/profiles/select'), {
        method:  'POST',
        headers: authHeaders(),
        body:    JSON.stringify({
          session_id: 'extension',
          name:       chosen.name,
          password:   pwd,
        }),
      })
      if (res.status === 401) {
        pwdError.textContent = 'Wrong password.'
        pwdError.style.display = ''
        pwdFallback.style.display = ''
        return
      }
      if (!res.ok) {
        pwdError.textContent = `Failed (${res.status})`
        pwdError.style.display = ''
        return
      }
      await chrome.storage.session.set({ chika_profile_unlocked: '1' })
      proceedToChat()
    } catch (err) {
      pwdError.textContent = `Network error: ${err.message}`
      pwdError.style.display = ''
    }
  }

  async function submitCreate() {
    createError.style.display = 'none'
    const name = newName.value.trim()
    if (!name) {
      createError.textContent = 'Name required.'
      createError.style.display = ''
      return
    }
    try {
      const res = await fetch(buildUrl('/api/profiles/create'), {
        method:  'POST',
        headers: authHeaders(),
        body:    JSON.stringify({ name, password: newPwd.value || null }),
      })
      if (!res.ok) {
        createError.textContent = `Failed (${res.status})`
        createError.style.display = ''
        return
      }
      const data = await res.json()
      chosen = { name: data.name, has_password: data.has_password }
      await submitSelect(newPwd.value || '')
    } catch (err) {
      createError.textContent = `Network error: ${err.message}`
      createError.style.display = ''
    }
  }

  pwdBack.onclick    = backToPickList
  createBack.onclick = backToPickList
  pwdSubmit.onclick  = () => submitSelect(pwdInput.value)
  pwdInput.onkeydown = (e) => { if (e.key === 'Enter') submitSelect(pwdInput.value) }
  pwdFallback.onclick = () => {
    backToPickList()
    createBtn.click()
  }
  createBtn.onclick = () => {
    listEl.style.display = 'none'
    createBtn.style.display = 'none'
    createView.style.display = ''
    setTimeout(() => newName.focus(), 0)
  }
  createSubmit.onclick = submitCreate

  await fetchProfiles()
}

// ── Full state application (initial load or structural change) ────────────────

function applyFullState(s) {
  state = s
  if (!s) { showView('disconnected'); return }

  // Reflect connection in header dot
  setStatusDot(s.connected)
  setSessionTitle(s.linkedTitle)

  if (s.authError) { showAuthError(); return }
  if (!s.connected) { showView('disconnected'); return }

  stopDisconnectPolling()
  showView('chat')

  // Seed streaming text from current state (may have accumulated tokens since
  // the last state_update we received)
  streamingText = s.currentMsg?.text || ''

  renderMessages(s)
  renderApprovals(s.pendingApprovals || [])
  renderQuestions(s.pendingQuestions || [])
  updateSendBtn()

  // Refresh the pet companion — fire-and-forget; won't block anything.
  refreshPet(s).catch(() => {})

  // Plan strip — shows the agent's active plan + accept/edit/reject buttons.
  // Plan lives in s.variables.plan.value (set by the engine's $plan).
  const planVar = s?.variables?.plan
  let plan = null
  if (planVar) {
    const raw = planVar.value ?? planVar.value_preview ?? null
    if (typeof raw === 'string') {
      try { plan = JSON.parse(raw) } catch { plan = null }
    } else if (raw && typeof raw === 'object') {
      plan = raw
    }
  }
  renderPlanStrip(plan)

  // Active shells strip — surface running PIDs with kill buttons.
  renderShellsStrip(s?.shellProcesses || s?.shells || {})
}

// ── Active shells strip ──────────────────────────────────────────────────

const extShells       = document.getElementById('extShells')
const extShellsList   = document.getElementById('extShellsList')
const extShellsCount  = document.getElementById('extShellsCount')
const extShellsKillAll = document.getElementById('extShellsKillAll')

function renderShellsStrip(processes) {
  if (!extShells || !extShellsList) return
  // ``processes`` may arrive as an object (pid → entry) or an array.
  const list = Array.isArray(processes)
    ? processes
    : Object.values(processes || {})
  const running = list.filter(p => p && p.running)
  if (running.length === 0) {
    extShells.style.display = 'none'
    extShellsList.innerHTML = ''
    return
  }
  extShells.style.display = ''
  extShellsCount.textContent = `${running.length} running`
  extShellsList.innerHTML = ''
  for (const proc of running) {
    const li = document.createElement('li')
    li.className = 'ext-shell-row'
    const pid = proc.pid
    const cmd = (proc.command || '').replace(/\s+/g, ' ').slice(0, 80)
    li.innerHTML = `
      <span class="ext-shell-pid"></span>
      <span class="ext-shell-cmd"></span>
      <button class="ext-shell-kill" type="button" title="Kill this process">Kill</button>`
    li.querySelector('.ext-shell-pid').textContent = `pid ${pid}`
    li.querySelector('.ext-shell-cmd').textContent = cmd
    li.querySelector('.ext-shell-kill').addEventListener('click', () => killOneShell(pid))
    extShellsList.appendChild(li)
  }
}

if (extShellsKillAll) extShellsKillAll.addEventListener('click', killAllShells)

async function _shellsRequest(path, opts) {
  const settings = await getSettings()
  const headers = { 'Content-Type': 'application/json' }
  if (settings.apiKey) headers['Authorization'] = `Bearer ${settings.apiKey}`
  return fetch(`${settings.serverUrl.replace(/\/$/, '')}${path}`, {
    method: 'POST', headers, ...(opts || {}),
  })
}

async function killOneShell(pid) {
  try {
    const res = await _shellsRequest(`/api/shells/${pid}/kill`)
    if (!res.ok) console.error('[Chika] kill', pid, 'failed:', res.status)
  } catch (err) { console.error('[Chika] kill', pid, 'failed:', err) }
}

async function killAllShells() {
  try {
    const res = await _shellsRequest('/api/shells/kill_all')
    if (!res.ok) console.error('[Chika] kill_all failed:', res.status)
  } catch (err) { console.error('[Chika] kill_all failed:', err) }
}

// ── Elapsed-time tickers for in-flight tool rows ──────────────────────────
// Keeps a small Map of pid → interval id so we can stop the ticker when the
// matching tool_result lands. Without these, the user sees a static row and
// has no idea whether a long npm-create / web-fetch / scrape is making
// progress or stuck.

const _elapsedTickers = new Map()

function _fmtElapsed(ms) {
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60_000)
  const s = Math.floor((ms % 60_000) / 1000).toString().padStart(2, '0')
  return `${m}m ${s}s`
}

function _startElapsedTicker(row) {
  if (!row || !row.dataset.startedAt) return
  const startedAt = parseInt(row.dataset.startedAt, 10)
  const elapsedEl = row.querySelector('.tool-elapsed')
  if (!elapsedEl) return
  const id = setInterval(() => {
    if (!row.isConnected) {
      _stopElapsedTicker(row)
      return
    }
    elapsedEl.textContent = _fmtElapsed(Date.now() - startedAt)
  }, 250)
  _elapsedTickers.set(row, id)
}

function _stopElapsedTicker(row) {
  const id = _elapsedTickers.get(row)
  if (id) {
    clearInterval(id)
    _elapsedTickers.delete(row)
  }
}

// ── Plan strip ─────────────────────────────────────────────────────────────
//
// Shows the active plan's goal + done/total task count and three buttons:
// accept / edit / reject. Each sends a structured message to the agent;
// the agent uses plan_edit() (or plan_set() for reject) on the backend to
// react. Plan data arrives as variable_set events for `$plan`.

const extPlan         = document.getElementById('extPlan')
const extPlanGoal     = document.getElementById('extPlanGoal')
const extPlanProgress = document.getElementById('extPlanProgress')
const extPlanAccept   = document.getElementById('extPlanAccept')
const extPlanEdit     = document.getElementById('extPlanEdit')
const extPlanReject   = document.getElementById('extPlanReject')

function _planLeaves(tasks) {
  const out = []
  for (const t of tasks ?? []) {
    if (t?.subtasks?.length) out.push(..._planLeaves(t.subtasks))
    else if (t) out.push(t)
  }
  return out
}

function renderPlanStrip(plan) {
  if (!extPlan) return
  if (!plan || !(plan.tasks?.length)) {
    extPlan.style.display = 'none'
    return
  }
  extPlan.style.display = ''
  extPlanGoal.textContent = (plan.goal || '').slice(0, 90) || '(no goal)'
  const leaves = _planLeaves(plan.tasks)
  const done = leaves.filter(t => t.status === 'done').length
  extPlanProgress.textContent = `${done}/${leaves.length || plan.tasks.length}`
}

function _sendPlanMessage(text) {
  if (!text) return
  chrome.runtime.sendMessage(
    { type: 'send_chat_message', text, includeTabText: false },
    () => {},
  )
}

extPlanAccept?.addEventListener('click', () =>
  _sendPlanMessage('Plan looks good. Proceed.'),
)
extPlanReject?.addEventListener('click', () =>
  _sendPlanMessage("I don't like this plan — drop it and propose a different one."),
)
extPlanEdit?.addEventListener('click', () => {
  // Inline prompt — keeps the popup self-contained.
  const fb = window.prompt('What should change about the plan?')
  if (fb && fb.trim()) {
    _sendPlanMessage(`[plan-edit feedback] ${fb.trim()}`)
  }
})

// ── Pet companion ──────────────────────────────────────────────────────────

const extPetEl     = document.getElementById('extPet')
const extPetEmoji  = document.getElementById('extPetEmoji')
const extPetBubble = document.getElementById('extPetBubble')
let _petFetchAt    = 0  // throttle: at most once per 5s

async function refreshPet(s) {
  const now = Date.now()
  if (now - _petFetchAt < 5000) return
  _petFetchAt = now
  if (!extPetEl) return
  const settings = await getSettings()
  const baseUrl = (settings.serverUrl || '').replace(/\/$/, '')
  if (!baseUrl) return
  const profile = s?.linkedProfile || 'default'
  const headers = settings.apiKey ? { 'Authorization': `Bearer ${settings.apiKey}` } : {}
  try {
    const res = await fetch(`${baseUrl}/api/profile/${encodeURIComponent(profile)}/pet`, { headers })
    if (!res.ok) return
    const d = await res.json()
    if (!d.pet) return
    extPetEmoji.textContent = d.pet.emoji || '🐾'
    extPetEl.title = `${d.pet.name} — set in Chika settings`
    extPetEl.style.display = ''
    extPetEl.style.setProperty('--pet-accent', d.pet.accent || '#9d7fff')
  } catch {/* silent */}
}

function showPetBubble(text, ms = 4000) {
  if (!extPetBubble || !text) return
  extPetBubble.textContent = text
  extPetBubble.classList.add('visible')
  clearTimeout(showPetBubble._t)
  showPetBubble._t = setTimeout(() => {
    extPetBubble.classList.remove('visible')
  }, ms)
}

// ── Views ─────────────────────────────────────────────────────────────────────

function showView(view) {
  notConfigured.style.display     = view === 'notConfigured' ? '' : 'none'
  disconnectedView.style.display  = view === 'disconnected'  ? '' : 'none'
  chatView.style.display          = view === 'chat'          ? '' : 'none'
  authErrorBanner.style.display   = view === 'authError'     ? '' : 'none'
  const gate = document.getElementById('profileGate')
  if (gate) gate.style.display = view === 'profileGate' ? '' : 'none'
}

function showAuthError() {
  authErrorBanner.style.display   = ''
  notConfigured.style.display     = 'none'
  disconnectedView.style.display  = 'none'
  chatView.style.display          = 'none'
}

function setStatusDot(connected) {
  statusDot.className = 'status-dot' + (connected ? ' connected' : '')
  statusDot.title     = connected ? 'Connected to Chika' : 'Disconnected'
}

function setSessionTitle(title) {
  sessionTitleEl.textContent  = title || ''
  sessionTitleEl.style.display = title ? '' : 'none'
}

// ── Message rendering ─────────────────────────────────────────────────────────

function renderMessages(s) {
  msgList.innerHTML = ''
  streamingEl = null

  const msgs = s.messages || []

  // Empty state — show a hint so the user knows the chat is ready
  if (msgs.length === 0 && !s.isStreaming) {
    const hint = document.createElement('div')
    hint.className = 'empty-hint'
    hint.textContent = 'Ask Chika anything about your current tab, or just chat.'
    msgList.appendChild(hint)
  }

  for (const msg of msgs) {
    appendMessage(msg, false)
  }

  if (s.isStreaming && s.currentMsg) {
    streamingEl = appendMessage(s.currentMsg, true)
  } else if (s.isStreaming) {
    // Engine is busy but no text yet — show thinking indicator
    streamingEl = appendThinkingRow()
  }

  scrollToBottom(false)
}

function appendMessage(msg, isStreaming) {
  const wrap = document.createElement('div')
  wrap.dataset.msgId = msg.id

  if (msg.role === 'user') {
    wrap.className = 'msg msg-user' + (msg._queued ? ' msg-queued' : '')
    const bubble = document.createElement('div')
    bubble.className = 'bubble bubble-user'
    bubble.textContent = msg.text
    wrap.appendChild(bubble)
  } else if (msg.role === 'error') {
    wrap.className = 'msg msg-error'
    const bubble = document.createElement('div')
    bubble.className = 'bubble bubble-error'
    bubble.textContent = msg.text
    wrap.appendChild(bubble)
  } else {
    wrap.className = 'msg msg-assistant'
    // Tool events first, then text bubble
    const toolHtml = buildToolEventsEl(msg.toolEvents || [])
    if (toolHtml) wrap.appendChild(toolHtml)

    if (msg.text || isStreaming) {
      const bubble = document.createElement('div')
      bubble.className = 'bubble bubble-assistant'
      bubble.innerHTML = formatMarkdown(msg.text || '') +
        (isStreaming ? '<span class="cursor"></span>' : '')
      wrap.appendChild(bubble)
    }
  }

  msgList.appendChild(wrap)
  return wrap
}

function appendThinkingRow() {
  const row = document.createElement('div')
  row.className = 'thinking-row'
  row.innerHTML = `<div class="thinking-dots"><span></span><span></span><span></span></div>`
  msgList.appendChild(row)
  return row
}

// ── Tool events ───────────────────────────────────────────────────────────────

function buildToolEventsEl(events) {
  if (!events || events.length === 0) return null

  const container = document.createElement('div')
  container.className = 'tool-events'

  // Pair calls with results
  const calls = {}
  const order = []
  for (const ev of events) {
    const key = ev.id || ev.tool
    if (ev.kind === 'call') {
      calls[key] = { call: ev, result: null }
      order.push(key)
    } else if (ev.kind === 'result') {
      if (calls[key]) {
        calls[key].result = ev
      } else {
        calls[key] = { call: null, result: ev }
        order.push(key)
      }
    }
  }

  for (const key of order) {
    const { call, result } = calls[key] || {}
    const tool = call?.tool || result?.tool || '?'
    const isRunning = !result
    const isError   = !!result?.error

    const row = document.createElement('div')
    row.className = 'tool-row' + (isRunning ? ' running' : isError ? ' error' : ' done')
    row.dataset.toolKey = key

    const icon = isRunning ? '◌' : isError ? '✗' : '✓'

    // Build context hint: show selector/url arg for quick diagnosis
    let contextHint = ''
    if (!isRunning) {
      const args = call?.args || {}
      if (args.selector)  contextHint = args.selector
      else if (args.url)  contextHint = args.url.replace(/^https?:\/\//, '').slice(0, 40)
    }

    // Error detail: humanise common error codes
    let errorDetail = ''
    if (isError) {
      const err = result.error
      const errMap = {
        selector_not_found:       'Selector not found',
        tab_not_found:            'Tab not found',
        restricted_page:          'Restricted page',
        extension_not_connected:  'Extension not connected',
        incognito_not_permitted:  'Incognito not permitted',
        script_injection_failed:  'Script injection failed',
        response_too_large:       'Response too large',
        timeout:                  'Timed out',
        navigation_blocked:       'Navigation blocked',
        captcha_detected:         'CAPTCHA detected',
        blocked_domain:           'Blocked domain',
        user_denied:              'Denied',
        tab_crashed:              'Tab crashed',
      }
      errorDetail = errMap[err] || err?.replace(/_/g, ' ') || 'Error'
    }

    row.innerHTML =
      `<span class="tool-icon">${icon}</span>` +
      `<span class="tool-name">${escHtml(toolLabel(tool))}</span>` +
      (contextHint ? `<span class="tool-ctx">${escHtml(contextHint)}</span>` : '') +
      (errorDetail ? `<span class="tool-err-detail">${escHtml(errorDetail)}</span>` : '')

    container.appendChild(row)
  }

  return container
}

function toolLabel(name) {
  const map = {
    browser_get_tabs:       'Read tabs',
    browser_get_active_tab: 'Read active tab',
    browser_get_text:       'Read page text',
    browser_get_dom:        'Read DOM',
    browser_get_element:    'Read element',
    browser_screenshot:     'Screenshot',
    browser_navigate:       'Navigate',
    browser_click:          'Click element',
    browser_fill_input:     'Fill input',
    browser_scroll:         'Scroll page',
    browser_open_tab:       'Open tab',
    browser_close_tab:      'Close tab',
    browser_switch_tab:     'Switch tab',
    browser_watch_element:  'Watch element',
    browser_unwatch:        'Unwatch',
    browser_list_watches:   'List watches',
    browser_run_research:   'Run research',
  }
  return map[name] || name.replace(/_/g, ' ')
}

// ── Approval cards ────────────────────────────────────────────────────────────

function renderApprovals(approvals) {
  msgList.querySelectorAll('.approval-card').forEach(el => el.remove())

  for (const approval of approvals) {
    const card = document.createElement('div')
    card.className = 'approval-card'
    card.dataset.requestId = approval.request_id

    const needsPassword = approval.approval_type === 'verify_password' ||
                          approval.approval_type === 'set_password'
    const pwPlaceholder = approval.approval_type === 'set_password'
      ? 'Set password (leave blank for none)'
      : 'Enter password'

    card.innerHTML = `
      <div class="approval-header">
        <span class="approval-icon">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
        </span>
        <span class="approval-title">Approval required</span>
      </div>
      <div class="approval-msg">${escHtml(approval.message || 'Allow: ' + approval.tool)}</div>
      ${needsPassword ? `<input type="password" class="approval-password" placeholder="${escHtml(pwPlaceholder)}" autocomplete="current-password" />` : ''}
      <div class="approval-btns">
        <button class="btn-deny">Deny</button>
        <button class="btn-approve">Allow</button>
      </div>
    `

    const getPassword = () => card.querySelector('.approval-password')?.value || ''

    card.querySelector('.btn-approve').addEventListener('click', () => {
      submitApproval(approval.request_id, true, getPassword())
    })
    card.querySelector('.btn-deny').addEventListener('click', () => {
      submitApproval(approval.request_id, false, '')
    })

    const pwEl = card.querySelector('.approval-password')
    if (pwEl) {
      pwEl.addEventListener('keydown', e => {
        if (e.key === 'Enter') submitApproval(approval.request_id, true, pwEl.value)
      })
    }

    msgList.appendChild(card)
  }

  if (approvals.length > 0) scrollToBottom(true)
}

// ── Question cards ────────────────────────────────────────────────────────────

function renderQuestions(questions) {
  msgList.querySelectorAll('.question-card').forEach(el => el.remove())

  for (const q of questions) {
    const card = document.createElement('div')
    card.className = 'question-card'
    card.dataset.requestId = q.request_id

    const optionsHtml = (q.options || []).map((opt, i) =>
      `<button class="question-option" data-index="${i}">${escHtml(String(opt))}</button>`
    ).join('')

    card.innerHTML = `
      <div class="question-header">${escHtml(q.header || 'Choose an option')}</div>
      <div class="question-text">${escHtml(q.question)}</div>
      <div class="question-options">${optionsHtml}</div>
    `

    card.querySelectorAll('.question-option').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.index, 10)
        if (idx < 0 || idx >= q.options.length) return
        const label = q.options[idx]
        submitQuestion(q.request_id, String(label), idx)
      })
    })

    msgList.appendChild(card)
  }

  if (questions.length > 0) scrollToBottom(true)
}

// ── Submit actions ────────────────────────────────────────────────────────────

function submitApproval(requestId, approved, password) {
  document.querySelector(`.approval-card[data-request-id="${CSS.escape(requestId)}"]`)?.remove()
  chrome.runtime.sendMessage({
    type:       'send_approval_response',
    request_id: requestId,
    approved,
    password,
  })
}

function submitQuestion(requestId, choice, choiceIndex) {
  document.querySelector(`.question-card[data-request-id="${CSS.escape(requestId)}"]`)?.remove()
  chrome.runtime.sendMessage({
    type:           'send_question_response',
    request_id:     requestId,
    choice,
    choice_index:   choiceIndex,
    choices:        [choice],
    choice_indices: [choiceIndex],
  })
}

// ── Send message ──────────────────────────────────────────────────────────────

function sendMessage() {
  const text = chatInput.value.trim()
  if (!text || !state?.sessionReady || state?.isStreaming) return

  chatInput.value = ''
  chatInput.style.height = ''
  // Optimistically mark busy so the button is disabled while the request
  // is in-flight (before ext_chat_start comes back from background).
  if (state) state.isStreaming = true
  updateSendBtn()

  chrome.runtime.sendMessage(
    { type: 'send_chat_message', text, includeTabText },
    (response) => {
      if (response?.error) {
        // Failed to send — restore the input text and clear busy flag
        if (state) state.isStreaming = false
        chatInput.value = text
        chatInput.style.height = 'auto'
        chatInput.style.height = Math.min(chatInput.scrollHeight, 110) + 'px'
        updateSendBtn()
        showToast(response.error)
      }
    }
  )
}

// ── UI helpers ────────────────────────────────────────────────────────────────

function updateSendBtn() {
  const streaming = !!state?.isStreaming
  const canSend   = chatInput.value.trim().length > 0
                 && state?.sessionReady
                 && !streaming

  sendBtn.disabled = !canSend
  sendBtn.style.display = streaming ? 'none' : ''
  stopBtn.style.display = streaming ? ''     : 'none'

  if (state?.connected && !state?.sessionReady) {
    chatInput.placeholder = 'Starting session…'
  } else if (streaming) {
    chatInput.placeholder = 'Responding…'
  } else {
    chatInput.placeholder = 'Message Chika…'
  }
}

function scrollToBottom(smooth) {
  msgList.scrollTo({ top: msgList.scrollHeight, behavior: smooth ? 'smooth' : 'instant' })
}

let toastTimer = null
function showToast(message) {
  let toast = document.getElementById('toast')
  if (!toast) {
    toast = document.createElement('div')
    toast.id = 'toast'
    toast.className = 'toast'
    document.body.appendChild(toast)
  }
  toast.textContent = message
  toast.classList.add('visible')
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 3200)
}

// ── Markdown formatter ────────────────────────────────────────────────────────
// Minimal: escape HTML first (XSS-safe), then apply bold/code/linebreak.
// NOTE: We preserve pre-whitespace in the bubble via CSS white-space:pre-wrap.

function formatMarkdown(text) {
  if (!text) return ''

  // 1. Escape HTML entities
  let out = escHtml(text)

  // 2. Fenced code blocks  ```...```
  out = out.replace(/```([\s\S]*?)```/g, (_, code) =>
    `<pre><code>${code.replace(/^\n/, '')}</code></pre>`
  )

  // 3. Inline code  `...`
  out = out.replace(/`([^`\n]+)`/g, '<code>$1</code>')

  // 4. Bold  **...**
  out = out.replace(/\*\*(.*?)\*\*/gs, '<strong>$1</strong>')

  // 5. Newlines → <br> (only outside pre blocks — skip for now, pre-wrap handles it)
  // We rely on CSS white-space: pre-wrap in the bubble for line breaks

  return out
}

function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

// ── Event listeners ───────────────────────────────────────────────────────────

msgList.addEventListener('scroll', () => {
  const gap = msgList.scrollHeight - msgList.scrollTop - msgList.clientHeight
  isAtBottom = gap < 50
})

chatInput.addEventListener('input', () => {
  // Auto-grow
  chatInput.style.height = 'auto'
  chatInput.style.height = Math.min(chatInput.scrollHeight, 110) + 'px'
  updateSendBtn()
})

chatInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
  if (e.key === 'Escape' && state?.isStreaming) {
    chrome.runtime.sendMessage({ type: 'send_to_server', payload: { type: 'stop' } })
  }
})

sendBtn.addEventListener('click', sendMessage)

stopBtn.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'send_to_server', payload: { type: 'stop' } })
})

tabCtxBtn.addEventListener('click', () => {
  includeTabText = !includeTabText
  tabCtxBtn.setAttribute('aria-pressed', String(includeTabText))
  tabCtxBtn.classList.toggle('active', includeTabText)
  tabCtxBtn.title = includeTabText
    ? 'Page content will be included — click to disable'
    : 'Include current page content as context'
})

// ── Background message listener ───────────────────────────────────────────────
// Handles incremental updates pushed from the service worker.

chrome.runtime.onMessage.addListener((msg) => {

  if (msg.type === 'connection_status') {
    setStatusDot(msg.connected)
    if (!msg.connected) {
      if (state) {
        state.connected    = false
        state.isStreaming  = false
        state.currentMsg   = null
        state.pendingApprovals = []
        state.pendingQuestions = []
      }
      showView('disconnected')
      startDisconnectPolling()
    } else {
      // Just connected — fetch fresh state so messages and session info render
      stopDisconnectPolling()
      refreshState()
    }
    return
  }

  if (msg.type === 'auth_error') {
    showAuthError()
    return
  }

  // Full state replacement — triggered by structural changes
  // (streaming start/end, session link, approvals, errors)
  if (msg.type === 'state_update') {
    const wasStreaming = state?.isStreaming
    state = msg.state

    setStatusDot(state.connected)
    setSessionTitle(state.linkedTitle)

    if (state.authError) { showAuthError(); return }
    if (!state.connected) { showView('disconnected'); return }

    showView('chat')

    // Full re-render on structural changes
    streamingText = state.currentMsg?.text || ''
    renderMessages(state)
    renderApprovals(state.pendingApprovals || [])
    renderQuestions(state.pendingQuestions || [])
    updateSendBtn()
    return
  }

  // Incremental token — update streaming bubble without re-rendering everything
  if (msg.type === 'token') {
    if (!state) return
    if (state.currentMsg) {
      state.currentMsg.text = (state.currentMsg.text || '') + (msg.text || '')
    }
    streamingText += msg.text || ''

    if (streamingEl) {
      // If we had a thinking row, replace it with a real assistant message row
      if (streamingEl.classList.contains('thinking-row')) {
        streamingEl.remove()
        if (state.currentMsg) {
          streamingEl = appendMessage(state.currentMsg, true)
        }
      } else {
        let bubble = streamingEl.querySelector('.bubble-assistant')
        if (!bubble) {
          bubble = document.createElement('div')
          bubble.className = 'bubble bubble-assistant'
          streamingEl.appendChild(bubble)
        }
        bubble.innerHTML = formatMarkdown(streamingText) + '<span class="cursor"></span>'
      }
    }

    if (isAtBottom) scrollToBottom(false)
    return
  }

  // Incremental tool event — update tool rows in the streaming element
  if (msg.type === 'tool_event') {
    if (!streamingEl || streamingEl.classList.contains('thinking-row')) return

    const ev = msg.event
    let toolEvents = streamingEl.querySelector('.tool-events')

    if (!toolEvents) {
      toolEvents = document.createElement('div')
      toolEvents.className = 'tool-events'
      // Insert before the text bubble
      const bubble = streamingEl.querySelector('.bubble-assistant')
      if (bubble) {
        streamingEl.insertBefore(toolEvents, bubble)
      } else {
        streamingEl.appendChild(toolEvents)
      }
    }

    const key = ev.id || ev.tool

    if (ev.kind === 'call') {
      const row = document.createElement('div')
      row.className = 'tool-row running'
      row.dataset.toolKey = key
      row.dataset.startedAt = String(Date.now())
      row.innerHTML =
        `<span class="tool-icon">◌</span>` +
        `<span class="tool-name">${escHtml(toolLabel(ev.tool))}</span>` +
        `<span class="tool-elapsed">0.0s</span>`
      toolEvents.appendChild(row)
      _startElapsedTicker(row)
      showPetBubble(`using ${toolLabel(ev.tool)}…`)

    } else if (ev.kind === 'result') {
      // Find and update the matching call row
      const callRow = toolEvents.querySelector(`[data-tool-key="${CSS.escape(key)}"]`)
      if (callRow) {
        const isError = !!ev.error
        callRow.className = 'tool-row ' + (isError ? 'error' : 'done')
        callRow.querySelector('.tool-icon').textContent = isError ? '✗' : '✓'
        // Stop the elapsed ticker and freeze the final duration.
        _stopElapsedTicker(callRow)
        const elapsedEl = callRow.querySelector('.tool-elapsed')
        if (elapsedEl) {
          const startedAt = parseInt(callRow.dataset.startedAt || '0', 10)
          if (startedAt) {
            elapsedEl.textContent = _fmtElapsed(Date.now() - startedAt)
          }
        }
        return
      }
      // No matching call row — add a standalone result row
      const row = document.createElement('div')
      row.className = 'tool-row ' + (ev.error ? 'error' : 'done')
      row.innerHTML =
        `<span class="tool-icon">${ev.error ? '✗' : '✓'}</span>` +
        `<span class="tool-name">${escHtml(toolLabel(ev.tool))}</span>`
      toolEvents.appendChild(row)
    }

    if (isAtBottom) scrollToBottom(false)
    return
  }

  // New approval during a streaming turn
  if (msg.type === 'approval_required') {
    if (state) {
      // Avoid duplicates
      if (!state.pendingApprovals.find(a => a.request_id === msg.approval.request_id)) {
        state.pendingApprovals.push(msg.approval)
      }
    }
    renderApprovals(state?.pendingApprovals || [msg.approval])
    return
  }

  // New question during a streaming turn
  if (msg.type === 'user_question') {
    if (state) {
      if (!state.pendingQuestions.find(q => q.request_id === msg.question.request_id)) {
        state.pendingQuestions.push(msg.question)
      }
    }
    renderQuestions(state?.pendingQuestions || [msg.question])
    return
  }

  if (msg.type === 'chat_error') {
    showToast(msg.message || 'Something went wrong')
    return
  }
})

// ── Bootstrap ─────────────────────────────────────────────────────────────────

init()

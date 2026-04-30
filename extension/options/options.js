/**
 * options.js — Settings page for the Chika extension
 */

import { getSettings, saveSettings } from '../lib/storage.js'

const serverUrlInput      = document.getElementById('serverUrl')
const apiKeyInput         = document.getElementById('apiKey')
const toggleKeyBtn        = document.getElementById('toggleKey')
const blockedDomainsTA    = document.getElementById('blockedDomains')
const maxTabSlider        = document.getElementById('maxTabContent')
const maxTabLabel         = document.getElementById('maxTabLabel')
const presetSupervisedBtn = document.getElementById('presetSupervised')
const presetAutonomousBtn = document.getElementById('presetAutonomous')
const permCategoryList    = document.getElementById('permCategoryList')
const permLoadStatus      = document.getElementById('permLoadStatus')
const saveBtn             = document.getElementById('saveBtn')
const testBtn             = document.getElementById('testBtn')
const feedback            = document.getElementById('feedback')

// In-memory state for category permissions (populated from server)
let _serverSettings = { autonomy: 'supervised', tool_permissions: {}, categories: {} }
const _pendingPerms = {}  // category → "ask" | "skip" (staged until save)

// ── Load saved settings ───────────────────────────────────────────────────────

async function loadSettings() {
  const s = await getSettings()
  serverUrlInput.value   = s.serverUrl   || 'http://127.0.0.1:8000'
  apiKeyInput.value      = s.apiKey      || ''
  blockedDomainsTA.value = (s.blockedDomains || []).join('\n')
  maxTabSlider.value     = s.maxTabKB    || 500
  updateMaxTabLabel()
  await loadServerSettings(s.serverUrl || 'http://127.0.0.1:8000', s.apiKey || '')
}

async function loadServerSettings(serverUrl, apiKey) {
  try {
    const headers = {}
    if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`
    const res = await fetch(`${serverUrl.replace(/\/$/, '')}/api/settings`, {
      headers,
      signal: AbortSignal.timeout(3000),
    })
    if (res.ok) {
      _serverSettings = await res.json()
      renderCategoryControls()
    } else {
      permLoadStatus.textContent = 'Could not load server settings.'
    }
  } catch {
    permLoadStatus.textContent = 'Server offline — permissions will sync on next save.'
  }
}

function effectivePerm(cat) {
  if (cat in _pendingPerms) return _pendingPerms[cat]
  const explicit = (_serverSettings.tool_permissions || {})[cat]
  if (explicit) return explicit
  return _serverSettings.autonomy === 'autonomous' ? 'skip' : 'ask'
}

function renderCategoryControls() {
  const cats = _serverSettings.categories || {}
  if (!Object.keys(cats).length) {
    permLoadStatus.textContent = 'No categories returned by server.'
    return
  }
  permLoadStatus.style.display = 'none'
  permCategoryList.innerHTML = ''

  for (const [cat, label] of Object.entries(cats)) {
    const row = document.createElement('div')
    row.className = 'perm-row'
    row.innerHTML = `
      <span class="perm-label">${label}</span>
      <div class="perm-toggle">
        <button type="button" class="perm-opt" data-cat="${cat}" data-val="ask">Ask</button>
        <button type="button" class="perm-opt" data-cat="${cat}" data-val="skip">Skip</button>
      </div>
    `
    permCategoryList.appendChild(row)
    updateCategoryRow(cat)
  }

  permCategoryList.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-cat]')
    if (!btn) return
    const cat = btn.dataset.cat
    const val = btn.dataset.val
    _pendingPerms[cat] = val
    updateCategoryRow(cat)
  })
}

function updateCategoryRow(cat) {
  const perm = effectivePerm(cat)
  permCategoryList.querySelectorAll(`[data-cat="${cat}"]`).forEach(btn => {
    btn.classList.toggle('active', btn.dataset.val === perm)
  })
}

presetSupervisedBtn.addEventListener('click', () => {
  Object.keys(_serverSettings.categories || {}).forEach(cat => { _pendingPerms[cat] = 'ask' })
  _pendingPerms.__autonomy = 'supervised'
  Object.keys(_serverSettings.categories || {}).forEach(cat => updateCategoryRow(cat))
})

presetAutonomousBtn.addEventListener('click', () => {
  Object.keys(_serverSettings.categories || {}).forEach(cat => { _pendingPerms[cat] = 'skip' })
  _pendingPerms.__autonomy = 'autonomous'
  Object.keys(_serverSettings.categories || {}).forEach(cat => updateCategoryRow(cat))
})

function updateMaxTabLabel() {
  const kb = parseInt(maxTabSlider.value, 10)
  maxTabLabel.textContent = kb >= 1000 ? `${(kb / 1000).toFixed(1)} MB` : `${kb} KB`
}
maxTabSlider.addEventListener('input', updateMaxTabLabel)

// ── Toggle key visibility ─────────────────────────────────────────────────────

toggleKeyBtn.addEventListener('click', () => {
  apiKeyInput.type = apiKeyInput.type === 'password' ? 'text' : 'password'
})

// ── Save ──────────────────────────────────────────────────────────────────────

saveBtn.addEventListener('click', async () => {
  const serverUrl = serverUrlInput.value.trim().replace(/\/$/, '')
  const apiKey    = apiKeyInput.value.trim()

  if (!serverUrl) {
    showFeedback('error', 'Server URL is required')
    return
  }

  try {
    const parsed = new URL(serverUrl)
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      showFeedback('error', 'Server URL must use http:// or https://')
      return
    }
  } catch {
    showFeedback('error', 'Server URL is not a valid URL')
    return
  }

  if (apiKey.length > 1000) {
    showFeedback('error', 'API key is too long (max 1000 characters)')
    return
  }

  const blocked = blockedDomainsTA.value
    .split('\n')
    .map(d => d.trim().toLowerCase())
    .filter(Boolean)

  await saveSettings({
    serverUrl,
    apiKey,
    blockedDomains: blocked,
    maxTabKB: parseInt(maxTabSlider.value, 10),
  })

  // Push pending permission changes to server (best-effort)
  if (Object.keys(_pendingPerms).length) {
    try {
      const headers = { 'Content-Type': 'application/json' }
      if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`
      const patch = {}
      const autonomyOverride = _pendingPerms.__autonomy
      if (autonomyOverride) patch.autonomy = autonomyOverride
      const catPerms = { ..._pendingPerms }
      delete catPerms.__autonomy
      if (Object.keys(catPerms).length) patch.tool_permissions = catPerms
      if (Object.keys(patch).length) {
        await fetch(`${serverUrl}/api/settings`, {
          method: 'PATCH',
          headers,
          body: JSON.stringify(patch),
          signal: AbortSignal.timeout(4000),
        })
      }
    } catch {
      // Server offline — changes sync when connection is re-established.
    }
  }

  showFeedback('ok', 'Settings saved. The extension will reconnect now.')

  // Tell background to reconnect with new settings
  chrome.runtime.sendMessage({ type: 'reconnect' }).catch(() => {})
})

// ── Test connection ───────────────────────────────────────────────────────────

testBtn.addEventListener('click', async () => {
  const serverUrl = serverUrlInput.value.trim().replace(/\/$/, '')
  if (!serverUrl) {
    showFeedback('error', 'Enter a server URL first')
    return
  }

  testBtn.disabled = true
  testBtn.textContent = 'Testing…'

  try {
    const res = await fetch(`${serverUrl}/health`, { signal: AbortSignal.timeout(5000) })
    const data = await res.json()
    if (data.status === 'ok') {
      showFeedback('ok', `Connected! Provider: ${data.provider} · Model: ${data.model}`)
    } else {
      showFeedback('error', 'Server responded but status is not OK')
    }
  } catch (e) {
    showFeedback('error', `Connection failed: ${e.message}`)
  } finally {
    testBtn.disabled = false
    testBtn.textContent = 'Test connection'
  }
})

// ── Feedback ──────────────────────────────────────────────────────────────────

function showFeedback(type, msg) {
  feedback.className = `feedback ${type === 'error' ? 'err' : 'ok'}`
  feedback.textContent = msg
  clearTimeout(feedback._timer)
  if (type !== 'error') {
    feedback._timer = setTimeout(() => {
      feedback.className = 'feedback'
      feedback.textContent = ''
    }, 4000)
  }
}

loadSettings()

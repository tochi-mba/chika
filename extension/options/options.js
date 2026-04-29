/**
 * options.js — Settings page for the Chika extension
 */

import { getSettings, saveSettings } from '../lib/storage.js'

const serverUrlInput    = document.getElementById('serverUrl')
const apiKeyInput       = document.getElementById('apiKey')
const toggleKeyBtn      = document.getElementById('toggleKey')
const blockedDomainsTA  = document.getElementById('blockedDomains')
const maxTabSlider      = document.getElementById('maxTabContent')
const maxTabLabel       = document.getElementById('maxTabLabel')
const saveBtn           = document.getElementById('saveBtn')
const testBtn           = document.getElementById('testBtn')
const feedback          = document.getElementById('feedback')

// ── Load saved settings ───────────────────────────────────────────────────────

async function loadSettings() {
  const s = await getSettings()
  serverUrlInput.value   = s.serverUrl   || 'http://127.0.0.1:8000'
  apiKeyInput.value      = s.apiKey      || ''
  blockedDomainsTA.value = (s.blockedDomains || []).join('\n')
  maxTabSlider.value     = s.maxTabKB    || 500
  updateMaxTabLabel()
}

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

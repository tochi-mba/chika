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

// ── Skills (parity with Vue Settings → Skills tab) ───────────────────────────
//
// Lists every skill the engine knows about (live + disabled) with a per-row
// toggle. Click flips the row + PATCHes /api/settings.skills_disabled, which
// triggers reload_skills() server-side — the change is live on the next turn,
// no restart needed.

const skillList         = document.getElementById('skillList')
const skillLoadStatus   = document.getElementById('skillLoadStatus')
const skillError        = document.getElementById('skillError')

let _skills = []                // [{ name, description, tools, disabled }]
let _skillsDisabled = []        // mirror of settings.skills_disabled

function skillHeaders() {
  const h = { 'Content-Type': 'application/json' }
  const k = apiKeyInput.value || ''
  if (k) h['Authorization'] = `Bearer ${k}`
  return h
}

function skillServer() {
  return (serverUrlInput.value || 'http://127.0.0.1:8000').replace(/\/$/, '')
}

async function loadSkills() {
  skillError.hidden = true
  try {
    const res = await fetch(`${skillServer()}/api/skills`, {
      headers: skillHeaders(),
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    _skills = data.skills || []
    _skillsDisabled = data.disabled || []
    renderSkills()
  } catch (e) {
    skillLoadStatus.textContent = 'Server offline — skill toggles unavailable.'
    skillLoadStatus.style.display = ''
  }
}

function renderSkills() {
  if (!_skills.length) {
    skillLoadStatus.textContent = 'No skills returned by server.'
    return
  }
  skillLoadStatus.style.display = 'none'
  skillList.innerHTML = ''

  for (const s of _skills) {
    const row = document.createElement('div')
    row.className = 'skill-row' + (s.disabled ? ' disabled' : '')
    const toolCount = (s.tools || []).length
    const escapedName = String(s.name).replace(/[<>&"']/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c]))
    const escapedDesc = String(s.description || '').replace(/[<>&"']/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c]))
    row.innerHTML = `
      <div class="skill-meta">
        <div class="skill-head">
          <span class="skill-name">${escapedName}</span>
          <span class="skill-tool-count">${toolCount} tool${toolCount === 1 ? '' : 's'}</span>
          ${s.disabled ? '<span class="skill-chip">off</span>' : ''}
        </div>
        ${escapedDesc ? `<div class="skill-desc">${escapedDesc}</div>` : ''}
      </div>
      <label class="switch">
        <input type="checkbox" data-skill="${escapedName}" ${s.disabled ? '' : 'checked'} />
        <span class="track"><span class="thumb"></span></span>
      </label>
    `
    skillList.appendChild(row)
  }

  skillList.querySelectorAll('input[data-skill]').forEach(input => {
    input.addEventListener('change', (e) => toggleSkill(e.target.dataset.skill))
  })
}

async function toggleSkill(name) {
  const cur = new Set(_skillsDisabled)
  if (cur.has(name)) cur.delete(name)
  else cur.add(name)
  const next = Array.from(cur)

  try {
    const res = await fetch(`${skillServer()}/api/settings`, {
      method: 'PATCH',
      headers: skillHeaders(),
      body: JSON.stringify({ skills_disabled: next }),
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    _skillsDisabled = next
    // Re-fetch so a re-enabled skill picks up its tool count.
    loadSkills()
  } catch (e) {
    skillError.hidden = false
    skillError.textContent = `Toggle failed: ${e.message}`
    // Revert checkbox state
    loadSkills()
  }
}

// ── Spotify integration ──────────────────────────────────────────────────────
//
// Parity with the Vue SettingsModal Integrations tab:
//   - Status with display name + tier
//   - Connect / Disconnect / Reconnect
//   - Headless URL fallback (paste-and-open) when popup-tab isn't available
//   - Share-across-profiles toggle
//
// Lives in this options page (not popup.js) because the OAuth dance
// opens a real browser tab — the popup window closes the moment focus
// leaves it, so popup-driven OAuth is unreliable. Options page is a
// proper full tab and stays open through the redirect.

const spotifyStatusLabel  = document.getElementById('spotifyStatusLabel')
const spotifyDot          = document.getElementById('spotifyDot')
const spotifyScope        = document.getElementById('spotifyScope')
const spotifyConnectBtn   = document.getElementById('spotifyConnect')
const spotifyDisconnectBtn= document.getElementById('spotifyDisconnect')
const spotifyReconnectBtn = document.getElementById('spotifyReconnect')
const spotifyFallback     = document.getElementById('spotifyFallback')
const spotifyAuthUrl      = document.getElementById('spotifyAuthUrl')
const spotifyCopyUrlBtn   = document.getElementById('spotifyCopyUrl')
const spotifyError        = document.getElementById('spotifyError')
const spotifyShareToggle  = document.getElementById('spotifyShare')


function spotifyHeaders() {
  const h = { 'Content-Type': 'application/json' }
  const k = apiKeyInput.value || ''
  if (k) h['Authorization'] = `Bearer ${k}`
  return h
}


function spotifyServer() {
  return (serverUrlInput.value || 'http://127.0.0.1:8000').replace(/\/$/, '')
}


async function loadSpotifyStatus() {
  spotifyError.hidden = true
  try {
    const res = await fetch(`${spotifyServer()}/api/spotify/status`, {
      headers: spotifyHeaders(),
      signal: AbortSignal.timeout(4000),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const s = await res.json()
    renderSpotifyStatus(s)
  } catch (e) {
    spotifyDot.className = 'dot off'
    spotifyStatusLabel.textContent = 'Server unreachable'
    spotifyConnectBtn.hidden     = false
    spotifyDisconnectBtn.hidden  = true
    spotifyReconnectBtn.hidden   = true
  }
}


function renderSpotifyStatus(s) {
  spotifyShareToggle.checked = !!s.shared

  if (!s.client_id_set) {
    spotifyDot.className = 'dot err'
    spotifyStatusLabel.textContent = 'Not configured'
    spotifyScope.hidden = false
    spotifyScope.textContent =
      'Set CHIKA_SPOTIFY_CLIENT_ID on the server (the easiest way), ' +
      'or follow the connection instructions printed by ' +
      '`chika spotify connect`.'
    spotifyConnectBtn.disabled    = true
    spotifyDisconnectBtn.hidden   = true
    spotifyReconnectBtn.hidden    = true
    return
  }
  spotifyConnectBtn.disabled = false

  if (s.authorized) {
    spotifyDot.className = 'dot ok'
    const name = s.display_name || 'unknown'
    const tier = s.product || ''
    spotifyStatusLabel.textContent = `Connected as ${name}${tier ? ' · ' + tier : ''}`
    spotifyScope.hidden = false
    spotifyScope.textContent = s.shared
      ? 'Connection is shared across all profiles.'
      : `Connection is for the "${s.profile}" profile only.`
    spotifyConnectBtn.hidden    = true
    spotifyDisconnectBtn.hidden = false
    spotifyReconnectBtn.hidden  = false
  } else {
    spotifyDot.className = 'dot off'
    spotifyStatusLabel.textContent = 'Not connected'
    spotifyScope.hidden = false
    spotifyScope.textContent = s.shared
      ? 'Sharing is on — connecting will apply to every profile.'
      : `Connecting will save to the "${s.profile || 'default'}" profile.`
    spotifyConnectBtn.hidden    = false
    spotifyDisconnectBtn.hidden = true
    spotifyReconnectBtn.hidden  = true
  }
}


async function spotifyDoConnect() {
  spotifyError.hidden = true
  spotifyConnectBtn.disabled    = true
  spotifyReconnectBtn.disabled  = true
  spotifyConnectBtn.textContent = 'Opening Spotify…'
  try {
    const res = await fetch(`${spotifyServer()}/api/spotify/connect`, {
      method: 'POST',
      headers: spotifyHeaders(),
      body: JSON.stringify({ open_browser: true }),
    })
    const data = await res.json()
    if (data.error) {
      spotifyError.hidden = false
      spotifyError.textContent = data.message || data.error
      return
    }
    if (data.auth_url) {
      // Open in a NEW tab from the options page. webbrowser.open on
      // the server may have already done this, but doing it here too
      // is the user's fastest path — clicking the button → tab opens.
      try {
        chrome.tabs.create({ url: data.auth_url })
      } catch {
        window.open(data.auth_url, '_blank')
      }
      if (!data.opened) {
        spotifyFallback.hidden = false
        spotifyAuthUrl.value   = data.auth_url
      }
    }
  } catch (e) {
    spotifyError.hidden = false
    spotifyError.textContent = String(e?.message || e)
  } finally {
    spotifyConnectBtn.disabled    = false
    spotifyReconnectBtn.disabled  = false
    spotifyConnectBtn.textContent = 'Connect Spotify'
    // Status will refresh when the OAuth callback completes; also
    // poll once after a few seconds in case the WS event was missed.
    setTimeout(loadSpotifyStatus, 4000)
  }
}


async function spotifyDoDisconnect() {
  spotifyDisconnectBtn.disabled = true
  try {
    await fetch(`${spotifyServer()}/api/spotify/disconnect`, {
      method: 'POST',
      headers: spotifyHeaders(),
    })
    await loadSpotifyStatus()
  } finally {
    spotifyDisconnectBtn.disabled = false
  }
}


async function spotifySetShare(checked) {
  spotifyShareToggle.disabled = true
  try {
    await fetch(`${spotifyServer()}/api/settings`, {
      method: 'PATCH',
      headers: spotifyHeaders(),
      body: JSON.stringify({
        spotify_share_across_profiles: checked ? 'on' : 'off',
      }),
    })
    await loadSpotifyStatus()
  } finally {
    spotifyShareToggle.disabled = false
  }
}


async function spotifyCopyUrl() {
  try {
    await navigator.clipboard.writeText(spotifyAuthUrl.value || '')
    const old = spotifyCopyUrlBtn.textContent
    spotifyCopyUrlBtn.textContent = 'Copied'
    setTimeout(() => { spotifyCopyUrlBtn.textContent = old }, 1800)
  } catch { /* clipboard unavailable in some contexts */ }
}


spotifyConnectBtn.addEventListener('click',    spotifyDoConnect)
spotifyReconnectBtn.addEventListener('click',  spotifyDoConnect)
spotifyDisconnectBtn.addEventListener('click', spotifyDoDisconnect)
spotifyCopyUrlBtn.addEventListener('click',    spotifyCopyUrl)
spotifyShareToggle.addEventListener('change', e => spotifySetShare(e.target.checked))

// Live status: poll every 5s while the options tab is open. The
// websocket isn't available from the options page (extension MV3
// service workers can't easily proxy a frontend WS), so polling is
// the simplest correct path.
let _spotifyPollTimer = null
function startSpotifyPolling() {
  loadSpotifyStatus()
  if (_spotifyPollTimer) clearInterval(_spotifyPollTimer)
  _spotifyPollTimer = setInterval(loadSpotifyStatus, 5000)
}
window.addEventListener('beforeunload', () => {
  if (_spotifyPollTimer) clearInterval(_spotifyPollTimer)
})

loadSettings().then(() => {
  startSpotifyPolling()
  loadSkills()
})

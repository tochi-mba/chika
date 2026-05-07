/**
 * Spotify integration — extension-popup section logic.
 *
 * Loaded dynamically by ``extension/options/options.js`` via the
 * SKILL_UI manifest endpoint
 * ``/api/skills/spotify/asset/ui/section.js``. Drop the
 * ``spotify_skill`` folder and this code disappears.
 *
 * Lives here (not in popup.js) because the OAuth dance opens a real
 * browser tab — the popup window closes the moment focus leaves it,
 * so popup-driven OAuth is unreliable. Options page is a proper full
 * tab and stays open through the redirect.
 *
 * Contract: the section's HTML root element is passed in. Inside it,
 * we look up children by ``data-role="..."`` so multiple sections
 * (one per skill) can coexist without ID collisions.
 */
export function init({ root, server, headers }) {
  const $ = (role) => root.querySelector(`[data-role="${role}"]`)
  const statusLabel = $('status-label')
  const dot         = $('dot')
  const scope       = $('scope')
  const connectBtn  = $('connect')
  const disconnectBtn = $('disconnect')
  const reconnectBtn  = $('reconnect')
  const fallback    = $('fallback')
  const authUrl     = $('auth-url')
  const copyUrlBtn  = $('copy-url')
  const errorEl     = $('error')
  const shareToggle = $('share')

  async function loadStatus() {
    errorEl.hidden = true
    try {
      const res = await fetch(`${server()}/api/spotify/status`, {
        headers: headers(),
        signal: AbortSignal.timeout(4000),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      renderStatus(await res.json())
    } catch {
      dot.className = 'dot off'
      statusLabel.textContent = 'Server unreachable'
      connectBtn.hidden    = false
      disconnectBtn.hidden = true
      reconnectBtn.hidden  = true
    }
  }

  function renderStatus(s) {
    shareToggle.checked = !!s.shared
    if (!s.client_id_set) {
      dot.className = 'dot err'
      statusLabel.textContent = 'Not configured'
      scope.hidden = false
      scope.textContent =
        'Set CHIKA_SPOTIFY_CLIENT_ID on the server (the easiest way), ' +
        'or follow the connection instructions printed by ' +
        '`chika spotify connect`.'
      connectBtn.disabled  = true
      disconnectBtn.hidden = true
      reconnectBtn.hidden  = true
      return
    }
    connectBtn.disabled = false
    if (s.authorized) {
      dot.className = 'dot ok'
      const name = s.display_name || 'unknown'
      const tier = s.product || ''
      statusLabel.textContent = `Connected as ${name}${tier ? ' · ' + tier : ''}`
      scope.hidden = false
      scope.textContent = s.shared
        ? 'Connection is shared across all profiles.'
        : `Connection is for the "${s.profile}" profile only.`
      connectBtn.hidden    = true
      disconnectBtn.hidden = false
      reconnectBtn.hidden  = false
    } else {
      dot.className = 'dot off'
      statusLabel.textContent = 'Not connected'
      scope.hidden = false
      scope.textContent = s.shared
        ? 'Sharing is on — connecting will apply to every profile.'
        : `Connecting will save to the "${s.profile || 'default'}" profile.`
      connectBtn.hidden    = false
      disconnectBtn.hidden = true
      reconnectBtn.hidden  = true
    }
  }

  async function doConnect() {
    errorEl.hidden = true
    connectBtn.disabled   = true
    reconnectBtn.disabled = true
    connectBtn.textContent = 'Opening Spotify…'
    try {
      const res = await fetch(`${server()}/api/spotify/connect`, {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ open_browser: true }),
      })
      const data = await res.json()
      if (data.error) {
        errorEl.hidden = false
        errorEl.textContent = data.message || data.error
        return
      }
      if (data.auth_url) {
        try {
          chrome.tabs.create({ url: data.auth_url })
        } catch {
          window.open(data.auth_url, '_blank')
        }
        if (!data.opened) {
          fallback.hidden = false
          authUrl.value   = data.auth_url
        }
      }
    } catch (e) {
      errorEl.hidden = false
      errorEl.textContent = String(e?.message || e)
    } finally {
      connectBtn.disabled    = false
      reconnectBtn.disabled  = false
      connectBtn.textContent = 'Connect Spotify'
      setTimeout(loadStatus, 4000)
    }
  }

  async function doDisconnect() {
    disconnectBtn.disabled = true
    try {
      await fetch(`${server()}/api/spotify/disconnect`, {
        method: 'POST',
        headers: headers(),
      })
      await loadStatus()
    } finally {
      disconnectBtn.disabled = false
    }
  }

  async function setShare(checked) {
    shareToggle.disabled = true
    try {
      await fetch(`${server()}/api/settings`, {
        method: 'PATCH',
        headers: headers(),
        body: JSON.stringify({
          spotify_share_across_profiles: checked ? 'on' : 'off',
        }),
      })
      await loadStatus()
    } finally {
      shareToggle.disabled = false
    }
  }

  async function copyUrl() {
    try {
      await navigator.clipboard.writeText(authUrl.value || '')
      const old = copyUrlBtn.textContent
      copyUrlBtn.textContent = 'Copied'
      setTimeout(() => { copyUrlBtn.textContent = old }, 1800)
    } catch { /* clipboard unavailable in some contexts */ }
  }

  connectBtn.addEventListener('click',    doConnect)
  reconnectBtn.addEventListener('click',  doConnect)
  disconnectBtn.addEventListener('click', doDisconnect)
  copyUrlBtn.addEventListener('click',    copyUrl)
  shareToggle.addEventListener('change', e => setShare(e.target.checked))

  // Live status: poll every 5s while the options tab is open. The
  // websocket isn't available from the options page, so polling is
  // the simplest correct path.
  loadStatus()
  const pollTimer = setInterval(loadStatus, 5000)

  // Returned cleanup hook — the host calls it when the section is
  // unmounted or the page closes.
  return () => clearInterval(pollTimer)
}

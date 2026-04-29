/**
 * storage.js — chrome.storage.session helpers
 *
 * Uses session storage so state survives service worker restarts within
 * a browser session, but is cleared on browser restart (intentional —
 * we don't want stale watches persisting across browser restarts).
 */

const WATCHES_KEY = 'chika_watches'
const SETTINGS_KEY = 'chika_settings'

// ── Settings ──────────────────────────────────────────────────────────────────

export async function getSettings() {
  const result = await chrome.storage.local.get(SETTINGS_KEY)
  return result[SETTINGS_KEY] || {
    // Use 127.0.0.1 not localhost — on Windows, localhost resolves to ::1
    // (IPv6) first. Browser tabs silently fall back to IPv4; service workers
    // don't, causing ERR_CONNECTION_REFUSED even when the server is running.
    serverUrl: 'http://127.0.0.1:8000',
    apiKey: '',
  }
}

export async function saveSettings(settings) {
  await chrome.storage.local.set({ [SETTINGS_KEY]: settings })
}

// ── Active watches (session-scoped) ──────────────────────────────────────────

/**
 * Watch record shape:
 * {
 *   watch_id: string,
 *   tab_id: number | null,
 *   selector: string,
 *   debounce_ms: number,
 *   created_at: number,  // Date.now()
 * }
 */

export async function getWatches() {
  try {
    const result = await chrome.storage.session.get(WATCHES_KEY)
    return result[WATCHES_KEY] || {}
  } catch {
    // session storage may not be available in all contexts
    return {}
  }
}

export async function saveWatch(record) {
  try {
    const current = await getWatches()
    current[record.watch_id] = record
    await chrome.storage.session.set({ [WATCHES_KEY]: current })
  } catch {
    // best-effort
  }
}

export async function removeWatch(watchId) {
  try {
    const current = await getWatches()
    delete current[watchId]
    await chrome.storage.session.set({ [WATCHES_KEY]: current })
  } catch {
    // best-effort
  }
}

export async function clearWatches() {
  try {
    await chrome.storage.session.set({ [WATCHES_KEY]: {} })
  } catch {
    // best-effort
  }
}

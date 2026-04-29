/**
 * bridge.js — Content script injected into every page
 *
 * Handles:
 *   - Setting up MutationObserver watches per request from background.js
 *   - Relaying watch_trigger events back to the service worker
 *   - Cancelling watches on navigation
 */

// Map of watch_id → { observer: MutationObserver, element: Element, cleanup: fn }
const activeWatches = new Map()

// ── Listen for commands from background.js ────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === 'setup_watch') {
    const result = setupWatch(msg)
    sendResponse(result)
    return true
  }

  if (msg.type === 'cancel_watch') {
    cancelWatch(msg.watch_id)
    sendResponse({ status: 'cancelled', watch_id: msg.watch_id })
    return true
  }

  if (msg.type === 'list_active_watches') {
    sendResponse({ watch_ids: Array.from(activeWatches.keys()) })
    return true
  }
})

// ── Watch setup ───────────────────────────────────────────────────────────────

function setupWatch({ watch_id, selector, debounce_ms = 1000 }) {
  // Cancel any existing watch with this ID (idempotent re-register)
  if (activeWatches.has(watch_id)) {
    cancelWatch(watch_id)
  }

  const el = document.querySelector(selector)
  if (!el) {
    return { error: 'selector_not_found', selector }
  }

  let debounceTimer = null
  const prevState = { text: el.innerText || el.textContent || '' }

  const observer = new MutationObserver(() => {
    clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      const currentText = el.innerText || el.textContent || ''
      if (currentText !== prevState.text) {
        const previous = prevState.text
        prevState.text = currentText

        try {
          chrome.runtime.sendMessage({
            type:     'watch_trigger',
            watch_id,
            data: {
              previous,
              current:  currentText,
              selector,
              url:      location.href,
              title:    document.title,
            },
          })
        } catch {
          // Service worker may have been killed — watch trigger lost (acceptable)
        }
      }
    }, debounce_ms)
  })

  observer.observe(el, {
    childList:     true,
    subtree:       true,
    characterData: true,
    attributes:    true,
  })

  // If the element is removed from DOM, fire a null trigger
  const removalObserver = new MutationObserver(() => {
    if (!document.contains(el)) {
      removalObserver.disconnect()
      try {
        chrome.runtime.sendMessage({
          type:     'watch_trigger',
          watch_id,
          data: {
            previous: prevState.text,
            current:  null,
            selector,
            url:      location.href,
            reason:   'element_removed',
          },
        })
      } catch {}
      activeWatches.delete(watch_id)
    }
  })
  removalObserver.observe(document.body, { childList: true, subtree: true })

  function cleanup() {
    clearTimeout(debounceTimer)
    observer.disconnect()
    removalObserver.disconnect()
  }

  activeWatches.set(watch_id, { observer, element: el, selector, cleanup })

  return { watch_id, status: 'watching', selector }
}

// ── Watch cancellation ────────────────────────────────────────────────────────

function cancelWatch(watch_id) {
  const record = activeWatches.get(watch_id)
  if (!record) return
  record.cleanup()
  activeWatches.delete(watch_id)
}

// ── Cancel all watches on navigation ─────────────────────────────────────────

window.addEventListener('beforeunload', () => {
  for (const [watch_id] of activeWatches) {
    try {
      chrome.runtime.sendMessage({
        type:     'watch_cancelled',
        watch_id,
        reason:   'navigation',
      })
    } catch {}
  }
  activeWatches.clear()
})

// ── Reconnect watches after soft navigation (SPA) ────────────────────────────
// For SPA apps that swap content without a full page reload, we listen for
// URL changes and re-register watches whose selectors are still in the DOM.

let _lastUrl = location.href
const _urlObserver = new MutationObserver(() => {
  if (location.href !== _lastUrl) {
    _lastUrl = location.href
    // Re-validate all active watches against the new DOM
    for (const [watch_id, record] of activeWatches) {
      const el = document.querySelector(record.selector)
      if (!el) {
        // Element gone after SPA navigation — cancel
        record.cleanup()
        activeWatches.delete(watch_id)
        try {
          chrome.runtime.sendMessage({
            type:     'watch_cancelled',
            watch_id,
            reason:   'spa_navigation',
          })
        } catch {}
      }
    }
  }
})
_urlObserver.observe(document.body, { childList: true, subtree: true })

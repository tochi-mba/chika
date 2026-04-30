/**
 * actions.js — Allowlisted browser action handlers
 *
 * Each function receives `args` from the server and returns a result dict.
 * The extension NEVER evaluates raw JavaScript strings from the server.
 * All handlers are self-contained (no shared mutable closures).
 */

import { isWriteBlocked, isRestrictedUrl, MAX_TEXT_BYTES, MAX_DOM_BYTES } from './security.js'
import { saveWatch, removeWatch, getWatches } from './storage.js'

// ── Utility ───────────────────────────────────────────────────────────────────

async function getActiveTabId() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true })
  return tab?.id ?? null
}

async function waitForTabLoad(tabId, timeoutMs = 15000) {
  const tab = await chrome.tabs.get(tabId).catch(() => null)
  if (!tab) return
  if (tab.status === 'complete') return

  return new Promise((resolve) => {
    const timer = setTimeout(resolve, timeoutMs)
    const listener = (id, changeInfo) => {
      if (id === tabId && changeInfo.status === 'complete') {
        clearTimeout(timer)
        chrome.tabs.onUpdated.removeListener(listener)
        resolve()
      }
    }
    chrome.tabs.onUpdated.addListener(listener)
  })
}

// Poll until a CSS selector exists in the tab (for SPAs that render async).
// Returns true if found, false if timed out.
async function waitForSelector(tabId, selector, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId },
        func: (sel) => !!document.querySelector(sel),
        args: [selector],
      })
      if (result) return true
    } catch { /* tab may still be loading */ }
    await sleep(400)
  }
  return false
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms))
}

// ── Read actions ──────────────────────────────────────────────────────────────

export async function getTabList() {
  const tabs = await chrome.tabs.query({})
  const active = tabs.find(t => t.active)
  return {
    tabs: tabs.slice(0, 200).map(t => ({
      id:        t.id,
      url:       t.url,
      title:     t.title,
      active:    t.active,
      status:    t.status,
      pinned:    t.pinned,
      windowId:  t.windowId,
      incognito: t.incognito,
    })),
    count:         tabs.length,
    truncated:     tabs.length > 200,
    active_tab_id: active?.id ?? null,
  }
}

export async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true })
  if (!tab) return { error: 'no_active_tab' }
  return {
    id:        tab.id,
    url:       tab.url,
    title:     tab.title,
    status:    tab.status,
    pinned:    tab.pinned,
    windowId:  tab.windowId,
    incognito: tab.incognito,
  }
}

export async function getTabText({ tab_id = null, selector = null, find = null, context_lines = 4, wait_for = null }) {
  const tabId = tab_id ?? (await getActiveTabId())
  if (tabId == null) return { error: 'no_active_tab' }

  const tab = await chrome.tabs.get(tabId).catch(() => null)
  if (!tab) return { error: 'tab_not_found', tab_id: tabId }
  if (isRestrictedUrl(tab.url)) return { error: 'restricted_page', url: tab.url }

  if (tab.status === 'loading') {
    await waitForTabLoad(tabId, 10_000)
  }

  // Wait for a specific element to appear before extracting — needed for SPAs
  // (e.g. YouTube Polymer components that render after status=complete)
  if (wait_for) {
    const appeared = await waitForSelector(tabId, wait_for, 10_000)
    if (!appeared) return {
      error:    'wait_for_timeout',
      selector: wait_for,
      message:  `Element '${wait_for}' did not appear within 10s. The page may still be loading or requires login.`,
      url:      tab.url,
    }
  }

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: (sel, findKeyword, ctxLines) => {
        try {
          const root = sel ? document.querySelector(sel) : document.body
          if (!root) return { error: 'selector_not_found', selector: sel }
          const raw = (root.innerText || root.textContent || '').trim()
          const MAX = 500_000
          let text = raw.length > MAX ? raw.slice(0, MAX) : raw

          // ── Keyword filter ───────────────────────────────────────────────
          // When `find` is set, split into lines, keep only lines (+ context)
          // that contain the keyword. Returns much smaller, focused output.
          if (findKeyword) {
            const kw    = findKeyword.toLowerCase()
            const lines = text.split('\n')
            const CTX   = Math.max(0, Math.min(ctxLines ?? 4, 50))
            const keep  = new Set()

            lines.forEach((line, i) => {
              if (line.toLowerCase().includes(kw)) {
                for (let j = Math.max(0, i - CTX); j <= Math.min(lines.length - 1, i + CTX); j++) {
                  keep.add(j)
                }
              }
            })

            if (keep.size === 0) {
              return {
                text: '',
                char_count: 0,
                filtered: true,
                keyword: findKeyword,
                no_match: true,
                url: location.href,
                title: document.title,
              }
            }

            // Group matched lines; insert '...' between non-consecutive blocks
            const sorted  = [...keep].sort((a, b) => a - b)
            const chunks  = []
            let   last    = -2
            for (const idx of sorted) {
              if (idx > last + 1) chunks.push('...')
              chunks.push(lines[idx])
              last = idx
            }
            text = chunks.join('\n').trim()
          }
          // ────────────────────────────────────────────────────────────────

          return {
            text,
            char_count:  text.length,
            original_chars: raw.length,
            truncated:   raw.length > MAX,
            filtered:    !!findKeyword,
            keyword:     findKeyword || null,
            url:         location.href,
            title:       document.title,
          }
        } catch (e) {
          return { error: 'extraction_failed', message: e.message }
        }
      },
      args: [selector, find, Math.max(0, Math.min(context_lines ?? 4, 50))],
    })
    return result
  } catch (e) {
    return { error: 'script_injection_failed', message: e.message }
  }
}

// Read a JavaScript variable from the page's real window context.
// Uses world:'MAIN' so it can access page globals like ytInitialData.
// var_path is a dot/bracket property path, e.g. "ytInitialData" or
// "ytInitialData.header.c4TabbedHeaderRenderer.title".
// Returns up to max_bytes of the serialised value; larger values are
// truncated with a hint to use a more specific path.
export async function getPageVar({ tab_id = null, var_path, max_bytes = 60000 }) {
  if (!var_path) return { error: 'missing_var_path' }
  // Safety: only allow safe property-path characters, no function calls or operators
  if (!/^[a-zA-Z_$][a-zA-Z0-9_$.\[\]'"]*$/.test(var_path)) {
    return { error: 'invalid_var_path', message: 'var_path must be a dot-notation property path (e.g. "ytInitialData.header")' }
  }

  const tabId = tab_id ?? (await getActiveTabId())
  if (tabId == null) return { error: 'no_active_tab' }

  const tab = await chrome.tabs.get(tabId).catch(() => null)
  if (!tab) return { error: 'tab_not_found', tab_id: tabId }
  if (isRestrictedUrl(tab.url)) return { error: 'restricted_page', url: tab.url }

  const capBytes = Math.min(Math.max(max_bytes || 60000, 1000), 300_000)

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      world:  'MAIN',   // access the page's real JS context
      func: (varPath, maxBytes) => {
        try {
          // Navigate the property path safely without eval
          const parts = varPath.replace(/\[(['"]?)(\w+)\1\]/g, '.$2').split('.').filter(Boolean)
          let val = window
          for (const part of parts) {
            if (val == null || typeof val !== 'object' && typeof val !== 'function') {
              return { error: 'path_not_found', path: varPath, stopped_at: part }
            }
            val = val[part]
          }
          if (val === undefined) return { error: 'path_not_found', path: varPath }

          let json
          try { json = JSON.stringify(val) } catch { return { error: 'not_serializable', path: varPath } }

          if (json.length > maxBytes) {
            // Show top-level keys for objects so caller can narrow the path
            let keys_preview = null
            if (val && typeof val === 'object' && !Array.isArray(val)) {
              keys_preview = Object.keys(val).slice(0, 50)
            } else if (Array.isArray(val)) {
              keys_preview = `Array[${val.length}]`
            }
            return {
              error:         'too_large',
              message:       `Value at '${varPath}' is ${json.length} bytes (limit ${maxBytes}). Use a more specific path.`,
              size_bytes:    json.length,
              limit_bytes:   maxBytes,
              keys_preview,
              path:          varPath,
              url:           location.href,
            }
          }

          return { value: val, size_bytes: json.length, path: varPath, url: location.href }
        } catch (e) {
          return { error: 'extraction_failed', message: e.message }
        }
      },
      args: [var_path, capBytes],
    })
    return result
  } catch (e) {
    return { error: 'script_injection_failed', message: e.message }
  }
}

export async function getTabDom({ tab_id = null, selector = null }) {
  const tabId = tab_id ?? (await getActiveTabId())
  if (tabId == null) return { error: 'no_active_tab' }

  const tab = await chrome.tabs.get(tabId).catch(() => null)
  if (!tab) return { error: 'tab_not_found', tab_id: tabId }
  if (isRestrictedUrl(tab.url)) return { error: 'restricted_page', url: tab.url }

  if (tab.status === 'loading') {
    await waitForTabLoad(tabId, 10_000)
  }

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: (sel) => {
        try {
          const root = sel ? document.querySelector(sel) : document.documentElement
          if (!root) return { error: 'selector_not_found', selector: sel }
          const html = root.outerHTML || root.innerHTML || ''
          const MAX = 2_000_000
          return {
            html:      html.length > MAX ? html.slice(0, MAX) : html,
            truncated: html.length > MAX,
            byte_count: html.length,
            url:   location.href,
            title: document.title,
          }
        } catch (e) {
          return { error: 'extraction_failed', message: e.message }
        }
      },
      args: [selector],
    })
    return result
  } catch (e) {
    return { error: 'script_injection_failed', message: e.message }
  }
}

export async function getElement({ tab_id = null, selector, attribute = 'text' }) {
  const tabId = tab_id ?? (await getActiveTabId())
  if (tabId == null) return { error: 'no_active_tab' }
  if (!selector)     return { error: 'selector_required' }

  const tab = await chrome.tabs.get(tabId).catch(() => null)
  if (!tab) return { error: 'tab_not_found' }
  if (isRestrictedUrl(tab.url)) return { error: 'restricted_page', url: tab.url }

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: (sel, attr) => {
        const el = document.querySelector(sel)
        if (!el) return { error: 'selector_not_found', selector: sel }
        let value
        if (attr === 'text')       value = el.innerText || el.textContent || ''
        else if (attr === 'html')  value = el.innerHTML
        else if (attr === 'value') value = el.value ?? el.getAttribute('value') ?? null
        else                       value = el.getAttribute(attr) ?? el[attr] ?? null
        return { value, tag: el.tagName.toLowerCase(), selector: sel }
      },
      args: [selector, attribute],
    })
    return result
  } catch (e) {
    return { error: 'script_injection_failed', message: e.message }
  }
}

export async function takeScreenshot({ tab_id = null }) {
  const tabId = tab_id ?? (await getActiveTabId())
  if (tabId == null) return { error: 'no_active_tab' }

  const tab = await chrome.tabs.get(tabId).catch(() => null)
  if (!tab) return { error: 'tab_not_found', tab_id: tabId }
  if (isRestrictedUrl(tab.url)) return { error: 'restricted_page', url: tab.url }

  // captureVisibleTab requires the tab's window to be focused
  const wasActive = tab.active
  if (!wasActive) {
    await chrome.tabs.update(tabId, { active: true })
    await sleep(200)  // allow render
  }

  let dataUrl
  try {
    dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
      format: 'png',
    })
  } catch (e) {
    return { error: 'capture_failed', message: e.message }
  }

  const base64 = dataUrl.replace(/^data:image\/png;base64,/, '')
  const sizeBytes = Math.round(base64.length * 0.75)

  let compressionFailed = false

  // If > 4MB compress to jpeg
  if (sizeBytes > 4 * 1024 * 1024) {
    try {
      const blob = await fetch(dataUrl).then(r => r.blob())
      const bitmap = await createImageBitmap(blob)
      const canvas = new OffscreenCanvas(
        Math.min(bitmap.width, 1280),
        Math.round(bitmap.height * (Math.min(bitmap.width, 1280) / bitmap.width))
      )
      const ctx = canvas.getContext('2d')
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
      const jpegBlob = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.75 })
      const jpegBuf = await jpegBlob.arrayBuffer()
      const jpegB64 = btoa(String.fromCharCode(...new Uint8Array(jpegBuf)))
      return {
        image:      jpegB64,
        format:     'jpeg',
        size_bytes: jpegBuf.byteLength,
        width:      canvas.width,
        height:     canvas.height,
        url:        tab.url,
        title:      tab.title,
        warning:    !wasActive ? 'tab_was_briefly_focused' : null,
      }
    } catch (e) {
      console.error('Screenshot JPEG compression failed:', e)
      compressionFailed = true
    }
  }

  return {
    image:      base64,
    format:     'png',
    size_bytes: sizeBytes,
    url:        tab.url,
    title:      tab.title,
    warning:    compressionFailed
      ? 'compression_failed_oversized'
      : (!wasActive ? 'tab_was_briefly_focused' : null),
  }
}

// ── Write actions ─────────────────────────────────────────────────────────────

export async function navigate({ url, tab_id = null, new_tab = false }) {
  if (!/^https?:\/\//.test(url) && url !== 'about:blank') {
    return { error: 'invalid_url_scheme', url }
  }
  if (isWriteBlocked(url)) {
    return { error: 'blocked_domain', url, message: 'Write actions are blocked on this domain.' }
  }

  if (new_tab) {
    const tab = await chrome.tabs.create({ url, active: true })
    await waitForTabLoad(tab.id, 30_000)
    const fresh = await chrome.tabs.get(tab.id).catch(() => null)
    return { tab_id: tab.id, url: fresh?.url ?? url, title: fresh?.title ?? '', status: 'navigated' }
  }

  const tabId = tab_id ?? (await getActiveTabId())
  if (tabId == null) return { error: 'no_active_tab' }

  const tab = await chrome.tabs.get(tabId).catch(() => null)
  if (!tab) return { error: 'tab_not_found', tab_id: tabId }

  try {
    await chrome.tabs.update(tabId, { url })
    await waitForTabLoad(tabId, 30_000)
    const fresh = await chrome.tabs.get(tabId).catch(() => null)
    return { tab_id: tabId, url: fresh?.url ?? url, title: fresh?.title ?? '', status: 'navigated' }
  } catch (e) {
    if (e.message?.includes('navigation')) {
      return { error: 'navigation_blocked', message: e.message }
    }
    return { error: 'navigate_failed', message: e.message }
  }
}

export async function openTab({ url = 'about:blank' }) {
  const tab = await chrome.tabs.create({ url, active: true })
  if (url !== 'about:blank') {
    await waitForTabLoad(tab.id, 30_000)
  }
  return { tab_id: tab.id, url: tab.url, status: 'opened' }
}

export async function closeTab({ tab_id }) {
  const tab = await chrome.tabs.get(tab_id).catch(() => null)
  if (!tab) return { error: 'tab_not_found', tab_id }

  const allTabs = await chrome.tabs.query({ windowId: tab.windowId })
  const isLast = allTabs.length === 1

  await chrome.tabs.remove(tab_id).catch(() => {})
  return { tab_id, status: 'closed', warning: isLast ? 'last_tab_in_window' : null }
}

export async function switchTab({ tab_id }) {
  const tab = await chrome.tabs.get(tab_id).catch(() => null)
  if (!tab) return { error: 'tab_not_found', tab_id }

  // Also focus the window if it's not the active one
  await chrome.windows.update(tab.windowId, { focused: true }).catch(() => {})
  await chrome.tabs.update(tab_id, { active: true })
  return { tab_id, status: 'focused', url: tab.url, title: tab.title }
}

export async function clickElement({ tab_id = null, selector }) {
  const tabId = tab_id ?? (await getActiveTabId())
  if (tabId == null) return { error: 'no_active_tab' }
  if (!selector)     return { error: 'selector_required' }

  const tab = await chrome.tabs.get(tabId).catch(() => null)
  if (!tab) return { error: 'tab_not_found' }
  if (isWriteBlocked(tab.url)) return { error: 'blocked_domain', url: tab.url }

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: (sel) => {
        const el = document.querySelector(sel)
        if (!el) return { error: 'selector_not_found', selector: sel }
        if (!el.offsetParent && el.style.display === 'none') {
          return { error: 'element_not_visible', selector: sel }
        }

        // Check for CAPTCHA patterns before clicking
        const captchaSelectors = ['.g-recaptcha', '#recaptcha', '.cf-challenge', '[data-sitekey]']
        for (const cs of captchaSelectors) {
          if (document.querySelector(cs)) {
            return { error: 'captcha_detected', message: 'A CAPTCHA is present. Manual interaction required.' }
          }
        }

        el.click()
        return { status: 'clicked', selector: sel, tag: el.tagName.toLowerCase() }
      },
      args: [selector],
    })
    return result
  } catch (e) {
    return { error: 'script_injection_failed', message: e.message }
  }
}

export async function fillInput({ tab_id = null, selector, value }) {
  const tabId = tab_id ?? (await getActiveTabId())
  if (tabId == null) return { error: 'no_active_tab' }
  if (!selector)     return { error: 'selector_required' }
  if (value == null) return { error: 'value_required' }

  const tab = await chrome.tabs.get(tabId).catch(() => null)
  if (!tab) return { error: 'tab_not_found' }
  if (isWriteBlocked(tab.url)) return { error: 'blocked_domain', url: tab.url }

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: (sel, val) => {
        const el = document.querySelector(sel)
        if (!el) return { error: 'selector_not_found', selector: sel }

        const tag = el.tagName.toLowerCase()
        const isPassword = el.type === 'password'

        // Set value via native setter so React/Vue state management picks it up
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
          tag === 'textarea' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype,
          'value'
        )?.set
        if (nativeInputValueSetter) {
          nativeInputValueSetter.call(el, val)
        } else {
          el.value = val
        }

        el.dispatchEvent(new Event('input',  { bubbles: true }))
        el.dispatchEvent(new Event('change', { bubbles: true }))

        return {
          status:      'filled',
          selector:    sel,
          tag,
          // Never echo password values
          value_echo:  isPassword ? '***' : (val.length > 40 ? val.slice(0, 40) + '…' : val),
        }
      },
      args: [selector, value],
    })
    return result
  } catch (e) {
    return { error: 'script_injection_failed', message: e.message }
  }
}

export async function scrollPage({ tab_id = null, direction = 'down', amount = 500 }) {
  const tabId = tab_id ?? (await getActiveTabId())
  if (tabId == null) return { error: 'no_active_tab' }

  const tab = await chrome.tabs.get(tabId).catch(() => null)
  if (!tab) return { error: 'tab_not_found' }
  if (isRestrictedUrl(tab.url)) return { error: 'restricted_page', url: tab.url }

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: (dir, amt) => {
        const el = document.scrollingElement || document.body
        const x0 = el.scrollLeft, y0 = el.scrollTop
        if      (dir === 'down')   el.scrollBy(0,  amt)
        else if (dir === 'up')     el.scrollBy(0, -amt)
        else if (dir === 'right')  el.scrollBy( amt, 0)
        else if (dir === 'left')   el.scrollBy(-amt, 0)
        else if (dir === 'top')    el.scrollTo(0, 0)
        else if (dir === 'bottom') el.scrollTo(0, el.scrollHeight)
        return {
          status:     'scrolled',
          direction:  dir,
          from:       { x: x0, y: y0 },
          to:         { x: el.scrollLeft, y: el.scrollTop },
          page_height: el.scrollHeight,
        }
      },
      args: [direction, amount],
    })
    return result
  } catch (e) {
    return { error: 'script_injection_failed', message: e.message }
  }
}

// ── Watch actions ─────────────────────────────────────────────────────────────

export async function watchElement({ tab_id = null, selector, watch_id, debounce_ms = 1000 }) {
  const tabId = tab_id ?? (await getActiveTabId())
  if (tabId == null) return { error: 'no_active_tab' }
  if (!selector)     return { error: 'selector_required' }

  const tab = await chrome.tabs.get(tabId).catch(() => null)
  if (!tab) return { error: 'tab_not_found' }
  if (isRestrictedUrl(tab.url)) return { error: 'restricted_page', url: tab.url }

  // Inject the watch into the content script via messaging
  const response = await chrome.tabs.sendMessage(tabId, {
    type:        'setup_watch',
    watch_id,
    selector,
    debounce_ms,
  }).catch(e => ({ error: 'content_script_unavailable', message: e.message }))

  if (response?.error) return response

  // Persist watch so it can be restored after SW restart
  await saveWatch({ watch_id, tab_id: tabId, selector, debounce_ms, created_at: Date.now() })

  return { watch_id, selector, tab_id: tabId, status: 'watching' }
}

export async function unwatchElement({ watch_id }) {
  await removeWatch(watch_id)

  // Find which tab has this watch and tell it to cancel
  const watches = await getWatches()
  const record = watches[watch_id]
  if (record?.tab_id) {
    await chrome.tabs.sendMessage(record.tab_id, { type: 'cancel_watch', watch_id })
      .catch(() => {})  // tab may already be closed
  }

  return { watch_id, status: 'cancelled' }
}

export async function listWatches({ watch_ids = [] }) {
  const stored = await getWatches()
  const result = watch_ids
    .map(id => stored[id] ? { ...stored[id], status: 'active' } : { watch_id: id, status: 'unknown' })
  return { watches: result, count: result.length }
}

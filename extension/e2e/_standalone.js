/**
 * Shared standalone Playwright harness for popup tests.
 *
 * Why standalone instead of `--load-extension`:
 *   The popup itself doesn't open a WebSocket — the service worker does,
 *   and forwards events to the popup via `chrome.runtime.onMessage`.
 *   The old `_fixtures.js` approach mocked `window.WebSocket` in the popup
 *   page, which the popup never instantiates, so pushed events never
 *   reached `popup.js`'s listeners. Tests using that pattern just timed
 *   out at every assertion.
 *
 *   This harness serves `popup.html` over a local HTTP server, mocks
 *   `chrome.*` (matching what the SW would otherwise provide), and exposes
 *   `window.__chikaPushChrome(msg)` so tests dispatch events the way the
 *   real SW does — `chrome.runtime.onMessage.addListener(fn)` is captured
 *   and invoked directly. It also captures every `chrome.runtime.sendMessage`
 *   the popup makes into `window.__chikaSentToBg` so tests can assert on
 *   outgoing payloads (e.g. "clicking Deny dispatched an approval response
 *   with approved=false").
 *
 * Use this for any test that exercises popup UI behaviour. Reserve the
 * `--load-extension` fixture (`_fixtures.js`) for tests that genuinely
 * need a real service worker (e.g. background.spec.js).
 */
import { test as base, expect, chromium } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'
import http from 'http'
import fs from 'fs'

const __filename = fileURLToPath(import.meta.url)
const EXT_ROOT   = path.resolve(path.dirname(__filename), '..')


function startStaticServer() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      let url = (req.url || '/').split('?')[0]
      if (url === '/' || url === '') url = '/popup/popup.html'
      const file = path.join(EXT_ROOT, url)
      if (!path.resolve(file).startsWith(EXT_ROOT)) {
        res.writeHead(403); res.end(); return
      }
      try {
        const data = fs.readFileSync(file)
        const ext = path.extname(file).toLowerCase()
        const ct = ext === '.html' ? 'text/html'
          : ext === '.css' ? 'text/css'
          : ext === '.js'  ? 'application/javascript'
          : ext === '.json' ? 'application/json'
          : 'application/octet-stream'
        res.writeHead(200, { 'Content-Type': ct })
        res.end(data)
      } catch {
        res.writeHead(404)
        res.end('not found')
      }
    })
    server.listen(0, '127.0.0.1', () => resolve(server))
  })
}


export const test = base.extend({
  context: async ({}, use) => {
    const server = await startStaticServer()
    const port = server.address().port
    const browser = await chromium.launch({ headless: true })
    const ctx = await browser.newContext({
      viewport: { width: 380, height: 600 },
      baseURL: `http://127.0.0.1:${port}`,
    })
    ctx.popupURL = `http://127.0.0.1:${port}/popup/popup.html`
    await use(ctx)
    await ctx.close()
    await browser.close()
    await new Promise((r) => server.close(r))
  },
  page: async ({ context }, use) => {
    const page = await context.newPage()
    await use(page)
  },
  popupURL: async ({ context }, use) => {
    await use(context.popupURL)
  },
})

export { expect }


// Stub chrome.* + WebSocket so popup.js doesn't blow up loading
// without the extension shell.
//
// Capture the chrome.runtime.onMessage listeners popup.js attaches and
// expose them as `window.__chikaPushChrome(msg)` — that's how tests
// dispatch SW→popup events. Capture every `chrome.runtime.sendMessage`
// the popup makes as `window.__chikaSentToBg` so tests can assert on
// outgoing payloads (clicking Deny, submitting an approval, etc.).
export const standaloneStub = `
;(() => {
  const _onMessageListeners = []
  window.__chikaPushChrome = (msg) => {
    for (const fn of _onMessageListeners) {
      try { fn(msg) } catch (e) { console.error(e) }
    }
  }
  window.__chikaSentToBg = []

  const chrome = {
    runtime: {
      lastError: null,
      sendMessage: (msg, cb) => {
        // Capture for test assertions.
        try { window.__chikaSentToBg.push(msg) } catch {}
        // Provide deterministic responses for the messages popup.js
        // sends during init so it lands in chat view.
        if (!cb) return
        if (msg?.type === 'request_status') {
          cb({ connected: true })
        } else if (msg?.type === 'request_chat_state') {
          cb({ state: {
            connected: true, messages: [], events: [],
            pendingApprovals: [], pendingQuestions: [],
          } })
        } else {
          cb(undefined)
        }
      },
      onMessage: {
        addListener:    (fn) => _onMessageListeners.push(fn),
        removeListener: (fn) => {
          const i = _onMessageListeners.indexOf(fn)
          if (i >= 0) _onMessageListeners.splice(i, 1)
        },
      },
      getURL:      (p) => p,
      id:          'standalone-stub',
    },
    storage: {
      local: {
        get: (keys, cb) => {
          const seeded = {
            chika_settings: {
              serverUrl: 'http://127.0.0.1:8000',
              apiKey:    'standalone-test-key',
            },
          }
          let out = {}
          if (typeof keys === 'string') {
            out[keys] = seeded[keys]
          } else if (Array.isArray(keys)) {
            keys.forEach((k) => out[k] = seeded[k])
          } else if (keys && typeof keys === 'object') {
            Object.keys(keys).forEach((k) => out[k] = seeded[k] ?? keys[k])
          } else {
            out = seeded
          }
          if (cb) { cb(out); return }
          return Promise.resolve(out)
        },
        set: (_data, cb) => {
          if (cb) { cb(); return }
          return Promise.resolve()
        },
      },
      sync: {
        get: (keys, cb) => cb && cb({}),
        set: (_data, cb) => cb && cb(),
      },
      session: {
        get: async (keys) => {
          const seeded = { chika_profile_unlocked: true }
          if (typeof keys === 'string') return { [keys]: seeded[keys] }
          if (Array.isArray(keys)) {
            const out = {}; keys.forEach((k) => out[k] = seeded[k]); return out
          }
          return seeded
        },
        set: async () => {},
      },
    },
    tabs: {
      query: (_q, cb) => cb && cb([{ id: 0, url: 'about:blank', title: '' }]),
    },
  }
  window.chrome = chrome

  // Some popup paths still construct a WebSocket to the configured server
  // (or import lib/ws_client.js indirectly). The popup itself doesn't, but
  // mocking it here keeps test failures honest — a real WebSocket attempt
  // against a non-existent server would throw async errors that the test
  // sees as console noise.
  const mock = {
    sentMessages: [],
    sockets: [],
  }
  class MockWS {
    constructor(url) {
      this.url = url; this.readyState = 0
      mock.sockets.push(this)
      setTimeout(() => {
        this.readyState = 1
        this.onopen && this.onopen({})
      }, 0)
    }
    send(data) { mock.sentMessages.push(data) }
    close() { this.readyState = 3; this.onclose && this.onclose({}) }
    addEventListener(name, fn) { this['on' + name] = fn }
    removeEventListener() {}
  }
  MockWS.OPEN = 1; MockWS.CLOSED = 3
  window.__chikaMockWS = mock
  window.WebSocket     = MockWS

  window.fetch = async () => new Response(JSON.stringify({ ok: true }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })
})()
`


/**
 * Wait for popup.js's init() to land in chat view. Mocked
 * chrome.runtime.sendMessage answers ``request_chat_state`` with a
 * ``connected: true`` state, which triggers ``showView('chat')`` —
 * but the chain is async so a deterministic poll is more reliable
 * than a fixed sleep.
 */
export async function waitForChatView(page, timeout = 4000) {
  await page.waitForFunction(() => {
    const el = document.getElementById('chatView')
    return el && el.style.display !== 'none' && getComputedStyle(el).display !== 'none'
  }, null, { timeout })
}

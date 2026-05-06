/**
 * Shared Playwright fixtures for the Chika extension e2e suite.
 *
 * Chrome MV3 extensions can only be loaded into a **persistent**
 * browser context (Playwright's `chromium.launchPersistentContext`).
 * Each test gets its own user-data directory under tmpdir so state
 * doesn't leak between runs.
 *
 * The fixture also resolves the extension's chrome-extension://<id>/
 * URL by inspecting the registered service worker, so tests can
 * navigate to popup.html via `popupURL`.
 */
import { test as base, expect, chromium } from '@playwright/test'
import path from 'path'
import os from 'os'
import fs from 'fs'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const EXT_PATH = path.resolve(path.dirname(__filename), '..')

/** Generate a fresh persistent user-data dir per test. */
function tmpUserDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'chika-ext-'))
}

// MV3 service workers do not reliably register under Playwright's headless
// Chromium on Ubuntu CI: `headless: true` causes Playwright to pass
// `--headless=old`, which boots Chrome without the SW host that MV3 needs,
// and the popupURL fixture's `waitForEvent('serviceworker')` then times out
// after 10s for every test. The fix is to run headed and provide a virtual
// display in CI via `xvfb-run -a`. Devs who don't want Chrome windows
// popping up locally can opt in to headless with CHIKA_E2E_HEADLESS=1.
const HEADLESS = process.env.CHIKA_E2E_HEADLESS === '1'

export const test = base.extend({
  context: async ({}, use) => {
    const userDataDir = tmpUserDir()
    const ctx = await chromium.launchPersistentContext(userDataDir, {
      headless: HEADLESS,
      args: [
        `--disable-extensions-except=${EXT_PATH}`,
        `--load-extension=${EXT_PATH}`,
        '--no-sandbox',
        '--disable-gpu',
      ],
    })
    await use(ctx)
    await ctx.close()
    try { fs.rmSync(userDataDir, { recursive: true, force: true }) } catch {}
  },

  /** Single shared page for tests that need any page object. */
  page: async ({ context }, use) => {
    let page = context.pages()[0]
    if (!page) page = await context.newPage()
    await use(page)
  },

  /**
   * The chrome-extension://<id>/popup/popup.html URL. Resolved by
   * waiting for the service-worker target to register and reading its
   * URL prefix. This is the canonical way to discover an MV3 extension's
   * id from Playwright.
   */
  popupURL: async ({ context }, use) => {
    let sw = context.serviceWorkers()[0]
    if (!sw) {
      sw = await context.waitForEvent('serviceworker', { timeout: 10_000 })
    }
    const extId = new URL(sw.url()).host
    await use(`chrome-extension://${extId}/popup/popup.html`)
  },
})

export { expect }


/**
 * Inject the same WS / fetch stub the frontend uses, so the extension
 * popup gets deterministic engine events when it tries to talk to the
 * backend.
 */
export const stubInit = `
  ;(() => {
    const mock = {
      sentMessages: [],
      sockets: [],
      pushEvent(payload) {
        const sock = mock.sockets[mock.sockets.length - 1]
        if (!sock) return
        const ev = { data: typeof payload === 'string' ? payload : JSON.stringify(payload) }
        sock.onmessage && sock.onmessage(ev)
      },
    }
    class MockWS {
      constructor(url) {
        this.url = url; this.readyState = 0
        mock.sockets.push(this)
        setTimeout(() => {
          this.readyState = 1
          this.onopen && this.onopen({})
          this.onmessage && this.onmessage({
            data: JSON.stringify({
              type: 'session_info',
              session_id: 'ext-test', device_id: 'ext-dev',
            }),
          })
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
    window.fetch = async () => new Response(JSON.stringify({}), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  })()
`

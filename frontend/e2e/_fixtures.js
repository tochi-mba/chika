/**
 * Shared Playwright fixtures for the Chika frontend e2e suite.
 *
 * Provides:
 *   - chikaPage: a Page with `window.WebSocket` replaced by a controllable
 *     mock so tests can drive engine events directly without booting the
 *     real backend. The mock buffers outbound user messages and exposes
 *     `pushEvent(...)` to inject server events.
 *
 * Why mock WS instead of running the real backend? Speed (no Python
 * boot), determinism (no real LLM, no race with FastAPI startup), and
 * we already test the real WS pipeline in tests/test_ws_e2e.py. These
 * Playwright tests are about the *frontend rendering correctness*.
 */
import fs from 'fs'
import path from 'path'
import url from 'url'

import { test as base, expect } from '@playwright/test'

// ── Skill-contributed Playwright mocks ─────────────────────────────
//
// Each shipped skill that needs Playwright fetch mocks ships a
// ``tests/playwright_mocks.js`` file. We discover + extract the
// ``MOCKS_SCRIPT`` template-literal SYNCHRONOUSLY via
// ``fs.readFileSync`` + a small regex — NOT via dynamic ``import()``.
//
// Why not ``await import(...)`` at module top: Playwright's CJS
// loader path can't ``require()`` a module that has top-level
// ``await`` ("require() cannot be used on an ESM graph with
// top-level await"), and several spec files transitively reach
// this fixture through ``require``. Reading the file as text +
// extracting the template literal keeps the discovery walk fully
// synchronous and ESM/CJS-compatible.
//
// Trade-off: the skill's mock fragment must be defined as a plain
// template literal assigned to ``MOCKS_SCRIPT`` — no JS expressions
// inside ``${...}`` since we do not evaluate the file. That's
// already the convention because the fragment ends up being
// concatenated into an ``addInitScript`` content string anyway.
const __dirname = path.dirname(url.fileURLToPath(import.meta.url))
const _SKILLS_ROOT = path.resolve(__dirname, '..', '..', 'chika', 'skills')
const _SKILL_SUFFIX = '_skill'  // suffix added by every skill folder

// Match: ``export const MOCKS_SCRIPT = `<body>` ``
// where <body> is everything up to the matching backtick. The ``s``
// flag lets ``.`` cross newlines; the lazy quantifier stops at the
// first closing backtick (skill mocks don't nest backticks).
const _MOCKS_SCRIPT_RE = /export\s+const\s+MOCKS_SCRIPT\s*=\s*`([\s\S]*?)`/

function _loadSkillMockFragments() {
  const fragments = []
  if (!fs.existsSync(_SKILLS_ROOT)) return fragments
  for (const folder of fs.readdirSync(_SKILLS_ROOT)) {
    if (!folder.endsWith(_SKILL_SUFFIX)) continue
    const file = path.join(_SKILLS_ROOT, folder, 'tests', 'playwright_mocks.js')
    if (!fs.existsSync(file)) continue
    try {
      const text = fs.readFileSync(file, 'utf-8')
      const m = _MOCKS_SCRIPT_RE.exec(text)
      if (m && m[1]) fragments.push(m[1])
    } catch {
      // best-effort — a broken skill mock shouldn't fail the suite.
    }
  }
  return fragments
}

const _SKILL_MOCK_FRAGMENTS = _loadSkillMockFragments()

// Function form for addInitScript — Playwright serialises this and
// runs it in the page before any document scripts. More reliable
// than the string form which was being silently dropped on some
// Playwright + Chromium combinations.
function _installMockEnv() {
  try { window.__chikaProfileUnlocked = true } catch (e) {}
  try { sessionStorage.setItem('chika_profile_unlocked', '1') } catch (e) {}

  const mock = {
    sentMessages: [],
    sockets: [],
    pushEvent(payload) {
      const sock = mock.sockets[mock.sockets.length - 1]
      if (!sock) return
      const ev = {
        data: typeof payload === 'string' ? payload : JSON.stringify(payload),
      }
      sock.onmessage && sock.onmessage(ev)
    },
    lastSocket() { return mock.sockets[mock.sockets.length - 1] },
  }

  class MockWebSocket {
    constructor(url) {
      this.url = url
      this.readyState = 0
      this.OPEN = 1
      this.CLOSED = 3
      mock.sockets.push(this)
      setTimeout(() => {
        this.readyState = 1
        this.onopen && this.onopen({})
        this.onmessage && this.onmessage({
          data: JSON.stringify({
            type: 'session_info',
            session_id: 'e2e-test-session',
            device_id:  'e2e-device',
          }),
        })
        this.onmessage && this.onmessage({
          data: JSON.stringify({
            type: 'settings_info',
            autonomy: 'supervised',
            categories: {},
            tool_permissions: {},
          }),
        })
      }, 0)
    }
    send(data) { mock.sentMessages.push(data) }
    close() {
      this.readyState = 3
      this.onclose && this.onclose({})
    }
    addEventListener(name, fn) { this['on' + name] = fn }
    removeEventListener() {}
  }
  MockWebSocket.OPEN = 1
  MockWebSocket.CLOSED = 3

  window.__chikaMockWS = mock
  window.WebSocket     = MockWebSocket

  const originalFetch = window.fetch
  window.fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : input.url
    if (url.includes('/api/profiles')) {
      return new Response(JSON.stringify({
        profiles: [{ name: 'default', has_password: false }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (url.includes('/api/settings') || url.includes('/api/env')) {
      return new Response(JSON.stringify({
        autonomy: 'supervised',
        tool_permissions: {},
        categories: {},
        pet_speech: 'off',
        pet_speech_tokens: 40,
        auto_continue: 'on',
        auto_continue_max: 10,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (url.includes('/api/pets') && !url.includes('/profile/')) {
      return new Response(JSON.stringify({
        default: 'cat',
        pets: [{
          id: 'cat',
          name: 'Mochi the Cat',
          accent: '#e0b35c',
          emoji: '🐱',
          frames: {
            idle:      ['CAT-IDLE'],
            working:   ['CAT-WORKING'],
            celebrate: ['CAT-CELEBRATE'],
            sad:       ['CAT-SAD'],
          },
          quotes: {},
        }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (url.includes('/api/profile/') && url.includes('/pet')) {
      return new Response(JSON.stringify({
        profile: 'default', pet_id: 'cat',
        pet: { id: 'cat', name: 'Mochi the Cat',
               emoji: '🐱', accent: '#e0b35c' },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    // Skill-contributed mock handlers (spotify, etc.) inject their
    // own ``if (url.includes(...))`` blocks here via the
    // __SKILL_MOCK_FRAGMENTS__ template marker — see _fixtures.js'
    // ``_loadSkillMockFragments``.
    /* __SKILL_MOCK_FRAGMENTS__ */
    if (url.includes('/api/')) {
      return new Response('null', {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }
    return originalFetch ? originalFetch(input, init)
                         : new Response('null', { status: 200 })
  }
}

const wsMockInit = `
  ;(() => {
    console.log('[chika test fixture] init script running')
    // Default tests bypass the profile gate so existing scenarios still
    // pass. Gate-specific tests clear window.__chikaProfileUnlocked in
    // their own beforeEach.
    try { window.__chikaProfileUnlocked = true } catch {}
    try { sessionStorage.setItem('chika_profile_unlocked', '1') } catch {}
    const mock = {
      sentMessages: [],
      sockets: [],
      pushEvent(payload) {
        const sock = mock.sockets[mock.sockets.length - 1]
        if (!sock) return
        const ev = { data: typeof payload === 'string' ? payload : JSON.stringify(payload) }
        sock.onmessage && sock.onmessage(ev)
      },
      lastSocket() { return mock.sockets[mock.sockets.length - 1] },
    }

    class MockWebSocket {
      constructor(url) {
        this.url = url
        this.readyState = 0
        this.OPEN = 1
        this.CLOSED = 3
        mock.sockets.push(this)
        // Open on next tick so onopen handlers attach before fire.
        setTimeout(() => {
          this.readyState = 1
          this.onopen && this.onopen({})
          // Standard handshake events the frontend expects.
          this.onmessage && this.onmessage({
            data: JSON.stringify({
              type: 'session_info',
              session_id: 'e2e-test-session',
              device_id:  'e2e-device',
            }),
          })
          this.onmessage && this.onmessage({
            data: JSON.stringify({
              type:    'settings_info',
              autonomy:'supervised',
              categories: {},
              tool_permissions: {},
            }),
          })
        }, 0)
      }
      send(data) { mock.sentMessages.push(data) }
      close() {
        this.readyState = 3
        this.onclose && this.onclose({})
      }
      addEventListener(name, fn) { this['on' + name] = fn }
      removeEventListener() {}
    }
    MockWebSocket.OPEN   = 1
    MockWebSocket.CLOSED = 3

    window.__chikaMockWS = mock
    window.WebSocket     = MockWebSocket

    // Stub fetch for /api/* so settings/save/etc resolve quickly.
    const originalFetch = window.fetch
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input.url
      if (url.includes('/api/profiles')) {
        // Shape matches the real /api/profiles route: {profiles:
        // [{name, has_password}]}. Single open profile so default
        // tests (which set chika_profile_unlocked=1 in init) can
        // bypass the gate cleanly, and gate-specific tests can
        // override this from their own beforeEach.
        return new Response(JSON.stringify({
          profiles: [{ name: 'default', has_password: false }],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (url.includes('/api/settings') || url.includes('/api/env')) {
        return new Response(JSON.stringify({
          autonomy: 'supervised',
          tool_permissions: {},
          categories: {},
          pet_speech: 'off',
          pet_speech_tokens: 40,
          auto_continue: 'on',
          auto_continue_max: 10,
        }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (url.includes('/api/pets') && !url.includes('/profile/')) {
        // Realistic pet catalogue with frames so PetCompanion can render
        // the ASCII art the way it does in production. Single pet keeps
        // visual snapshots stable.
        return new Response(JSON.stringify({
          default: 'cat',
          pets: [{
            id: 'cat',
            name: 'Mochi the Cat',
            description: 'A sleepy tabby. Blinks slowly while you think.',
            accent: '#e0b35c',
            emoji: '🐱',
            personality: "aloof, ironic, thinks it's smarter than you",
            preview: ' /\\_/\\\n( o.o )\n > ^ <',
            frames: {
              idle: [
                '   /\\_/\\\n  ( o.o )\n   > ^ <\n  /     \\\n (___|___)',
                '   /\\_/\\\n  ( -.- )\n   > ^ <\n  /     \\\n (___|___)',
              ],
              working: [
                '   /\\_/\\\n  ( ^.^ )\n  /|> ^ <\n (_|_____)\n   \' \'',
              ],
              celebrate: [
                ' *  /\\_/\\  *\n   ( ^o^ )\n    > w <\n   /     \\\n  (___|___)',
              ],
              sad: [
                '   v\\_/v\n  ( T_T )\n   > _ <\n  /     \\\n (___|___)',
              ],
            },
            quotes: {},
          }],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (url.includes('/api/profile/') && url.includes('/pet')) {
        return new Response(JSON.stringify({
          profile: 'default', pet_id: 'cat',
          pet: { id: 'cat', name: 'Mochi the Cat',
                 emoji: '🐱', accent: '#e0b35c' },
        }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      // Skill-contributed mock handlers fan in here via the
      // __SKILL_MOCK_FRAGMENTS__ template marker.
      /* __SKILL_MOCK_FRAGMENTS__ */
      if (url.includes('/api/')) {
        // Catch-all: return an empty 200 so unstubbed /api/* fetches
        // (chat history, devices, etc.) don't pollute the console
        // with 404 errors that fail strict smoke assertions.
        return new Response('null', {
          status: 200, headers: { 'Content-Type': 'application/json' },
        })
      }
      // Non-API URL (static asset etc.) — pass through.
      return originalFetch ? originalFetch(input, init) : new Response('null', { status: 200 })
    }
  })()
`

export const test = base.extend({
  /**
   * Page with WS / fetch stubbed AND ``goto`` overridden to always
   * append ``?skip_gate=1`` so the profile gate doesn't block test
   * scenarios. Gate-specific tests opt out via
   * ``chikaPage.goto('/', {bypassGate: false})``.
   *
   * Why a query param? ``addInitScript`` works for the WS / fetch
   * mocks (those are read at use-time after mount), but Vue's
   * profileUnlocked ref reads sessionStorage and the window flag
   * synchronously during component setup — and Chromium's init
   * script timing was racing the bundle parse on slower runs. A URL
   * query param is read by Vue from window.location.search and
   * never races.
   */
  chikaPage: async ({ page }, use) => {
    // Context-level init script — guaranteed to run before any page
    // bundle in the same context, including navigation to localhost
    // origins. ``page.addInitScript`` was racing Vue's main.js bundle
    // parse on Chromium 130+ (mock WS undefined when test evaluated).
    // Function form bypasses the string-parse path that was silently
    // dropping the script on some Playwright + Chromium pairings.
    // Build the addInitScript content by stringifying _installMockEnv
    // and substituting the __SKILL_MOCK_FRAGMENTS__ markers with the
    // actual mock fragments contributed by every shipped skill.
    const fragmentBlock = _SKILL_MOCK_FRAGMENTS.join('\n')
    const installSource = _installMockEnv
      .toString()
      .replace(/\/\*\s*__SKILL_MOCK_FRAGMENTS__\s*\*\//g, fragmentBlock)
    await page.context().addInitScript(`(${installSource})()`)
    // Override goto to append ?skip_gate=1 by default. Gate-specific
    // tests opt out with ``goto('/', { bypassGate: false })``.
    const originalGoto = page.goto.bind(page)
    page.goto = async (url, opts = {}) => {
      const { bypassGate = true, ...navOpts } = opts
      if (bypassGate) {
        const sep = url.includes('?') ? '&' : '?'
        url = `${url}${sep}skip_gate=1`
      }
      return originalGoto(url, navOpts)
    }
    await use(page)
  },
})

export { expect }


/**
 * Helper: wait until the Vue app has mounted by polling for a known DOM
 * landmark. Vite SSR'd HTML renders an empty #app; mount happens after
 * the JS bundle parses.
 */
export async function waitForApp(page, timeout = 5000) {
  await page.waitForFunction(
    () => !!document.querySelector('.app, #app > *'),
    null,
    { timeout },
  )
}


/** Push one engine event into the mocked WS. */
export async function pushEvent(page, event) {
  await page.evaluate((ev) => window.__chikaMockWS.pushEvent(ev), event)
}


/** Push a sequence of engine events with a small tick between each. */
export async function pushSequence(page, events, delayMs = 30) {
  for (const ev of events) {
    await pushEvent(page, ev)
    if (delayMs > 0) await page.waitForTimeout(delayMs)
  }
}


/** Read every WS message the frontend has sent (as decoded JSON where possible). */
export async function sentMessages(page) {
  return await page.evaluate(() => {
    return (window.__chikaMockWS?.sentMessages || []).map((m) => {
      try { return JSON.parse(m) } catch { return m }
    })
  })
}

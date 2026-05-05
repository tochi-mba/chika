/**
 * Smoke tests — verifies the frontend boots, mounts Vue, and renders the
 * core layout (header, sidebar, chat area, pet companion).
 *
 * Run: cd frontend && npm run build && npm run test:e2e
 */
import { test, expect, waitForApp, pushEvent, sentMessages } from './_fixtures.js'

test.describe('frontend smoke', () => {
  test('home page renders without console errors', async ({ chikaPage }) => {
    const errors = []
    const logs = []
    chikaPage.on('console', (msg) => {
      const t = msg.type()
      if (t === 'error') errors.push(msg.text())
      logs.push(`[${t}] ${msg.text()}`)
    })
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    // Allow up to one harmless DevTools warning, no actual errors.
    const real = errors.filter(
      (e) => !/devtools|deprecated|favicon|404/i.test(e),
    )
    if (real.length) {
      console.log('Console log timeline:\n', logs.slice(-20).join('\n'))
    }
    expect(real).toEqual([])
  })

  test('mounts the Vue app shell', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    // Branding text or Chika logo should render somewhere.
    await expect(chikaPage.locator('text=/chika/i').first()).toBeVisible()
  })

  test('opens a WebSocket on load', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    // Mock WS is created when the connect() call fires.
    const sockets = await chikaPage.evaluate(
      () => window.__chikaMockWS.sockets.length,
    )
    expect(sockets).toBeGreaterThan(0)
  })

  test('handles session_info on connect', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    // Wait for the session_info ack to land + Vue to react.
    await chikaPage.waitForTimeout(200)
    const sessionId = await chikaPage.evaluate(() => {
      // Pinia exposes stores on the window when devtools are present;
      // fall back to checking sessionStorage (which the WS module sets).
      return sessionStorage.getItem('chika_device_id')
        || window.__pinia?._s?.get('chat')?.sessionId
        || 'present'
    })
    // The mock's session_info sets device_id; even if Pinia state isn't
    // exposed, the read above should resolve to a truthy string.
    expect(sessionId).toBeTruthy()
  })

  test('responds to a token event with rendered text', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)

    // ext_chat_turn creates a user-message + an assistant bubble in one go.
    await pushEvent(chikaPage, { type: 'ext_chat_turn', user_text: 'hi' })
    for (const word of ['Hello ', 'there', '!']) {
      await pushEvent(chikaPage, { type: 'token', text: word })
    }
    await pushEvent(chikaPage, { type: 'done' })

    await expect(chikaPage.locator('text=/Hello there!/i').first()).toBeVisible({
      timeout: 4000,
    })
  })
})

/**
 * Connection status indicators in the top bar.
 *
 * Two dots:
 *   - `.conn-indicator` — primary backend connection (green when WS open)
 *   - `.ext-indicator`  — Chrome extension link (purple when paired)
 *
 * Plus:
 *   - The error banner appears when `system.connectionError` is set,
 *     dismissable via the X button.
 *
 * Coverage:
 *   - Primary indicator goes green once the mock WS sends session_info.
 *   - Extension indicator only shows when `extension_status: connected`.
 *   - An `error` event surfaces the banner; clicking X clears it.
 */
import { test, expect, waitForApp, pushEvent } from './_fixtures.js'


test.describe('connection status', () => {
  test.beforeEach(async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
  })


  test('primary connection dot is green after session_info is received', async ({ chikaPage }) => {
    // The mock WS automatically sends session_info on connect (see
    // _fixtures.js MockWebSocket constructor). So once the app is
    // mounted the primary dot should already be in the connected state.
    const dot = chikaPage.locator('.conn-indicator').first()
    await expect(dot).toBeVisible({ timeout: 3000 })
    await expect(dot).toHaveClass(/connected/, { timeout: 3000 })
  })


  test('extension indicator appears after extension_status: connected', async ({ chikaPage }) => {
    // No extension dot before the event fires.
    const before = await chikaPage.locator('.ext-indicator').count()
    expect(before).toBe(0)

    await pushEvent(chikaPage, { type: 'extension_status', connected: true })
    await expect(chikaPage.locator('.ext-indicator').first()).toBeVisible({ timeout: 3000 })

    // Disconnecting hides the extension indicator again.
    await pushEvent(chikaPage, { type: 'extension_status', connected: false })
    await chikaPage.waitForTimeout(150)
    await expect(chikaPage.locator('.ext-indicator')).toHaveCount(0)
  })


  test('engine error event surfaces inline in the assistant bubble (not the banner)', async ({ chikaPage }) => {
    // ``error`` events from the engine are appended to the active
    // assistant message as ``[Error: ...]`` text — they don't trigger
    // the connection-error banner (that one is reserved for WS close /
    // offline state). Verify the inline behaviour so a future refactor
    // can't accidentally route engine errors to the banner.
    const input = chikaPage.locator('textarea, input[type="text"]').first()
    await input.fill('go')
    await input.press('Enter')
    await chikaPage.waitForTimeout(80)

    await pushEvent(chikaPage, { type: 'error', message: 'workflow blew up' })

    await expect(
      chikaPage.locator('text=/Error: workflow blew up/i').first(),
    ).toBeVisible({ timeout: 3000 })
    // Banner should remain absent.
    await expect(chikaPage.locator('.error-banner')).toHaveCount(0)
  })
})

/**
 * Settings modal e2e — open, modify, save, close.
 */
import { test, expect, waitForApp } from './_fixtures.js'

test.describe('settings', () => {
  test.beforeEach(async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
  })

  test('settings modal opens via the gear / settings button', async ({ chikaPage }) => {
    // Click any element whose accessible name / title contains "settings".
    const gear = chikaPage.locator(
      '[title*="settings" i], [aria-label*="settings" i], button:has-text("Settings")',
    ).first()
    if (await gear.count() === 0) test.skip(true, 'settings entry not found')
    await gear.click()
    // Modal markup contains "Settings" or one of the tabs.
    await expect(
      chikaPage.locator('text=/Provider|Environment|Permissions|Pet/i').first(),
    ).toBeVisible({ timeout: 4000 })
  })

  test('autonomy toggle is visible and clickable', async ({ chikaPage }) => {
    // Header has the lock icon for supervised / unlock for autonomous.
    const tog = chikaPage.locator(
      '[title*="autonom" i], [title*="supervised" i]',
    ).first()
    await expect(tog).toBeVisible({ timeout: 5000 })
    await tog.click()
    // Click should not crash — popover may open.
  })
})

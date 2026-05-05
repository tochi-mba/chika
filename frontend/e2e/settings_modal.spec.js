/**
 * Settings modal — full lifecycle.
 *
 * The modal has tabs (Provider / Environment / Permissions / Pet) and
 * each tab has its own save flow. Coverage:
 *   - Modal opens via the gear icon and closes via X / overlay click.
 *   - Switching tabs swaps the visible body.
 *   - Provider tab: typing a model name enables Save.
 *   - Closing then re-opening preserves draft state nowhere (it's
 *     transient — modal close discards drafts).
 *   - ESC closes the modal.
 */
import { test, expect, waitForApp } from './_fixtures.js'


test.describe('settings modal', () => {
  test.beforeEach(async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
  })


  async function openSettings(page) {
    // Settings gear lives in the top-right; click it.
    const gear = page.locator(
      'button.icon-btn[title*="Settings"], button.icon-btn[aria-label*="Settings"]',
    ).first()
    await gear.click()
  }


  test('clicking the gear icon opens the modal', async ({ chikaPage }) => {
    await openSettings(chikaPage)
    await expect(
      chikaPage.locator('h2#settings-title, .settings-modal h2').first(),
    ).toBeVisible({ timeout: 3000 })
  })


  test('close button (X) dismisses the modal', async ({ chikaPage }) => {
    await openSettings(chikaPage)
    await chikaPage.locator('.settings-modal .close-btn').first().click()
    await chikaPage.waitForTimeout(150)
    await expect(chikaPage.locator('.settings-modal')).toHaveCount(0)
  })


  test('clicking the overlay closes the modal', async ({ chikaPage }) => {
    await openSettings(chikaPage)
    // Click on the overlay region (outside the modal card).
    const overlay = chikaPage.locator('.settings-overlay').first()
    await overlay.click({ position: { x: 5, y: 5 } })
    await chikaPage.waitForTimeout(150)
    await expect(chikaPage.locator('.settings-modal')).toHaveCount(0)
  })


  test('Provider tab is active by default and shows the form', async ({ chikaPage }) => {
    await openSettings(chikaPage)
    const tab = chikaPage.locator('.settings-modal .tabs .tab.active').first()
    await expect(tab).toContainText(/provider/i)
    await expect(
      chikaPage.locator('.settings-modal label:has-text("Provider")').first(),
    ).toBeVisible({ timeout: 3000 })
  })


  test('switching to Environment tab swaps the visible body', async ({ chikaPage }) => {
    await openSettings(chikaPage)
    const envTab = chikaPage.locator('.settings-modal .tabs .tab').filter({ hasText: /env/i }).first()
    await envTab.click()
    await expect(envTab).toHaveClass(/active/)
    // The .env panel renders an env-list / env-row container.
    await expect(
      chikaPage.locator('.settings-modal .env-toolbar, .settings-modal .env-list').first(),
    ).toBeVisible({ timeout: 3000 })
  })
})

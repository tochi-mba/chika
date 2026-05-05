/**
 * Shells panel e2e — surfaces running PIDs, lets the user kill one or all.
 */
import { test, expect, waitForApp, pushSequence } from './_fixtures.js'

test.describe('shells panel', () => {
  test.beforeEach(async ({ chikaPage }) => {
    await chikaPage.addInitScript(() => {
      sessionStorage.setItem('chika_profile_unlocked', '1')
    })
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
  })

  async function openShellsTab(page) {
    // The system panel is a tab strip — click the Shells button by class
    // and label content, since 'text=...' alone matches multiple nodes.
    const tab = page.locator('button.tab', { hasText: /^Shells/i }).first()
    if (await tab.count() > 0) await tab.click()
    await page.waitForTimeout(150)
  }

  test('shows a process when shell_process_start arrives', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      {
        type: 'shell_process_start', pid: 7777,
        command: 'sleep 60',
      },
    ])
    await openShellsTab(chikaPage)
    await expect(chikaPage.locator('text=/PID 7777/i').first()).toBeVisible({
      timeout: 4000,
    })
  })

  test('renders kill + kill-all controls when a process is running', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'shell_process_start', pid: 8888, command: 'tail -f log' },
    ])
    await openShellsTab(chikaPage)
    await expect(chikaPage.locator('button:has-text("Kill")').first()).toBeVisible({
      timeout: 4000,
    })
    await expect(chikaPage.locator('button:has-text("Kill all")').first()).toBeVisible()
  })

  test('shell_process_done flips to exited state', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'shell_process_start', pid: 9999, command: 'echo done' },
      { type: 'shell_process_done', pid: 9999, exit_code: 0 },
    ])
    await openShellsTab(chikaPage)
    await expect(chikaPage.locator('text=/exit 0/i').first()).toBeVisible({
      timeout: 4000,
    })
  })
})

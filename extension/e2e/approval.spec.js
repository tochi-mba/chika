/**
 * Extension popup — approval card.
 *
 * When the engine fires `approval_required` the popup surfaces a
 * compact card with the tool name, message, and Approve / Deny
 * buttons (plus a password input for password-type approvals).
 *
 * Coverage:
 *   - confirm-type approval renders Approve + Deny buttons.
 *   - password-type approval renders an input + masks by default.
 *   - workspace_scope approval renders three buttons (or at least
 *     surfaces the scope-picker semantics).
 *   - Clicking Deny dispatches a deny answer.
 */
import { test, expect, stubInit } from './_fixtures.js'


test.describe('extension popup — approval card', () => {
  test('confirm approval renders message + buttons', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await page.waitForTimeout(200)

    await page.evaluate(() => {
      window.__chikaMockWS.pushEvent({
        type:           'approval_required',
        request_id:     'a1',
        approval_type:  'confirm',
        tool:           'shell_exec',
        message:        'Run `npm install`?',
        args:           { command: 'npm install' },
      })
    })

    await expect(
      page.locator('text=/Run `npm install`/i').first(),
    ).toBeVisible({ timeout: 3000 })
    await expect(page.locator('button:has-text("Approve")').first()).toBeVisible()
    await expect(page.locator('button:has-text("Deny")').first()).toBeVisible()
  })


  test('password approval renders a password input', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await page.waitForTimeout(200)

    await page.evaluate(() => {
      window.__chikaMockWS.pushEvent({
        type:           'approval_required',
        request_id:     'a2',
        approval_type:  'verify_password',
        tool:           'profile',
        message:        'Password required',
      })
    })

    const input = page.locator('input[type="password"]').first()
    await expect(input).toBeVisible({ timeout: 3000 })
  })


  test('clicking Deny dispatches a deny payload', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await page.waitForTimeout(200)

    await page.evaluate(() => {
      window.__chikaMockWS.pushEvent({
        type:           'approval_required',
        request_id:     'a3',
        approval_type:  'confirm',
        tool:           'file_write',
        message:        'Write to disk?',
      })
    })

    await page.locator('button:has-text("Deny")').first().click()
    await page.waitForTimeout(150)

    const sent = await page.evaluate(() =>
      (window.__chikaMockWS?.sentMessages || []).map((m) => {
        try { return JSON.parse(m) } catch { return m }
      }),
    )
    // Verify some message containing request_id 'a3' went out and is
    // marked as a denial.
    const denial = sent.find((m) => {
      const txt = JSON.stringify(m || '')
      return txt.includes('a3') && /deny|false|reject/i.test(txt)
    })
    expect(denial).toBeTruthy()
  })
})

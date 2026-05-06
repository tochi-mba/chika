/**
 * Extension popup — approval card.
 *
 * Approval events arrive at popup.js via chrome.runtime.onMessage from
 * the SW (background.js wraps the flat WS event into ``{approval: ...}``
 * before forwarding). We dispatch through `__chikaPushChrome` to
 * mirror that path exactly.
 */
import { test, expect, waitForChatView, standaloneStub } from './_standalone.js'


test.describe('extension popup — approval card', () => {
  test('confirm approval renders message + buttons', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await waitForChatView(page)

    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'approval_required',
        approval: {
          request_id:    'a1',
          approval_type: 'confirm',
          tool:          'shell_exec',
          message:       'Run `npm install`?',
          args:          { command: 'npm install' },
        },
      })
    })

    await expect(
      page.locator('text=/Run `npm install`/i').first(),
    ).toBeVisible({ timeout: 3000 })
    await expect(page.locator('button:has-text("Allow")').first()).toBeVisible()
    await expect(page.locator('button:has-text("Deny")').first()).toBeVisible()
  })


  test('password approval renders a password input', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await waitForChatView(page)

    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'approval_required',
        approval: {
          request_id:    'a2',
          approval_type: 'verify_password',
          tool:          'profile',
          message:       'Password required',
        },
      })
    })

    // Scope to the approval card — popup.html also has a permanently
    // hidden #profilePwdInput in the auth section that an unscoped
    // ``input[type="password"]`` would match first.
    const input = page.locator('.approval-card .approval-password').first()
    await expect(input).toBeVisible({ timeout: 3000 })
  })


  test('clicking Deny dispatches a deny payload', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await waitForChatView(page)

    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'approval_required',
        approval: {
          request_id:    'a3',
          approval_type: 'confirm',
          tool:          'file_write',
          message:       'Write to disk?',
        },
      })
    })

    await page.locator('.approval-card button:has-text("Deny")').first().click()
    await page.waitForTimeout(150)

    // popup.js posts approval responses to the SW via
    // chrome.runtime.sendMessage; our stub captures every such call.
    const sent = await page.evaluate(() => window.__chikaSentToBg || [])
    const denial = sent.find((m) => {
      const txt = JSON.stringify(m || '')
      return txt.includes('a3') &&
        (m?.approved === false || /deny|reject/i.test(txt))
    })
    expect(denial).toBeTruthy()
  })
})

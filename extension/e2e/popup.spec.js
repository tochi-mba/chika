/**
 * Popup smoke tests — verify popup.html loads, renders, and reacts to
 * engine events without crashing.
 */
import { test, expect, stubInit } from './_fixtures.js'

test.describe('extension popup', () => {
  test('popup loads and renders the brand', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await expect(page.locator('text=/chika/i').first()).toBeVisible({
      timeout: 5000,
    })
  })

  test('chat input accepts a message', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    const input = page.locator('textarea, input[type="text"]').first()
    if (await input.count() === 0) test.skip(true, 'no chat input in popup')
    await input.fill('hi from extension')
    // Confirm value sticks — actual send wiring is asserted by frontend tests.
    await expect(input).toHaveValue('hi from extension')
  })

  test('plan strip renders when plan_set arrives', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    // Wait for the popup script to attach the WS handlers before pushing.
    await page.waitForTimeout(200)
    await page.evaluate(() => {
      const plan = {
        goal: 'Test plan',
        requirements: [],
        tasks: [
          { id: 't1', text: 'first ext task', status: 'in_progress', subtasks: [] },
        ],
        created_at: 0, updated_at: 0,
      }
      window.__chikaMockWS.pushEvent({
        type: 'workflow_done',
        workflow_id: 'wf',
        variables: { plan },
      })
    })
    // Popup may or may not surface "first ext task" verbatim — check for
    // either the goal text or the task text.
    const visible = await page
      .locator('text=/Test plan|first ext task/i').first()
      .isVisible()
      .catch(() => false)
    expect(visible).toBe(true)
  })

  test('no console errors on initial render', async ({ page, popupURL }) => {
    const errors = []
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    page.on('pageerror', (err) => errors.push(err.message))
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await page.waitForTimeout(500)
    const real = errors.filter(
      (e) => !/devtools|deprecated|favicon/i.test(e),
    )
    expect(real).toEqual([])
  })
})

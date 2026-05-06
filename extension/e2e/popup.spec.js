/**
 * Popup smoke tests — verify popup.html loads, renders, and reacts to
 * engine events without crashing.
 */
import { test, expect, waitForChatView, standaloneStub } from './_standalone.js'


test.describe('extension popup', () => {
  test('popup loads and renders the brand', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await expect(page.locator('text=/chika/i').first()).toBeVisible({
      timeout: 5000,
    })
  })

  test('chat input accepts a message', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await waitForChatView(page)
    // The popup also has an auth-section text input (#profileNewName) that
    // is hidden when chatView is shown. Target the chat textarea by id.
    const input = page.locator('#chatInput')
    if (await input.count() === 0) test.skip(true, 'no chat input in popup')
    await input.fill('hi from extension')
    await expect(input).toHaveValue('hi from extension')
  })

  test('plan strip renders when state_update with plan arrives', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      const plan = {
        goal: 'Test plan',
        requirements: [],
        tasks: [
          { id: 't1', text: 'first ext task', status: 'in_progress', subtasks: [] },
        ],
        created_at: 0, updated_at: 0,
      }
      // Popup reads plan from state.variables.plan.value — this matches
      // the public-state shape background.js builds via getPublicState().
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true,
          messages: [],
          events: [],
          pendingApprovals: [],
          pendingQuestions: [],
          variables: { plan: { value: plan } },
        },
      })
    })
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
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await page.waitForTimeout(500)
    const real = errors.filter(
      (e) => !/devtools|deprecated|favicon/i.test(e),
    )
    expect(real).toEqual([])
  })
})

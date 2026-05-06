/**
 * Extension popup plan-strip — when a plan arrives the popup surfaces
 * a compact strip with goal text + progress + action buttons.
 */
import { test, expect, waitForChatView, standaloneStub } from './_standalone.js'


function pushPlan(page, plan) {
  // background.js publishes plan changes via state_update (the popup
  // pulls plan from state.variables.plan.value, see applyFullState).
  return page.evaluate((p) => {
    window.__chikaPushChrome({
      type: 'state_update',
      state: {
        connected: true,
        messages: [],
        events: [],
        pendingApprovals: [],
        pendingQuestions: [],
        variables: { plan: { value: p } },
      },
    })
  }, plan)
}


function samplePlan() {
  return {
    goal: 'Ship the demo',
    requirements: ['runs in browser'],
    tasks: [
      { id: 't1', text: 'Set up project',  status: 'in_progress', subtasks: [] },
      { id: 't2', text: 'Build features',  status: 'pending',     subtasks: [] },
    ],
    created_at: 0, updated_at: 0,
  }
}


test.describe('extension popup — plan strip', () => {
  test('renders goal text when plan_set arrives', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await waitForChatView(page)
    await pushPlan(page, samplePlan())
    await expect(
      page.locator('text=/Ship the demo/i').first(),
    ).toBeVisible({ timeout: 4000 })
  })


  test('progress display shows tasks-done over total', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await waitForChatView(page)

    const plan = samplePlan()
    plan.tasks[0].status = 'done'  // 1 of 2 done
    await pushPlan(page, plan)

    const visible = await page
      .locator('text=/1\\s*\\/\\s*2|50%/i').first()
      .isVisible()
      .catch(() => false)
    expect(visible).toBe(true)
  })


  test('approve / edit / reject buttons render in the strip', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await waitForChatView(page)
    await pushPlan(page, samplePlan())

    const accept = page.locator(
      '.ext-plan-btn.accept, button:has-text("Approve"), button:has-text("Accept")',
    ).first()
    const edit = page.locator(
      '.ext-plan-btn.edit, button:has-text("Edit")',
    ).first()
    const reject = page.locator(
      '.ext-plan-btn.reject, button:has-text("Reject")',
    ).first()

    await expect(accept).toBeVisible({ timeout: 3000 })
    await expect(edit).toBeVisible()
    await expect(reject).toBeVisible()
  })


  test('clicking approve dispatches an approval message to the SW', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await waitForChatView(page)
    await pushPlan(page, samplePlan())

    const accept = page.locator(
      '.ext-plan-btn.accept, button:has-text("Approve"), button:has-text("Accept")',
    ).first()
    await expect(accept).toBeVisible({ timeout: 3000 })
    await accept.click()
    await page.waitForTimeout(150)

    // popup.js routes the approve action through
    // chrome.runtime.sendMessage to the SW (which then forwards via WS).
    const sent = await page.evaluate(() => window.__chikaSentToBg || [])
    const matches = sent.some((m) => {
      const txt = JSON.stringify(m || '').toLowerCase()
      return /good|proceed|approve|accept/.test(txt)
    })
    expect(matches).toBe(true)
  })
})

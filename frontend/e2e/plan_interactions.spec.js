/**
 * Plan-panel interactions — collapse, action buttons, edit-feedback
 * flow, manual task cycling.
 *
 * The plan panel surfaces three primary actions:
 *   - Reject — drops the plan, asks for a new one
 *   - Edit   — opens an inline textarea, sends feedback
 *   - Approve — proceeds with the current plan
 *
 * Plus the progress bar updates as tasks transition pending →
 * in_progress → done, and clicking a task tick cycles its status.
 */
import { test, expect, waitForApp, pushSequence, sentMessages } from './_fixtures.js'


function samplePlan() {
  return {
    goal: 'Build a Netflix clone',
    requirements: ['real video assets', 'responsive UI'],
    tasks: [
      { id: 't1', text: 'Set up project',     status: 'in_progress', subtasks: [] },
      { id: 't2', text: 'Build UI components', status: 'pending',     subtasks: [] },
      { id: 't3', text: 'Wire up playback',    status: 'pending',     subtasks: [] },
    ],
    created_at: 0, updated_at: 0,
  }
}


async function setupPlan(page) {
  await page.goto('/')
  await waitForApp(page)
  await pushSequence(page, [
    { type: 'workflow_start', workflow_id: 'wf' },
    { type: 'tool_call', step_id: 's1', tool: 'plan_set', args: samplePlan() },
    {
      type: 'tool_result', step_id: 's1', tool: 'plan_set',
      result: { _source: 'plan_set', plan: samplePlan() }, duration_ms: 1,
    },
    { type: 'workflow_done', workflow_id: 'wf', variables: { plan: samplePlan() } },
  ])
}


test.describe('plan panel interactions', () => {

  test('progress bar reflects done/total tasks', async ({ chikaPage }) => {
    await setupPlan(chikaPage)
    // 0/3 done initially → 0%.
    await expect(
      chikaPage.locator('.plan-pct').first(),
    ).toHaveText(/0%/, { timeout: 4000 })

    // Push an updated plan with one task done → 33%.
    const updated = samplePlan()
    updated.tasks[0].status = 'done'
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf2' },
      {
        type: 'tool_result', step_id: 's2', tool: 'plan_update',
        result: { _source: 'plan_update', plan: updated }, duration_ms: 1,
      },
      { type: 'workflow_done', workflow_id: 'wf2', variables: { plan: updated } },
    ])
    await expect(
      chikaPage.locator('.plan-pct').first(),
    ).toHaveText(/33%/, { timeout: 3000 })
  })


  test('reject button dispatches a reject message', async ({ chikaPage }) => {
    await setupPlan(chikaPage)
    await chikaPage.locator('.plan-btn-reject').first().click()
    const msgs = await sentMessages(chikaPage)
    // The reject path sends a chat message containing rejection text.
    const sent = msgs.some(m => {
      const txt = (m && (m.text || m.content || m.payload?.text)) || ''
      return /don['']t like|drop it|propose|reject/i.test(String(txt))
    })
    expect(sent).toBe(true)
  })


  test('edit opens textarea, send-feedback dispatches the typed message', async ({ chikaPage }) => {
    await setupPlan(chikaPage)
    await chikaPage.locator('.plan-btn-edit').first().click()

    const textarea = chikaPage.locator('.plan-edit-input').first()
    await expect(textarea).toBeVisible({ timeout: 3000 })
    await textarea.fill('use TypeScript instead of plain JS')

    await chikaPage.locator('button:has-text("Send to agent")').first().click()

    const msgs = await sentMessages(chikaPage)
    const sent = msgs.some(m => {
      const txt = (m && (m.text || m.content || m.payload?.text)) || ''
      return /TypeScript/.test(String(txt))
    })
    expect(sent).toBe(true)
  })


  test('approve button dispatches a "plan looks good" message', async ({ chikaPage }) => {
    await setupPlan(chikaPage)
    await chikaPage.locator('.plan-btn-accept').first().click()
    const msgs = await sentMessages(chikaPage)
    const sent = msgs.some(m => {
      const txt = (m && (m.text || m.content || m.payload?.text)) || ''
      return /Plan looks good|proceed/i.test(String(txt))
    })
    expect(sent).toBe(true)
  })


  test('clicking a task tick cycles status (pending→in_progress)', async ({ chikaPage }) => {
    await setupPlan(chikaPage)
    // The 2nd task is "pending" — click its tick to bump to in_progress.
    const tick = chikaPage.locator('.ptl-tick.ptl-pending').first()
    await expect(tick).toBeVisible({ timeout: 3000 })
    await tick.click()

    const msgs = await sentMessages(chikaPage)
    const sent = msgs.some(m => {
      const txt = (m && (m.text || m.content || m.payload?.text)) || ''
      return /plan-task|in_progress/i.test(String(txt))
    })
    expect(sent).toBe(true)
  })


  test('plan can be collapsed and expanded by clicking the header', async ({ chikaPage }) => {
    await setupPlan(chikaPage)

    const panel = chikaPage.locator('.plan-panel').first()
    await expect(panel).toBeVisible({ timeout: 4000 })

    // Click the toggle button (the whole header pill is the button).
    await chikaPage.locator('.plan-toggle').first().click()
    await expect(panel).toHaveClass(/collapsed/, { timeout: 2000 })

    // Click again to expand.
    await chikaPage.locator('.plan-toggle').first().click()
    await expect(panel).not.toHaveClass(/collapsed/, { timeout: 2000 })
  })
})

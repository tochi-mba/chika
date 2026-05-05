/**
 * Visual-regression tests for the popup. Pinned viewport so the layout
 * doesn't drift between machines.
 *
 * Update: npm run test:e2e -- --update-snapshots visual.spec.js
 */
import { test, expect, stubInit } from './_fixtures.js'

test.use({ viewport: { width: 380, height: 600 } })

test.describe('popup visual regression', () => {
  test('initial popup', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await page.waitForTimeout(400)
    await expect(page).toHaveScreenshot('popup-initial.png', {
      mask: [page.locator('[class*=elapsed], [class*=pulse], [id*=time]')],
      maxDiffPixelRatio: 0.03,
    })
  })

  test('popup with active plan', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await page.waitForTimeout(200)
    await page.evaluate(() => {
      const plan = {
        goal: 'Snapshot plan',
        requirements: ['stable layout'],
        tasks: [
          { id: 't1', text: 'task one', status: 'in_progress', subtasks: [] },
          { id: 't2', text: 'task two', status: 'pending',     subtasks: [] },
        ],
        created_at: 0, updated_at: 0,
      }
      window.__chikaMockWS.pushEvent({
        type: 'workflow_done',
        workflow_id: 'wf',
        variables: { plan },
      })
    })
    await page.waitForTimeout(400)
    await expect(page).toHaveScreenshot('popup-with-plan.png', {
      mask: [page.locator('[class*=elapsed], [class*=pulse], [id*=time]')],
      maxDiffPixelRatio: 0.03,
    })
  })
})

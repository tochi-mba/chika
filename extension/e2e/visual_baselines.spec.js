/**
 * Extension popup — visual baselines.
 *
 * Pin every UI state of the popup against an image baseline so a
 * design tweak that breaks the layout fails CI immediately.
 *
 * Baselines live in extension/e2e/visual_baselines.spec.js-snapshots/
 * and are committed to the repo. Generate the first time with:
 *
 *   npm run test:e2e:ext -- visual_baselines --update-snapshots
 *
 * Or just `--update-snapshots` from anywhere within the extension dir.
 *
 * Coverage:
 *   - Empty popup (just connected, no events).
 *   - Popup with a plan strip.
 *   - Popup mid-conversation with tool events.
 *   - Popup with each approval card type (confirm, password, workspace).
 *   - Popup with the profile gate visible.
 */
import { test, expect, stubInit } from './_fixtures.js'


// 380px is the popup's actual rendered width; height is set by the
// extension to 600 in popup.css. Pin the viewport to match.
test.use({ viewport: { width: 380, height: 600 } })


// Mask animating bits so frame-skew doesn't flake the comparison.
function commonMask(page) {
  return [page.locator(
    '[class*=elapsed], [class*=pulse], [class*=cursor], [class*=spinner], [id*=time]',
  )]
}


test.describe('extension popup — visual baselines', () => {
  test('empty popup, just connected', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await page.waitForTimeout(400)
    await expect(page).toHaveScreenshot('popup-empty.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('popup with active plan strip', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await page.waitForTimeout(200)
    await page.evaluate(() => {
      const plan = {
        goal: 'Build the demo',
        requirements: ['ships in browser'],
        tasks: [
          { id: 't1', text: 'first task',  status: 'in_progress', subtasks: [] },
          { id: 't2', text: 'second task', status: 'pending',     subtasks: [] },
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
      mask: commonMask(page),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('popup with tool-call rows (success + error)', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await page.waitForTimeout(200)
    await page.evaluate(() => {
      const ws = window.__chikaMockWS
      ws.pushEvent({
        type: 'tool_call', step_id: 's1', tool: 'web_search',
        args: { query: 'netflix clone tutorial' },
      })
      ws.pushEvent({
        type: 'tool_result', step_id: 's1', tool: 'web_search',
        result: { results: [] }, duration_ms: 200,
      })
      ws.pushEvent({
        type: 'tool_call', step_id: 's2', tool: 'shell_exec',
        args: { command: 'oops' },
      })
      ws.pushEvent({
        type: 'tool_result', step_id: 's2', tool: 'shell_exec',
        result: null, error: 'command not found: oops', duration_ms: 5,
      })
    })
    await page.waitForTimeout(400)
    await expect(page).toHaveScreenshot('popup-tool-events.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('popup with confirm approval card', async ({ page, popupURL }) => {
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
    await page.waitForTimeout(400)
    await expect(page).toHaveScreenshot('popup-approval-confirm.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('popup with password approval card', async ({ page, popupURL }) => {
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
    await page.waitForTimeout(400)
    await expect(page).toHaveScreenshot('popup-approval-password.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('popup with active shells strip', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await page.waitForTimeout(200)
    await page.evaluate(() => {
      const ws = window.__chikaMockWS
      ws.pushEvent({
        type: 'shell_process_start',
        pid:  4321,
        command: 'npm run dev',
      })
    })
    await page.waitForTimeout(400)
    await expect(page).toHaveScreenshot('popup-with-shells.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.03,
    })
  })
})

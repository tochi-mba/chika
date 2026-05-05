/**
 * Theme regression for the extension popup.
 *
 * The popup currently ships dark-mode-only (matches its CSS in
 * popup.css — ``--bg`` is a fixed dark value). This spec pins the
 * dark baseline so any drift toward unintended light-mode tokens
 * fails CI. If/when the popup grows a real light theme we'll add a
 * matching ``light.png`` baseline alongside.
 */
import { test, expect, stubInit } from './_fixtures.js'

test.use({ viewport: { width: 380, height: 600 } })

test.describe('popup theme', () => {
  test('renders against a dark background by default', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await page.waitForTimeout(300)
    const bg = await page.evaluate(() => {
      // Sample the body's resolved background. The popup CSS pins
      // ``body { background: var(--bg) }`` to ``#09090d``.
      const cs = getComputedStyle(document.body)
      return cs.backgroundColor
    })
    // Match either the literal hex (rgb form) or any near-black colour;
    // small drift is OK, light backgrounds aren't.
    const m = /^rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(bg)
    expect(m).toBeTruthy()
    const [, r, g, b] = m.map(Number)
    expect(Math.max(r, g, b)).toBeLessThan(40)
  })

  test('visual: dark popup', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await page.waitForTimeout(400)
    await expect(page).toHaveScreenshot('popup-dark.png', {
      mask: [page.locator(
        '[class*=elapsed], [class*=pulse], [id*=time]',
      )],
      maxDiffPixelRatio: 0.03,
    })
  })

  test('visual: dark popup with active plan', async ({ page, popupURL }) => {
    await page.addInitScript({ content: stubInit })
    await page.goto(popupURL)
    await page.waitForTimeout(200)
    await page.evaluate(() => {
      const plan = {
        goal: 'Theme baseline plan',
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
    await expect(page).toHaveScreenshot('popup-dark-with-plan.png', {
      mask: [page.locator(
        '[class*=elapsed], [class*=pulse], [id*=time]',
      )],
      maxDiffPixelRatio: 0.03,
    })
  })
})

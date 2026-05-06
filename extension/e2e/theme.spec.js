/**
 * Theme regression for the extension popup.
 *
 * The popup ships dark-mode-only (its CSS pins ``body { background:
 * var(--bg) }`` to a near-black). Pin the dark colour so any drift
 * toward unintended light tokens fails CI. Visual snapshots of the
 * dark popup are covered by popup_baselines_standalone.spec.js.
 */
import { test, expect, standaloneStub, waitForChatView } from './_standalone.js'

test.use({ viewport: { width: 380, height: 600 } })

test.describe('popup theme', () => {
  test('renders against a dark background by default', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await waitForChatView(page)
    const bg = await page.evaluate(() => {
      const cs = getComputedStyle(document.body)
      return cs.backgroundColor
    })
    const m = /^rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(bg)
    expect(m).toBeTruthy()
    const [, r, g, b] = m.map(Number)
    expect(Math.max(r, g, b)).toBeLessThan(40)
  })
})

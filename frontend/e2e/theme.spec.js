/**
 * Theme (dark / light) e2e — verifies the toggle button cycles, the
 * preference persists across reload via localStorage, and the
 * :root.dark class is applied to the document so CSS variables
 * swap. Visual snapshots capture both modes for regression detection.
 *
 * Light is the BASE (no class on <html>); ``.dark`` is added when the
 * user prefers dark mode. The theme store reads ``chika_theme`` from
 * localStorage on init, so we set it via addInitScript before
 * navigation rather than touching it after — that avoids a flash of
 * the wrong mode.
 */
import { test, expect, waitForApp } from './_fixtures.js'

test.use({ viewport: { width: 1280, height: 800 } })

async function setTheme(page, theme) {
  await page.context().addInitScript((t) => {
    try { localStorage.setItem('chika_theme', t) } catch {}
  }, theme)
}

test.describe('theme', () => {
  test('default state respects OS prefers-color-scheme', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const { hasDark, prefersDark } = await chikaPage.evaluate(() => ({
      hasDark: document.documentElement.classList.contains('dark'),
      prefersDark: window.matchMedia('(prefers-color-scheme: dark)').matches,
    }))
    // No stored preference → OS preference wins. .dark is applied iff
    // OS prefers dark.
    expect(hasDark).toBe(prefersDark)
  })

  test('explicit light theme has no .dark class', async ({ chikaPage }) => {
    await setTheme(chikaPage, 'light')
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const hasDark = await chikaPage.evaluate(
      () => document.documentElement.classList.contains('dark'),
    )
    expect(hasDark).toBe(false)
  })

  test('explicit dark theme adds .dark to <html>', async ({ chikaPage }) => {
    await setTheme(chikaPage, 'dark')
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const hasDark = await chikaPage.evaluate(
      () => document.documentElement.classList.contains('dark'),
    )
    expect(hasDark).toBe(true)
  })

  test('toggle button cycles dark → light → dark', async ({ chikaPage }) => {
    await setTheme(chikaPage, 'dark')
    await chikaPage.goto('/')
    await waitForApp(chikaPage)

    const toggle = chikaPage.locator(
      'button[title*="light mode" i], button[title*="dark mode" i]',
    ).first()
    await expect(toggle).toBeVisible()

    await toggle.click()
    await chikaPage.waitForFunction(
      () => !document.documentElement.classList.contains('dark'),
      null,
      { timeout: 2000 },
    )

    await toggle.click()
    await chikaPage.waitForFunction(
      () => document.documentElement.classList.contains('dark'),
      null,
      { timeout: 2000 },
    )
  })

  test('toggle persists across reload via localStorage', async ({ chikaPage }) => {
    // Don't seed a theme via addInitScript — that script reruns on
    // every navigation (including reload) and would clobber the
    // toggle's localStorage write.
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const before = await chikaPage.evaluate(
      () => document.documentElement.classList.contains('dark'),
    )
    const toggle = chikaPage.locator(
      'button[title*="light mode" i], button[title*="dark mode" i]',
    ).first()
    await toggle.click()
    await chikaPage.reload()
    await waitForApp(chikaPage)
    const after = await chikaPage.evaluate(
      () => document.documentElement.classList.contains('dark'),
    )
    expect(after).toBe(!before)
    const stored = await chikaPage.evaluate(
      () => localStorage.getItem('chika_theme'),
    )
    expect(stored).toBe(after ? 'dark' : 'light')
  })

  // ── Visual baselines for both modes ────────────────────────────────

  test('visual: dark mode app shell', async ({ chikaPage }) => {
    await setTheme(chikaPage, 'dark')
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.waitForTimeout(300)
    await expect(chikaPage).toHaveScreenshot('app-shell-dark.png', {
      mask: [chikaPage.locator(
        '.conn-indicator, [class*=elapsed], [class*=pulse]',
      )],
      maxDiffPixelRatio: 0.02,
    })
  })

  test('visual: light mode app shell', async ({ chikaPage }) => {
    await setTheme(chikaPage, 'light')
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.waitForTimeout(300)
    await expect(chikaPage).toHaveScreenshot('app-shell-light.png', {
      mask: [chikaPage.locator(
        '.conn-indicator, [class*=elapsed], [class*=pulse]',
      )],
      maxDiffPixelRatio: 0.02,
    })
  })
})

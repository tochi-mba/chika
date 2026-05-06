// Render the chika trefoil mark to PNGs at 16/32/48/128px.
// Uses Playwright (already in extension/devDependencies).
//
//   cd extension
//   node icons/_render.mjs
//
// Writes icon16.png / icon32.png / icon48.png / icon128.png next to
// this file. Idempotent — re-run after design changes to refresh.
import { chromium } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname  = path.dirname(__filename)
const RENDER_HTML = `file://${path.resolve(__dirname, '_render.html')}`

const SIZES = [16, 32, 48, 128]

const browser = await chromium.launch({ headless: true })
try {
  for (const size of SIZES) {
    const ctx = await browser.newContext({
      viewport: { width: size, height: size },
      deviceScaleFactor: 2,    // hi-DPI for crisp small icons
    })
    const page = await ctx.newPage()
    await page.goto(`${RENDER_HTML}?size=${size}`)
    await page.waitForLoadState('networkidle')
    // Transparent background — capture omits the body fill.
    await page.evaluate(() => { document.documentElement.style.background = 'transparent' })
    const buf = await page.screenshot({ omitBackground: true, type: 'png' })
    const out = path.resolve(__dirname, `icon${size}.png`)
    const fs = await import('fs')
    fs.writeFileSync(out, buf)
    console.log(`wrote ${out} (${buf.length} bytes)`)
    await ctx.close()
  }
} finally {
  await browser.close()
}

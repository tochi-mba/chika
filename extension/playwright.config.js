// @ts-check
import { defineConfig } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname  = path.dirname(__filename)

/**
 * Playwright config for the Chika browser extension.
 *
 * Chrome extensions need a *persistent* browser context with
 * --load-extension pointing at the unpacked extension directory.
 * Each test fixture launches its own context (see e2e/_fixtures.js).
 *
 * Run:
 *     cd extension
 *     npm install
 *     npm run test:e2e:install   # downloads chromium
 *     npm run test:e2e
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,                  // extensions share global state
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,                            // one extension, one browser
  // CI uses three reporters in parallel:
  //   - github   : annotates the PR with inline pass/fail markers
  //   - list     : streams progress in the action logs
  //   - html     : writes ``playwright-report/`` so the upload-artifact
  //                step has something to upload (without it the artifact
  //                step warns "No files were found", and failures are
  //                un-debuggable from the Actions UI).
  reporter: process.env.CI
    ? [['github'], ['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]]
    : 'list',
  timeout: 30_000,
  expect: { timeout: 5_000 },

  use: {
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  // No webServer — the popup is loaded as chrome-extension://...
  // We stub the backend WS the same way the frontend tests do.
})

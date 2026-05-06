// Playwright config for the docs/ landing page.
//
// We serve docs/ as static files via http-server on a free port, then
// drive the page across multiple viewports. ``chromium`` covers
// desktop + iPhone + iPad emulations via project configs below.

import { defineConfig, devices } from '@playwright/test';

const PORT = process.env.DOCS_PORT || 5174;
const BASE_URL = process.env.BASE_URL || `http://localhost:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI
    ? [['github'], ['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]]
    : 'list',

  expect: {
    // Pixel-diff snapshots have to tolerate sub-pixel rendering noise
    // across runs. 0.06 is the same threshold the frontend e2e uses.
    toHaveScreenshot: { maxDiffPixelRatio: 0.06 },
  },

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    // Reduce flakiness: wait for DOMContentLoaded by default,
    // individual tests `await page.waitForLoadState('networkidle')`
    // when they need GitHub API mock to complete.
    navigationTimeout: 15_000,
  },

  // Spin up http-server before tests, tear it down after.
  webServer: {
    command: `npx http-server . -p ${PORT} -s --cors`,
    port: Number(PORT),
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },

  // Each project = a viewport / device emulation. Names are stable
  // because ``--project=desktop`` selects only desktop tests when
  // iterating locally.
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'iphone-se',
      use: { ...devices['iPhone SE'] },
    },
    {
      name: 'iphone-14',
      use: { ...devices['iPhone 14'] },
    },
    {
      name: 'iphone-14-landscape',
      use: { ...devices['iPhone 14 landscape'] },
    },
    {
      name: 'pixel-7',
      use: { ...devices['Pixel 7'] },
    },
    {
      name: 'ipad-mini',
      use: { ...devices['iPad Mini'] },
    },
    {
      name: 'ipad-pro',
      use: { ...devices['iPad Pro 11'] },
    },
  ],
});

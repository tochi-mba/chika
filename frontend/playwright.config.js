// @ts-check
import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright config for the Chika frontend.
 *
 * Tests live under ./e2e/. The webServer block boots `vite preview`
 * against the built dist on port 4173 (Vite's preview default), so a
 * full `npm run build && npm run test:e2e` produces deterministic runs.
 *
 * For dev iteration: `npm run dev` in one terminal, then
 * `BASE_URL=http://localhost:5173 npx playwright test --ui`.
 */
export default defineConfig({
  // Two-rooted spec discovery:
  //   - ``frontend/e2e/*.spec.js``: cross-cutting Vue-app tests
  //   - ``../chika/skills/*/tests/*.spec.js``: skill-owned e2e
  //     specs (per the drop-in skill contract — a skill's full
  //     test surface lives inside its folder).
  testDir: '..',
  testMatch: [
    'frontend/e2e/**/*.spec.js',
    'chika/skills/*/tests/**/*.spec.js',
  ],
  // The CLI/extension/backend-stub layers parallelise fine, but the Vue
  // frontend tests share one vite preview server and a global
  // window.__chikaMockWS — running them concurrently produces phantom
  // failures from cross-context state bleed. Pin to one worker.
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
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
  expect: {
    timeout: 5_000,
    // Per-platform baselines — Chromium renders fonts and antialiasing
    // differently on Linux vs macOS vs Windows, so the canonical
    // baselines are committed under ``-chromium-linux.png`` (the CI
    // platform). Devs on macOS / Windows generate their baselines via
    // the .github/workflows/update-snapshots.yml workflow:
    // push code, add the ``update-snapshots`` label, and CI commits
    // freshly-generated Linux baselines back to the PR branch. This is
    // the pattern Microsoft / Vercel / Next.js use for the same problem
    // — devs don't have to install Docker locally.
    toHaveScreenshot: {
      // Default Playwright path template includes platform suffix.
    },
  },

  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: process.env.BASE_URL
    ? undefined
    : {
        command: 'npm run preview -- --host 127.0.0.1 --port 4173',
        url: 'http://127.0.0.1:4173',
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
})

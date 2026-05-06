// docs/landing.spec.js
//
// Cross-viewport tests for docs/index.html. Run via Playwright with
// each project in playwright.config.js (desktop, iPhone SE, iPhone 14,
// iPhone 14 landscape, Pixel 7, iPad Mini, iPad Pro).
//
// What we verify across all viewports:
//   - the brand mark renders (no broken SVG)
//   - the hero title is visible above the fold
//   - the primary download CTA is visible AND big enough to tap
//   - no horizontal scroll (max scrollWidth ≤ viewport width + 1px)
//   - all key sections (#install, #update, #uninstall) are reachable
//
// What we verify only on desktop (some assertions are noisier on
// narrow viewports — text wraps differently, etc.):
//   - GitHub Releases mock pre-populates the install cards correctly
//   - OS detection re-targets the primary CTA
//   - Reduced-motion mode disables the trefoil animations

import { test, expect } from '@playwright/test';

// Stub the GitHub API so tests don't burn through the rate limit.
async function mockGithubReleases(page) {
  await page.route('**/api.github.com/repos/**/releases/latest', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        tag_name: 'v2.0.5',
        name: 'Chika v2.0.5',
        assets: [
          {
            name: 'chika-setup-2.0.5.exe',
            browser_download_url: 'https://example.com/chika-setup-2.0.5.exe',
          },
          {
            name: 'Chika-2.0.5.pkg',
            browser_download_url: 'https://example.com/Chika-2.0.5.pkg',
          },
          {
            name: 'chika_2.0.5_all.deb',
            browser_download_url: 'https://example.com/chika_2.0.5_all.deb',
          },
          {
            name: 'chika-2.0.5-py3-none-any.whl',
            browser_download_url: 'https://example.com/chika-2.0.5-py3-none-any.whl',
          },
        ],
      }),
    });
  });
}

// ── Cross-viewport: render + layout ─────────────────────────────────

test.beforeEach(async ({ page }) => {
  await mockGithubReleases(page);
});

test('brand mark renders without broken SVG', async ({ page }) => {
  await page.goto('/');
  // The header brand SVG must be present + visible. Uses the
  // `.brand-mark` class on the SVG inside the sticky `.header`.
  const mark = page.locator('.header .brand-mark').first();
  await expect(mark).toBeVisible();
  const paths = await mark.locator('path').count();
  expect(paths).toBeGreaterThanOrEqual(3);
});

test('hero title is visible above the fold', async ({ page }) => {
  await page.goto('/');
  const title = page.locator('h1.hero-title');
  await expect(title).toBeVisible();
  // Above-fold check: bounding box top < viewport height.
  const box = await title.boundingBox();
  const vp = page.viewportSize();
  expect(box).not.toBeNull();
  expect(box.y).toBeLessThan(vp.height);
});

test('primary download CTA is visible and tap-target-sized', async ({ page }) => {
  await page.goto('/');
  const cta = page.locator('#primary-download');
  await expect(cta).toBeVisible();
  const box = await cta.boundingBox();
  expect(box).not.toBeNull();
  // Apple HIG minimum tap target is 44x44 pt. We allow 44x44 px as a
  // proxy (close enough on actual devices; Playwright is using CSS px
  // through the device emulation transform).
  expect(box.height).toBeGreaterThanOrEqual(44);
  expect(box.width).toBeGreaterThanOrEqual(44);
});

test('no horizontal scroll on any viewport', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('domcontentloaded');
  // Allow ±1 CSS px for sub-pixel rounding noise across browsers.
  const scroll = await page.evaluate(() => ({
    sw: document.documentElement.scrollWidth,
    cw: document.documentElement.clientWidth,
  }));
  expect(scroll.sw).toBeLessThanOrEqual(scroll.cw + 1);
});

test('install / update / uninstall sections are present', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#install')).toBeAttached();
  await expect(page.locator('#update')).toBeAttached();
  await expect(page.locator('#uninstall')).toBeAttached();
});

test('install cards expose the right OS', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.install-card[data-os="windows"]')).toBeAttached();
  await expect(page.locator('.install-card[data-os="macos"]')).toBeAttached();
  await expect(page.locator('.install-card[data-os="linux"]')).toBeAttached();
  // The remaining three cards (universal curl, source, PyPI) carry copy
  // snippets — verified via the .code-block locator below since they
  // don't have an OS data-attribute.
  await expect(page.locator('.install-card .code-block')).toHaveCount(3);
});

test('settings-can-change-anytime reassurance is visible', async ({ page }) => {
  await page.goto('/');
  const reassure = page.locator('.hero-reassurance').first();
  await expect(reassure).toContainText(/anytime|any time/i);
});

test('terminal mock renders with state row', async ({ page }) => {
  await page.goto('/');
  const stateRow = page.locator('.term-state').first();
  await expect(stateRow).toBeAttached();
  // Verb should cycle through the predefined list.
  const verb = page.locator('#state-verb');
  await expect(verb).toBeAttached();
});

// ── GitHub mock + OS detection (desktop only — text comparisons
//    on narrow viewports get noisy with truncation) ─────────────────

test('install cards populate from GitHub Releases', async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name !== 'desktop',
    'desktop-only — narrow viewports truncate the asset names',
  );
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await expect(page.locator('#windows-asset')).toContainText('chika-setup-2.0.5.exe');
  await expect(page.locator('#macos-asset')).toContainText('Chika-2.0.5.pkg');
  await expect(page.locator('#linux-deb-asset')).toContainText('chika_2.0.5_all.deb');
});

test('primary CTA updates href when GitHub returns assets', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop-only assertion');
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  // The CTA should now point at one of our mocked download URLs
  // (the exact one depends on the chromium UA; we just check it
  // moved off the generic releases page).
  const href = await page.locator('#primary-download').getAttribute('href');
  expect(href).toMatch(/example\.com\/(chika-setup-|Chika-|chika_)/);
});

test('reduced-motion mode disables animations', async ({ page, browser }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop-only — animation introspection');
  const context = await browser.newContext({ reducedMotion: 'reduce' });
  const p = await context.newPage();
  await mockGithubReleases(p);
  await p.goto('/');
  // The .leaf-1 path's animation should have been neutered.
  const dur = await p.evaluate(() => {
    const el = document.querySelector('.leaf.leaf-1');
    return el ? getComputedStyle(el).animationDuration : '';
  });
  // ``0s`` or ``0.01ms`` (CSS clamp). Different browsers serialise
  // the same clamped value three different ways:
  //   - "0s"        (Firefox)
  //   - "0.01ms"    (some Chromium versions, literal CSS string)
  //   - "1e-05s"    (Chromium 119+, getComputedStyle normalises ms→s
  //                  in scientific notation when the value is sub-ms)
  // All three mean "animation is effectively off."
  expect(dur).toMatch(/(^0s$|0\.01ms|^1e-05s$)/);
  await context.close();
});

// ── Visual snapshot per viewport ─────────────────────────────────────
//
// These run last because snapshots are noisier than the assertions
// above. We only snapshot the hero (above-the-fold) — the rest of
// the page involves animations + GitHub-mock async that make the
// full-page snapshot brittle. The hero is the marketing value.

test('hero matches snapshot', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('domcontentloaded');
  // Freeze keyframes for determinism.
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-duration: 0s !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0s !important;
      }
    `,
  });
  // The hero is now a <section class="hero">, not a <header>.
  // First-run baselines are generated by ``npm run test:e2e:update-snapshots``;
  // a design refresh means existing baselines are stale and must be
  // regenerated before this test passes locally.
  await page.locator('section.hero').waitFor();
  await expect(page.locator('section.hero')).toHaveScreenshot('hero.png');
});


// ── Layout structure assertions ─────────────────────────────────────


test('header is fixed and shows on scroll', async ({ page }) => {
  await page.goto('/');
  const header = page.locator('header.header');
  await expect(header).toBeVisible();
  // Scroll down — header should still be visible (position: fixed).
  await page.evaluate(() => window.scrollTo(0, 800));
  await expect(header).toBeVisible();
});


test('all six feature cards render', async ({ page }) => {
  await page.goto('/');
  const cards = page.locator('.feature-card');
  await expect(cards).toHaveCount(6);
});


test('all six install paths render', async ({ page }) => {
  await page.goto('/');
  const cards = page.locator('.install-card');
  await expect(cards).toHaveCount(6);  // win/mac/linux + universal/source/pypi
});


test('terminal mock state row has triangles + verb', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.term-triangles .tri')).toHaveCount(3);
  await expect(page.locator('#state-verb')).toBeAttached();
  await expect(page.locator('#state-elapsed')).toBeAttached();
});


test('copy buttons have aria-labels and target ids', async ({ page }) => {
  await page.goto('/');
  const buttons = page.locator('.copy-btn');
  const count = await buttons.count();
  expect(count).toBeGreaterThanOrEqual(2);   // at least curl + git source
  for (let i = 0; i < count; i++) {
    const btn = buttons.nth(i);
    await expect(btn).toHaveAttribute('aria-label', /.+/);
    await expect(btn).toHaveAttribute('data-copy-target', /.+/);
  }
});


test('mobile nav toggle exists on touch viewports', async ({ page }, testInfo) => {
  test.skip(
    !['iphone-se', 'iphone-14', 'pixel-7'].includes(testInfo.project.name),
    'mobile-only — toggle is hidden on desktop',
  );
  await page.goto('/');
  // Toggle should be visible at narrow viewports
  await expect(page.locator('#nav-toggle')).toBeVisible();
});


test('sections are reachable via anchor scroll', async ({ page }) => {
  await page.goto('/#install');
  await page.waitForLoadState('domcontentloaded');
  const installSection = page.locator('#install');
  await expect(installSection).toBeInViewport();
});


// ── Visual regression: per-section snapshot at every viewport ─────
//
// Each snapshot lives at:
//   docs/e2e/__snapshots__/<spec>/<test-name>-<project>.png
//
// First run: ``npm run test:e2e:update-snapshots`` writes baselines.
// Subsequent runs: pixel-diff with maxDiffPixelRatio (set in
// playwright.config.js to 0.06) tolerates sub-pixel rendering noise.
// A real visual regression (broken layout, missing element) fails CI.
//
// We freeze animations and stub the GitHub API in beforeEach so the
// snapshot is deterministic across runs.


async function freezeAnimations(page) {
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-duration: 0s !important;
        animation-iteration-count: 1 !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
      }
    `,
  });
}


test('snapshot — header (sticky top bar)', async ({ page }) => {
  await page.goto('/');
  await freezeAnimations(page);
  await page.locator('header.header').waitFor();
  await expect(page.locator('header.header')).toHaveScreenshot('header.png');
});


test('snapshot — terminal showcase', async ({ page }) => {
  await page.goto('/');
  await freezeAnimations(page);
  await page.locator('.terminal').waitFor();
  await expect(page.locator('.terminal')).toHaveScreenshot('terminal.png');
});


test('snapshot — features section', async ({ page }) => {
  await page.goto('/#features');
  await freezeAnimations(page);
  await page.locator('section.features').waitFor();
  await expect(page.locator('section.features')).toHaveScreenshot('features.png');
});


test('snapshot — install section', async ({ page }) => {
  await page.goto('/#install');
  await freezeAnimations(page);
  await page.waitForLoadState('networkidle');
  await page.locator('section.install').waitFor();
  await expect(page.locator('section.install')).toHaveScreenshot('install.png');
});


test('snapshot — update section', async ({ page }) => {
  await page.goto('/#update');
  await freezeAnimations(page);
  await page.locator('section.update').waitFor();
  await expect(page.locator('section.update')).toHaveScreenshot('update.png');
});


test('snapshot — uninstall section', async ({ page }) => {
  await page.goto('/#uninstall');
  await freezeAnimations(page);
  await page.locator('section.uninstall').waitFor();
  await expect(page.locator('section.uninstall')).toHaveScreenshot('uninstall.png');
});


test('snapshot — footer', async ({ page }) => {
  await page.goto('/');
  await freezeAnimations(page);
  // Scroll to bottom so the footer is rendered/laid out
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.locator('footer.footer').waitFor();
  await expect(page.locator('footer.footer')).toHaveScreenshot('footer.png');
});


test('snapshot — full page', async ({ page }, testInfo) => {
  // Full-page snapshots are big and most useful at mobile widths
  // (verify the entire single-column flow). We only run them on
  // narrower projects — desktop full-page is a baselines-and-diffs
  // headache.
  test.skip(
    !['iphone-14', 'iphone-se', 'pixel-7', 'ipad-mini'].includes(testInfo.project.name),
    'full-page snapshots only run on mobile/tablet projects',
  );
  await page.goto('/');
  await freezeAnimations(page);
  await page.waitForLoadState('networkidle');
  await expect(page).toHaveScreenshot('fullpage.png', { fullPage: true });
});


test('snapshot — install card (windows clickable)', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop-only for legibility');
  await page.goto('/#install');
  await freezeAnimations(page);
  await page.waitForLoadState('networkidle');
  const card = page.locator('.install-card[data-os="windows"]');
  await card.waitFor();
  await expect(card).toHaveScreenshot('card-windows.png');
});


test('snapshot — install card (curl shell snippet)', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop-only for legibility');
  await page.goto('/#install');
  await freezeAnimations(page);
  // The 4th install-card is the universal Linux curl snippet
  const card = page.locator('.install-card').nth(3);
  await card.waitFor();
  await expect(card).toHaveScreenshot('card-curl.png');
});


test('snapshot — mobile nav open', async ({ page }, testInfo) => {
  test.skip(
    !['iphone-14', 'iphone-se', 'pixel-7'].includes(testInfo.project.name),
    'mobile-only — toggle is hidden on desktop',
  );
  await page.goto('/');
  await freezeAnimations(page);
  await page.locator('#nav-toggle').click();
  // Wait for the menu transition — we already froze it to 0s, so it's
  // effectively immediate; this is just defence against any inherited
  // visibility delay.
  await page.locator('#nav-links.active').waitFor();
  await expect(page).toHaveScreenshot('mobile-nav-open.png', { fullPage: false });
});


test('snapshot — primary CTA hover state', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'hover only meaningful on pointer-fine');
  await page.goto('/');
  await freezeAnimations(page);
  const cta = page.locator('#primary-download');
  await cta.hover();
  await expect(cta).toHaveScreenshot('cta-hover.png');
});


test('snapshot — features grid (with hover on first card)', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'hover only meaningful on pointer-fine');
  await page.goto('/#features');
  await freezeAnimations(page);
  const card = page.locator('.feature-card').first();
  await card.hover();
  // Snapshot the whole grid so we can see the hover lifted the card
  await expect(page.locator('.features-grid')).toHaveScreenshot('features-with-hover.png');
});

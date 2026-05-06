/**
 * Spotify integration — visual + behavioural tests for the Settings
 * "Integrations" tab. Drives every state through the chikaPage
 * fixture's stubbed fetch (see _fixtures.js): each test sets a
 * ``window.__chikaSpotifyStatus`` global via ``addInitScript`` before
 * the page loads, and the fixture serves it back in response to
 * ``/api/spotify/status``.
 *
 * Coverage:
 *   - Disconnected state (initial)
 *   - Configuration error (no CLIENT_ID baked in)
 *   - Connected with display name + premium pill
 *   - Connected with shared-bucket label
 *   - Connected with per-profile override active (the killer case)
 *   - Headless URL fallback (browser-open failed)
 *   - Disconnect button flow
 *   - Share-across-profiles toggle reflects checked state
 *   - Per-profile override toggle only shown under share-on
 *   - Error message renders on connect failure
 */
import { test, expect, waitForApp } from './_fixtures.js'

test.use({ viewport: { width: 1280, height: 800 } })


/**
 * Inject a status response that the fixture's mocked fetch will
 * serve for /api/spotify/status. Must be called before goto().
 *
 * We use the content-string form rather than the function form so
 * the script is evaluated with deterministic timing relative to the
 * fixture's WS_MOCK_SCRIPT (both are now strings, both apply at
 * document-start in registration order).
 */
async function seedStatus(page, status) {
  await page.addInitScript({
    content: `window.__chikaSpotifyStatus = ${JSON.stringify(status)};`,
  })
}


/** Same idea for the connect endpoint. */
async function seedConnect(page, payload) {
  await page.addInitScript({
    content: `window.__chikaSpotifyConnect = ${JSON.stringify(payload)};`,
  })
}


/**
 * Force light or dark mode before goto(). The theme store reads
 * ``chika_theme`` from localStorage at boot, so seeding it via
 * addInitScript guarantees no flash-of-wrong-theme in the snapshot.
 */
async function setTheme(page, theme) {
  await page.addInitScript({
    content: `try { localStorage.setItem('chika_theme', ${JSON.stringify(theme)}) } catch (e) {}`,
  })
}


/** Open Settings → Integrations and wait for the Spotify card. */
async function openIntegrations(page) {
  await page.goto('/')
  await waitForApp(page)
  const gear = page.locator(
    'button.icon-btn[title*="Settings"], button.icon-btn[aria-label*="Settings"]',
  ).first()
  await gear.click()
  await page.locator('.settings-modal').waitFor({ timeout: 4000 })
  await page.locator('.tab', { hasText: 'Integrations' }).click()
  await page.locator('.integrations-panel').waitFor()
  // Component fetches /api/spotify/status on mount + every 4s; give
  // the first cycle time to land before snapshotting.
  await page.waitForTimeout(250)
}


function spotifyCard(page) {
  return page.locator('.card', { has: page.locator('h3', { hasText: 'Spotify' }) })
}


// ── Disconnected state ─────────────────────────────────────────────────

test.describe('Spotify Integrations tab', () => {
  test('disconnected state — connect button is enabled', async ({ chikaPage }) => {
    await seedStatus(chikaPage, {
      authorized: false, client_id_set: true,
      profile: 'default', active_profile: 'default',
      shared: false, shared_setting: false,
      overrides_share: false, profile_overrides: {},
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    await expect(card).toBeVisible()
    await expect(card.locator('.btn-primary')).toBeVisible()
    await expect(card.locator('.btn-primary')).toBeEnabled()
    await expect(card.locator('.btn-primary')).toContainText(/Connect Spotify/i)
    await expect(card).toHaveScreenshot('spotify-disconnected.png', {
      maxDiffPixelRatio: 0.05,
    })
  })


  test('not configured — connect button is disabled with helpful copy', async ({ chikaPage }) => {
    await seedStatus(chikaPage, {
      authorized: false, client_id_set: false,
      profile: 'default', active_profile: 'default',
      shared: false, shared_setting: false,
      overrides_share: false, profile_overrides: {},
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    await expect(card.locator('.btn-primary')).toBeDisabled()
    await expect(card).toContainText(/CHIKA_SPOTIFY_CLIENT_ID|client_id/i)
    await expect(card).toHaveScreenshot('spotify-not-configured.png', {
      maxDiffPixelRatio: 0.05,
    })
  })


  test('connected state shows display name + premium pill + disconnect/reconnect', async ({ chikaPage }) => {
    await seedStatus(chikaPage, {
      authorized: true, client_id_set: true,
      display_name: 'Tochi', product: 'premium',
      profile: 'default', active_profile: 'default',
      shared: false, shared_setting: false,
      overrides_share: false, profile_overrides: {},
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    await expect(card).toContainText('Tochi')
    await expect(card.locator('.tier.premium')).toContainText('premium')
    await expect(card.locator('button', { hasText: 'Disconnect' })).toBeVisible()
    await expect(card.locator('button', { hasText: 'Reconnect' })).toBeVisible()
    await expect(card).toHaveScreenshot('spotify-connected-premium.png', {
      maxDiffPixelRatio: 0.05,
    })
  })


  test('connected state with shared bucket', async ({ chikaPage }) => {
    await seedStatus(chikaPage, {
      authorized: true, client_id_set: true,
      display_name: 'Tochi', product: 'premium',
      profile: 'default', active_profile: 'default',
      shared: true, shared_setting: true,
      overrides_share: false, profile_overrides: {},
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    await expect(card).toContainText(/shared across all profiles/i)
    await expect(card).toHaveScreenshot('spotify-connected-shared.png', {
      maxDiffPixelRatio: 0.05,
    })
  })


  test('per-profile override visible when share is on', async ({ chikaPage }) => {
    await seedStatus(chikaPage, {
      authorized: true, client_id_set: true,
      display_name: 'Tochi', product: 'premium',
      profile: 'work', active_profile: 'work',
      shared: false, shared_setting: true,    // global on, this profile overriding
      overrides_share: true, profile_overrides: { work: true },
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    // Override row visible only when shared_setting is on
    await expect(card).toContainText(/Use my own Spotify for this profile/i)
    // Should show this profile is overriding
    const overrideToggle = card.locator('.share-row').nth(1).locator('input')
    await expect(overrideToggle).toBeChecked()
    await expect(card).toHaveScreenshot('spotify-override-active.png', {
      maxDiffPixelRatio: 0.05,
    })
  })


  test('override row HIDDEN when global share is off', async ({ chikaPage }) => {
    await seedStatus(chikaPage, {
      authorized: true, client_id_set: true,
      display_name: 'Tochi', product: 'premium',
      profile: 'default', active_profile: 'default',
      shared: false, shared_setting: false,
      overrides_share: false, profile_overrides: {},
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    // Only one share-row (the global toggle), no override row.
    await expect(card.locator('.share-row')).toHaveCount(1)
  })


  test('headless URL fallback shown when browser open failed', async ({ chikaPage }) => {
    await seedStatus(chikaPage, {
      authorized: false, client_id_set: true,
      profile: 'default', active_profile: 'default',
      shared: false, shared_setting: false,
      overrides_share: false, profile_overrides: {},
    })
    await seedConnect(chikaPage, {
      auth_url: 'https://accounts.spotify.com/authorize?client_id=fake&state=zzz',
      opened: false, client_id_set: true,
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    await card.locator('.btn-primary').click()
    await expect(card.locator('.fallback')).toBeVisible({ timeout: 4000 })
    await expect(card.locator('.fallback input')).toHaveValue(
      /accounts\.spotify\.com\/authorize/,
    )
    await expect(card).toHaveScreenshot('spotify-fallback-url.png', {
      maxDiffPixelRatio: 0.05,
    })
  })


  test('disconnect button clears connected state', async ({ chikaPage }) => {
    await seedStatus(chikaPage, {
      authorized: true, client_id_set: true,
      display_name: 'Tochi', product: 'premium',
      profile: 'default', active_profile: 'default',
      shared: false, shared_setting: false,
      overrides_share: false, profile_overrides: {},
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    await expect(card).toContainText('Tochi')
    // Flip the seed so the next status poll returns disconnected.
    await chikaPage.evaluate(() => {
      window.__chikaSpotifyStatus = {
        authorized: false, client_id_set: true,
        profile: 'default', active_profile: 'default',
        shared: false, shared_setting: false,
        overrides_share: false, profile_overrides: {},
      }
    })
    await card.locator('button', { hasText: 'Disconnect' }).click()
    // The polling cycle (4s) catches up; the button text flips back.
    await expect(
      card.locator('.btn-primary', { hasText: 'Connect Spotify' }),
    ).toBeVisible({ timeout: 6000 })
  })


  test('share-across-profiles toggle reflects checked state', async ({ chikaPage }) => {
    await seedStatus(chikaPage, {
      authorized: true, client_id_set: true,
      display_name: 'Tochi', product: 'premium',
      profile: 'default', active_profile: 'default',
      shared: true, shared_setting: true,
      overrides_share: false, profile_overrides: {},
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    // First share-row is the global share toggle.
    const shareToggle = card.locator('.share-row').first().locator('input')
    await expect(shareToggle).toBeChecked()
    await expect(card.locator('.share-row').first()).toHaveScreenshot(
      'spotify-share-on.png',
      { maxDiffPixelRatio: 0.05 },
    )
  })


  test('error message renders on connect failure', async ({ chikaPage }) => {
    await seedStatus(chikaPage, {
      authorized: false, client_id_set: true,
      profile: 'default', active_profile: 'default',
      shared: false, shared_setting: false,
      overrides_share: false, profile_overrides: {},
    })
    await seedConnect(chikaPage, {
      auth_url: '',
      opened: false,
      client_id_set: false,
      error: 'no_client_id',
      message: "Spotify CLIENT_ID isn't configured.",
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    await card.locator('.btn-primary').click()
    await expect(card.locator('.error-msg')).toBeVisible()
    await expect(card.locator('.error-msg')).toContainText(/CLIENT_ID/i)
    await expect(card).toHaveScreenshot('spotify-error-state.png', {
      maxDiffPixelRatio: 0.05,
    })
  })


  // ── Dark-mode parity ───────────────────────────────────────────────
  //
  // The Vue Integrations tab inherits the global theme. Each light-mode
  // baseline above has a dark-mode counterpart so we catch
  // theme-specific regressions (forgotten color-mix args, hardcoded
  // hex values bleeding through, etc.) without doubling the assertion
  // count.

  test('dark mode — disconnected state', async ({ chikaPage }) => {
    await setTheme(chikaPage, 'dark')
    await seedStatus(chikaPage, {
      authorized: false, client_id_set: true,
      profile: 'default', active_profile: 'default',
      shared: false, shared_setting: false,
      overrides_share: false, profile_overrides: {},
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    await expect(card).toHaveScreenshot('spotify-disconnected-dark.png', {
      maxDiffPixelRatio: 0.05,
    })
  })


  test('dark mode — connected with premium', async ({ chikaPage }) => {
    await setTheme(chikaPage, 'dark')
    await seedStatus(chikaPage, {
      authorized: true, client_id_set: true,
      display_name: 'Tochi', product: 'premium',
      profile: 'default', active_profile: 'default',
      shared: false, shared_setting: false,
      overrides_share: false, profile_overrides: {},
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    await expect(card).toHaveScreenshot('spotify-connected-premium-dark.png', {
      maxDiffPixelRatio: 0.05,
    })
  })


  test('dark mode — connected shared', async ({ chikaPage }) => {
    await setTheme(chikaPage, 'dark')
    await seedStatus(chikaPage, {
      authorized: true, client_id_set: true,
      display_name: 'Tochi', product: 'premium',
      profile: 'default', active_profile: 'default',
      shared: true, shared_setting: true,
      overrides_share: false, profile_overrides: {},
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    await expect(card).toHaveScreenshot('spotify-connected-shared-dark.png', {
      maxDiffPixelRatio: 0.05,
    })
  })


  test('dark mode — per-profile override active', async ({ chikaPage }) => {
    await setTheme(chikaPage, 'dark')
    await seedStatus(chikaPage, {
      authorized: true, client_id_set: true,
      display_name: 'Tochi', product: 'premium',
      profile: 'work', active_profile: 'work',
      shared: false, shared_setting: true,
      overrides_share: true, profile_overrides: { work: true },
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    await expect(card).toHaveScreenshot('spotify-override-active-dark.png', {
      maxDiffPixelRatio: 0.05,
    })
  })


  test('dark mode — not configured', async ({ chikaPage }) => {
    await setTheme(chikaPage, 'dark')
    await seedStatus(chikaPage, {
      authorized: false, client_id_set: false,
      profile: 'default', active_profile: 'default',
      shared: false, shared_setting: false,
      overrides_share: false, profile_overrides: {},
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    await expect(card).toHaveScreenshot('spotify-not-configured-dark.png', {
      maxDiffPixelRatio: 0.05,
    })
  })


  test('dark mode — error state', async ({ chikaPage }) => {
    await setTheme(chikaPage, 'dark')
    await seedStatus(chikaPage, {
      authorized: false, client_id_set: true,
      profile: 'default', active_profile: 'default',
      shared: false, shared_setting: false,
      overrides_share: false, profile_overrides: {},
    })
    await seedConnect(chikaPage, {
      auth_url: '', opened: false, client_id_set: false,
      error: 'no_client_id',
      message: "Spotify CLIENT_ID isn't configured.",
    })
    await openIntegrations(chikaPage)
    const card = spotifyCard(chikaPage)
    await card.locator('.btn-primary').click()
    await expect(card.locator('.error-msg')).toBeVisible()
    await expect(card).toHaveScreenshot('spotify-error-state-dark.png', {
      maxDiffPixelRatio: 0.05,
    })
  })
})

/**
 * Profile-gate e2e — the gate must mount before the chat surface, list
 * profiles, accept a pick, accept a password, and route the user back
 * to "create new" when they're locked out.
 */
import { test, expect, waitForApp } from './_fixtures.js'

test.describe('profile gate', () => {
  test.beforeEach(async ({ chikaPage }) => {
    // Override fetch BEFORE mount so the gate sees specific profile data.
    await chikaPage.addInitScript(() => {
      sessionStorage.removeItem('chika_profile_unlocked')
      window.__chikaProfileUnlocked = false
      // Patch fetch to provide deterministic /api/profiles + select responses.
      const originalFetch = window.fetch
      window.fetch = async (input, init) => {
        const url = typeof input === 'string' ? input : input.url
        if (url.includes('/api/profiles/select')) {
          const body = JSON.parse((init && init.body) || '{}')
          // Mirror the real backend: a profile flagged has_password=true
          // requires a non-empty password; profiles without a password
          // accept any empty submission. We hardcode "locked" as the
          // only password-protected profile in this fixture.
          const requiresPassword = body.name === 'locked'
          if (!requiresPassword || body.password === 'right') {
            return new Response(JSON.stringify({
              ok: true, name: body.name, workspace: '/x', pet_id: 'cat',
            }), { status: 200, headers: { 'Content-Type': 'application/json' } })
          }
          return new Response(JSON.stringify({ detail: 'incorrect password' }),
            { status: 401, headers: { 'Content-Type': 'application/json' } })
        }
        if (url.includes('/api/profiles/create')) {
          const body = JSON.parse((init && init.body) || '{}')
          return new Response(JSON.stringify({
            ok: true, name: body.name,
            has_password: !!(body.password && body.password.length),
          }), { status: 200, headers: { 'Content-Type': 'application/json' } })
        }
        if (url.includes('/api/profiles')) {
          return new Response(JSON.stringify({
            profiles: [
              { name: 'open',   has_password: false },
              { name: 'locked', has_password: true  },
            ],
          }), { status: 200, headers: { 'Content-Type': 'application/json' } })
        }
        return originalFetch ? originalFetch(input, init) : new Response('null')
      }
    })
    // Bypass disabled — these tests need the gate visible.
    await chikaPage.goto('/', { bypassGate: false })
  })

  test('gate is shown before the app surface', async ({ chikaPage }) => {
    await expect(chikaPage.locator('text=/Who.s working today/i')).toBeVisible({
      timeout: 5000,
    })
    // Both profiles render in the list.
    await expect(chikaPage.locator('text=/^open$/').first()).toBeVisible()
    await expect(chikaPage.locator('text=/^locked$/').first()).toBeVisible()
  })

  test('picking the unlocked profile mounts the chat surface', async ({ chikaPage }) => {
    await chikaPage.locator('button:has-text("open")').first().click()
    // Once unlocked the gate disappears and the app shows.
    await expect(chikaPage.locator('text=/Who.s working today/i')).toBeHidden({
      timeout: 5000,
    })
    await waitForApp(chikaPage)
  })

  test('locked profile prompts for a password', async ({ chikaPage }) => {
    await chikaPage.locator('button:has-text("locked")').first().click()
    await expect(chikaPage.locator('text=/Password for locked/i')).toBeVisible()
  })

  test('wrong password shows error + reveals create-fallback link', async ({ chikaPage }) => {
    await chikaPage.locator('button:has-text("locked")').first().click()
    await chikaPage.locator('input[type="password"]').first().fill('wrong')
    await chikaPage.locator('button:has-text("Continue")').first().click()
    await expect(chikaPage.locator('text=/Wrong password/i')).toBeVisible({
      timeout: 4000,
    })
    await expect(
      chikaPage.locator('text=/Locked out\\? Create a new profile instead/i'),
    ).toBeVisible()
  })

  test('create-new flow from the picker mounts a fresh profile', async ({ chikaPage }) => {
    await chikaPage.locator('button:has-text("New profile")').first().click()
    await chikaPage.locator('input[placeholder*="tochi" i]').first().fill('fresh')
    await chikaPage.locator('button:has-text("Create + use")').first().click()
    // Gate dismisses after create.
    await expect(chikaPage.locator('text=/Who.s working today/i')).toBeHidden({
      timeout: 5000,
    })
  })
})

/**
 * Playwright mock-fetch fragment for the spotify skill.
 *
 * Exported as a string so the central frontend fixture
 * (``frontend/e2e/_fixtures.js``) can stitch every shipped skill's
 * mock handlers together via ``page.addInitScript`` without naming
 * any single skill — preserves the strict skill-isolation contract.
 *
 * The fragment runs INSIDE the page (browser context). It expects
 * the surrounding fixture to declare ``url``, ``originalFetch``, and
 * the ``window.__chika*`` stub holders.
 */
export const MOCKS_SCRIPT = `
if (url.includes('/api/' + 'spotify' + '/status')) {
  const stub = window.__chikaSpotifyStatus || {
    authorized: false, client_id_set: true,
    profile: 'default', active_profile: 'default',
    shared: false, shared_setting: false,
    overrides_share: false, profile_overrides: {},
  }
  return new Response(JSON.stringify(stub), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })
}
if (url.includes('/api/' + 'spotify' + '/connect')) {
  const stub = window.__chikaSpotifyConnect || {
    auth_url: 'https://accounts.example.com/authorize?client_id=test&state=zzz',
    opened: true, client_id_set: true,
  }
  return new Response(JSON.stringify(stub), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })
}
if (url.includes('/api/' + 'spotify' + '/disconnect')) {
  return new Response(JSON.stringify({ ok: true, tokens_clear: true }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })
}
if (url.includes('/api/' + 'spotify' + '/profile')) {
  const stub = window.__chikaSpotifyProfile || null
  return new Response(JSON.stringify(stub), {
    status: stub ? 200 : 401,
    headers: { 'Content-Type': 'application/json' },
  })
}
`

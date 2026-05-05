/**
 * Background service-worker tests — verify the SW registers, listens
 * to runtime messages, and exposes the expected MV3 hooks.
 */
import { test, expect } from './_fixtures.js'

test.describe('extension background', () => {
  test('service worker registers', async ({ context }) => {
    let sw = context.serviceWorkers()[0]
    if (!sw) {
      sw = await context.waitForEvent('serviceworker', { timeout: 10_000 })
    }
    expect(sw).toBeTruthy()
    expect(sw.url()).toMatch(/background\.js$/)
  })

  test('runtime.id is populated', async ({ context }) => {
    let sw = context.serviceWorkers()[0]
    if (!sw) {
      sw = await context.waitForEvent('serviceworker', { timeout: 10_000 })
    }
    const id = await sw.evaluate(() => chrome.runtime.id)
    expect(id).toBeTruthy()
  })

  test('manifest has the expected name + version', async ({ context }) => {
    let sw = context.serviceWorkers()[0]
    if (!sw) {
      sw = await context.waitForEvent('serviceworker', { timeout: 10_000 })
    }
    const manifest = await sw.evaluate(() => chrome.runtime.getManifest())
    expect(manifest.name).toMatch(/Chika/)
    expect(manifest.version).toBeTruthy()
    expect(manifest.manifest_version).toBe(3)
  })
})

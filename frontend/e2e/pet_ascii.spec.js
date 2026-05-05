/**
 * Pet ASCII rendering — the desktop pet should render the same multi-line
 * ASCII frames the CLI uses, cycling through them per state.
 */
import { test, expect, waitForApp, pushSequence } from './_fixtures.js'

test.describe('pet ASCII rendering', () => {
  test.beforeEach(async ({ chikaPage }) => {
    await chikaPage.addInitScript(() => {
      sessionStorage.setItem('chika_profile_unlocked', '1')
      // Override the pets fetch to ship a deterministic frame table.
      const originalFetch = window.fetch
      window.fetch = async (input, init) => {
        const url = typeof input === 'string' ? input : input.url
        if (url.includes('/api/pets') && !url.includes('/profile/')) {
          return new Response(JSON.stringify({
            default: 'cat',
            pets: [
              {
                id: 'cat',
                name: 'Mochi the Cat',
                accent: '#e0b35c',
                emoji: '🐱',
                frames: {
                  idle: ['IDLE-FRAME-A', 'IDLE-FRAME-B'],
                  working: ['WORK-FRAME-A', 'WORK-FRAME-B'],
                  celebrate: ['YAY-FRAME'],
                  sad: ['SAD-FRAME'],
                },
                quotes: {},
              },
            ],
          }), { status: 200, headers: { 'Content-Type': 'application/json' } })
        }
        return originalFetch ? originalFetch(input, init)
                             : new Response('{}', { status: 200 })
      }
    })
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
  })

  test('idle frame renders inside the pet companion', async ({ chikaPage }) => {
    await expect(chikaPage.locator('.pet-ascii').first()).toBeVisible({
      timeout: 4000,
    })
    const text = await chikaPage.locator('.pet-ascii').first().textContent()
    expect(text).toMatch(/IDLE-FRAME-[AB]/)
  })

  test('switching state swaps to the working frames', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
    ])
    // Wait for the state machine to react.
    await expect.poll(async () => {
      const t = await chikaPage.locator('.pet-ascii').first().textContent()
      return t || ''
    }, { timeout: 4000 }).toMatch(/WORK-FRAME-[AB]/)
  })

  test('celebrate state lands on workflow_done', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'workflow_done', workflow_id: 'wf', variables: {} },
    ])
    await expect.poll(async () => {
      const t = await chikaPage.locator('.pet-ascii').first().textContent()
      return t || ''
    }, { timeout: 4000 }).toMatch(/YAY-FRAME/)
  })

  test('error event flips to sad frame', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'error', message: 'boom' },
    ])
    await expect.poll(async () => {
      const t = await chikaPage.locator('.pet-ascii').first().textContent()
      return t || ''
    }, { timeout: 4000 }).toMatch(/SAD-FRAME/)
  })
})

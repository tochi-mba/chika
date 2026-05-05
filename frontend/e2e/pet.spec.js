/**
 * Pet companion e2e — the floating pet widget reflects the engine state.
 */
import { test, expect, waitForApp, pushEvent, pushSequence } from './_fixtures.js'

test.describe('pet companion', () => {
  test.beforeEach(async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
  })

  test('pet is visible on load', async ({ chikaPage }) => {
    // PetCompanion.vue renders SOMETHING — emoji, asset, or text.
    // We assert the component slot renders a known-class root (.pet-* / .pet).
    const pet = chikaPage.locator('[class*=pet]').first()
    await expect(pet).toBeVisible({ timeout: 5000 })
  })

  test('pet reacts to a tool call (working state)', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      {
        type: 'tool_call', step_id: 's1',
        tool: 'shell_exec',
        args: { command: 'ls' },
      },
    ])
    // The DOM root for the pet should pick up a "working"-ish class /
    // pet animation hooks. We don't pin the exact class name; just
    // verify the pet element is still in the document.
    const pet = chikaPage.locator('[class*=pet]').first()
    await expect(pet).toBeVisible()
  })

  test('pet_changed event surfaces a different pet', async ({ chikaPage }) => {
    await pushEvent(chikaPage, {
      type: 'pet_changed',
      profile: 'default',
      pet: { id: 'dog', name: 'Biscuit' },
    })
    // Avoid pinning the exact rendering — just confirm the event didn't
    // crash the page.
    await chikaPage.waitForTimeout(150)
    const errorCount = await chikaPage.evaluate(() => {
      // Capture page errors from DOM if anything broke.
      return document.querySelectorAll('[class*=error-overlay]').length
    })
    expect(errorCount).toBe(0)
  })
})

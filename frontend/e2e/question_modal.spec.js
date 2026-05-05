/**
 * Question modal e2e — `ask_user` produces a multi-choice modal
 * fired through the WS as a ``user_question`` event. The user picks
 * one (or many) options + optional notes, and the answer ships back
 * as ``user_question_response`` with ``choice``, ``choice_index``,
 * ``choices`` (multi), ``choice_indices`` (multi), and ``notes``.
 *
 * The modal is mounted via Teleport at document root, so locators
 * search the whole page rather than scoping to the chat surface.
 *
 * Coverage:
 *   - Modal renders with the question text and every option label.
 *   - Submit/Confirm is disabled until at least one option is picked.
 *   - Single-select dispatches user_question_response with the picked
 *     choice + index.
 *   - Multi-select dispatches the choices array.
 *   - Notes textarea content rides along on the response.
 */
import { test, expect, waitForApp, pushEvent, sentMessages } from './_fixtures.js'


function singleQuestion() {
  return {
    type:        'user_question',
    request_id:  'q-1',
    question:    'Which framework do you want?',
    header:      'STACK',
    multi_select: false,
    options: [
      { label: 'React',   description: 'Most popular' },
      { label: 'Vue',     description: 'Lighter weight' },
      { label: 'Svelte',  description: 'Compile-time' },
    ],
  }
}


function multiQuestion() {
  return {
    type:         'user_question',
    request_id:   'q-2',
    question:     'Which features should we include?',
    multi_select: true,
    options: [
      { label: 'Auth' },
      { label: 'Search' },
      { label: 'Chat' },
    ],
  }
}


test.describe('question modal', () => {
  test.beforeEach(async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
  })


  test('renders question text and every option label', async ({ chikaPage }) => {
    await pushEvent(chikaPage, singleQuestion())
    await expect(
      chikaPage.locator('text=/Which framework do you want\\?/i'),
    ).toBeVisible({ timeout: 4000 })
    for (const label of ['React', 'Vue', 'Svelte']) {
      await expect(chikaPage.locator(`text=/^${label}$/`).first()).toBeVisible()
    }
  })


  test('confirm is disabled until an option is selected', async ({ chikaPage }) => {
    await pushEvent(chikaPage, singleQuestion())
    const confirm = chikaPage
      .locator('button:has-text("Confirm"), button:has-text("Submit")')
      .first()
    await expect(confirm).toBeVisible({ timeout: 3000 })
    await expect(confirm).toBeDisabled()

    await chikaPage.locator('button.option:has-text("Vue")').first().click()
    await expect(confirm).toBeEnabled()
  })


  test('single-select: confirming dispatches the chosen option', async ({ chikaPage }) => {
    await pushEvent(chikaPage, singleQuestion())
    await chikaPage.locator('button.option:has-text("Svelte")').first().click()
    await chikaPage.locator('button:has-text("Confirm")').first().click()

    const msgs = await sentMessages(chikaPage)
    const answer = msgs.find(m => m && m.type === 'user_question_response')
    expect(answer).toBeTruthy()
    expect(answer.choice).toBe('Svelte')
    expect(answer.choice_index).toBe(2)
  })


  test('multi-select: multiple options stay toggled and fire one answer', async ({ chikaPage }) => {
    await pushEvent(chikaPage, multiQuestion())
    await chikaPage.locator('button.option:has-text("Auth")').first().click()
    await chikaPage.locator('button.option:has-text("Chat")').first().click()
    // Toggle off + back on to confirm multi-select picks survive extra clicks.
    await chikaPage.locator('button.option:has-text("Auth")').first().click()
    await chikaPage.locator('button.option:has-text("Auth")').first().click()

    const submit = chikaPage.locator('button:has-text("Submit")').first()
    await expect(submit).toBeEnabled()
    await submit.click()

    const msgs = await sentMessages(chikaPage)
    const answer = msgs.find(m => m && m.type === 'user_question_response')
    expect(answer).toBeTruthy()
    expect(Array.isArray(answer.choices)).toBe(true)
    expect(answer.choices).toContain('Auth')
    expect(answer.choices).toContain('Chat')
  })


  test('notes textarea content rides along on the payload', async ({ chikaPage }) => {
    await pushEvent(chikaPage, singleQuestion())
    await chikaPage.locator('button.option:has-text("React")').first().click()
    // Scope to the modal — the page also has a chat-input textarea.
    await chikaPage.locator('.modal textarea.notes').first().fill('also turn on TypeScript')
    await chikaPage.locator('button:has-text("Confirm")').first().click()

    const msgs = await sentMessages(chikaPage)
    const answer = msgs.find(m => m && m.type === 'user_question_response')
    expect(answer).toBeTruthy()
    expect(answer.notes).toBe('also turn on TypeScript')
  })
})

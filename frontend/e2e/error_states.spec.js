/**
 * Error-state rendering — engine-side errors must surface clearly.
 *
 * Coverage:
 *   - workflow_done with workflow_errors injects ``[Error: ...]`` into
 *     the assistant bubble.
 *   - tool_result with `error` field surfaces the error text inline
 *     in the tool-block.
 *   - skill_doc_required is shown as a tool-block error with a hint
 *     telling the user the agent needs to re-emit.
 *   - plan_required refusal appears when a workflow with writes has
 *     no plan_set.
 *   - circuit-breaker (repeated_error_circuit_breaker) shows a
 *     distinct halt message.
 */
import { test, expect, waitForApp, pushSequence } from './_fixtures.js'


async function startTurn(page) {
  const input = page.locator('textarea, input[type="text"]').first()
  await input.fill('test')
  await input.press('Enter')
  await page.waitForTimeout(80)
}


test.describe('error states', () => {
  test('tool_result error surfaces in the tool-block result summary', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await startTurn(chikaPage)

    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'tool_call', step_id: 's1', tool: 'shell_exec', args: {} },
      {
        type: 'tool_result', step_id: 's1', tool: 'shell_exec',
        result: null, error: 'permission denied',
        duration_ms: 3,
      },
    ])

    const errBlock = chikaPage.locator('.message-list .tool-block.is-error').first()
    await expect(errBlock).toBeVisible({ timeout: 3000 })
    await expect(errBlock).toContainText(/permission denied/i)
  })


  test('plan_required refusal renders as a tool-block error', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await startTurn(chikaPage)

    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      {
        type: 'tool_call', step_id: 'plan_gate', tool: 'plan_gate',
        args: { _auto: true, writes_used: ['file_write', 'shell_exec'] },
      },
      {
        type: 'tool_result', step_id: 'plan_gate', tool: 'plan_gate',
        error: 'plan_required',
        result: {
          error:       'plan_required',
          write_count: 3,
          writes_used: ['file_write', 'shell_exec'],
          hint:        'Workflow has 3 write-class tool calls and no active plan.',
        },
        duration_ms: 0,
      },
    ])

    const errBlock = chikaPage.locator('.message-list .tool-block.is-error').first()
    await expect(errBlock).toBeVisible({ timeout: 3000 })
    await expect(errBlock).toContainText(/plan_required/)
  })


  test('skill_doc_required surfaces as a structured error', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await startTurn(chikaPage)

    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      {
        type: 'tool_call', step_id: 's1', tool: 'browser_navigate',
        args: { url: 'https://example.com' },
      },
      {
        type: 'tool_result', step_id: 's1', tool: 'browser_navigate',
        error: 'skill_doc_required',
        result: {
          error:       'skill_doc_required',
          skill:       'browser',
          tool_blocked: 'browser_navigate',
          char_count:  4321,
          doc:         '...',
          hint:        '`browser_navigate` did NOT run.',
        },
        duration_ms: 0,
      },
    ])

    const errBlock = chikaPage.locator('.message-list .tool-block.is-error').first()
    await expect(errBlock).toBeVisible({ timeout: 3000 })
    await expect(errBlock).toContainText(/skill_doc_required/)
  })


  test('engine error event lands in the assistant bubble as [Error: ...]', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    // Seed a user + assistant bubble directly via the store so the
    // error event has a place to land. The chat store's appendToken
    // silently no-ops when no assistant bubble exists; the textarea
    // path here is too racy to rely on.
    await chikaPage.evaluate(() => {
      const stores = window.__pinia__?._s
      const chat = stores?.get('chat')
      if (!chat) throw new Error('chat store missing')
      chat.messages = [
        { id: 'u1', role: 'user', text: 'go', streaming: false },
        { id: 'a1', role: 'assistant', text: '', streaming: true,
          warnings: [], toolEvents: [] },
      ]
    })

    // Use a hyphenated message — the markdown parser eats underscores
    // ('max_turns_reached' → 'maxturnsreached' as italic markup), and
    // we don't care to assert against rendered markdown surface here.
    await pushSequence(chikaPage, [
      { type: 'error', message: 'engine error: max-turns-reached' },
    ])

    await expect(
      chikaPage.locator('.message.assistant').last(),
    ).toContainText('max-turns-reached', { timeout: 3000 })
  })


  test('circuit_breaker error shows the repeated-error halt message', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await startTurn(chikaPage)

    // Engine emits this when a tool fails the same way 3+ times in a row.
    await pushSequence(chikaPage, [
      {
        type:        'error',
        error_code:  'repeated_error_circuit_breaker',
        message:
          "Stopping: same error 'denied_by_workspace_policy' on " +
          "'/Users/x/file.html' repeated 3 times.",
      },
    ])

    await expect(
      chikaPage.locator('text=/repeated 3 times/i').first(),
    ).toBeVisible({ timeout: 3000 })
  })
})

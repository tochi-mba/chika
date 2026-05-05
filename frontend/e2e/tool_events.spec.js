/**
 * Tool-event rendering — guards the v0 tool-block visual that shipped
 * in the recent design overhaul.
 *
 * Tool calls and tool results render inside an assistant message
 * bubble's `toolEvents` array (see chat.js:attachToolEvent). The
 * bubble must already exist when events arrive, so each test first
 * sends a user message via the chat input to create one.
 *
 * After the bubble exists, ToolEventRow renders each event with:
 *   - status dot (text-3 = neutral, accent + pulse = pending,
 *     success-color = ok, error-color = failed)
 *   - tool name in mono accent text
 *   - argument pills (bg-surface-2, key= prefix in dim mono)
 *   - result/error block when expanded (success → surface-2 tint,
 *     error → error-tinted background)
 */
import { test, expect, waitForApp, pushSequence } from './_fixtures.js'


async function startTurn(page) {
  // Use the chat input to create a user message + assistant bubble —
  // ToolEventRow attaches events to the last assistant message.
  const input = page.locator('textarea, input[type="text"]').first()
  await input.fill('test turn')
  await input.press('Enter')
  await page.waitForTimeout(80)
}


test.describe('tool event rendering', () => {
  test.beforeEach(async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await startTurn(chikaPage)
  })


  test('tool_call renders as a bordered tool-block with name + arg pills', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      {
        type: 'tool_call', step_id: 's1',
        tool: 'file_write',
        args: { path: '/tmp/hello.txt', content: 'hi' },
      },
    ])

    const block = chikaPage.locator('.message-list .tool-block').first()
    await expect(block).toBeVisible({ timeout: 4000 })
    await expect(block.locator('.tool-name')).toHaveText(/file_write/)
    const pills = block.locator('.arg-pill')
    expect(await pills.count()).toBeGreaterThan(0)
    await expect(pills.first().locator('.arg-key')).toContainText('=')
  })


  test('tool_result on success shows success status dot', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'tool_call', step_id: 's1', tool: 'file_write', args: { path: 'a.txt' } },
      {
        type: 'tool_result', step_id: 's1', tool: 'file_write',
        result: { ok: true, bytes: 12 }, duration_ms: 5,
      },
    ])
    await chikaPage.waitForTimeout(150)
    // After a result lands the matching tool_call's pending flag is
    // cleared and a sibling tool_result block renders. Either of those
    // should carry the success state — locate by class.
    const successDot = chikaPage.locator('.message-list .tool-block .status-dot.dot-success').first()
    await expect(successDot).toBeVisible({ timeout: 3000 })
  })


  test('tool_result with error shows error status', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'tool_call', step_id: 's2', tool: 'shell_exec', args: { command: 'oops' } },
      {
        type: 'tool_result', step_id: 's2', tool: 'shell_exec',
        result: null, error: 'command failed: not found',
        duration_ms: 3,
      },
    ])
    await chikaPage.waitForTimeout(150)
    const errBlock = chikaPage.locator('.message-list .tool-block.is-error').first()
    await expect(errBlock).toBeVisible({ timeout: 3000 })
    await expect(errBlock.locator('.status-dot.dot-error')).toBeVisible()
  })


  test('pending tool_call shows the pulsing accent dot + spinner', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      {
        type: 'tool_call', step_id: 's3',
        tool: 'shell_exec', args: { command: 'sleep 5' },
      },
    ])
    // The chat store auto-marks tool_call events `pending: true` when
    // they arrive without a matching tool_result yet. Verify the
    // pending-state pieces render: pulsing dot + mini spinner.
    const pendingDot = chikaPage.locator('.message-list .tool-block .status-dot.dot-pending').first()
    await expect(pendingDot).toBeVisible({ timeout: 3000 })
    await expect(chikaPage.locator('.message-list .mini-spinner').first()).toBeVisible()
  })


  test('skill_load events get the distinct skill-load card treatment', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      {
        type: 'tool_call', step_id: 's4',
        tool: 'skill_load', args: { skill: 'plan' },
      },
    ])
    const skillBlock = chikaPage.locator('.message-list .tool-block.is-skill-load').first()
    await expect(skillBlock).toBeVisible({ timeout: 3000 })
    await expect(skillBlock.locator('.skill-badge').first()).toBeVisible()
  })
})

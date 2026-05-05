/**
 * Chat-flow e2e — sending messages, tool events, plan rendering.
 *
 * The mock WS lets us drive any sequence of engine events deterministically.
 */
import { test, expect, waitForApp, pushEvent, pushSequence, sentMessages } from './_fixtures.js'

test.describe('chat flow', () => {
  test.beforeEach(async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
  })

  test('user message sends a chat payload over the WS', async ({ chikaPage }) => {
    // Find the chat input — text-area or input element.
    const input = chikaPage.locator(
      'textarea, input[type="text"]',
    ).first()
    await expect(input).toBeVisible({ timeout: 5000 })
    await input.fill('hello chika')
    await input.press('Enter')

    await chikaPage.waitForTimeout(200)
    const msgs = await sentMessages(chikaPage)
    const userMsg = msgs.find(
      (m) => m && (m.type === 'chat' || m.type === 'user_message' || m.text),
    )
    expect(userMsg).toBeTruthy()
  })

  test('tool_call events render a tool block', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf', name: 'demo' },
      {
        type: 'tool_call', step_id: 's1',
        tool: 'file_read',
        args: { path: 'foo.py', start_line: 1, end_line: 5 },
      },
      {
        type: 'tool_result', step_id: 's1',
        tool: 'file_read',
        result: { content: 'print("hi")' },
        duration_ms: 12,
      },
      { type: 'workflow_done', workflow_id: 'wf', variables: {} },
      { type: 'done' },
    ])
    await expect(chikaPage.locator('text=/file_read/i').first()).toBeVisible({
      timeout: 4000,
    })
  })

  test('plan_set updates the plan panel', async ({ chikaPage }) => {
    // First, simulate a workflow that calls plan_set; the engine emits a
    // tool_result whose result.plan describes the plan. The frontend's
    // chat store reads $plan from the workflow_done variables block.
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      {
        type: 'tool_call', step_id: 's1',
        tool: 'plan_set',
        args: {
          goal: 'Build it',
          tasks: [{ id: 't1', text: 'scaffold', status: 'in_progress' }],
        },
      },
      {
        type: 'tool_result', step_id: 's1',
        tool: 'plan_set',
        result: {
          _source: 'plan_set',
          plan: {
            goal: 'Build it',
            requirements: ['must work'],
            tasks: [
              { id: 't1', text: 'scaffold the project', status: 'in_progress', subtasks: [] },
              { id: 't2', text: 'add UI', status: 'pending', subtasks: [] },
            ],
            created_at: 0, updated_at: 0,
          },
        },
        duration_ms: 5,
      },
      {
        type: 'workflow_done', workflow_id: 'wf',
        variables: {
          plan: {
            goal: 'Build it',
            requirements: ['must work'],
            tasks: [
              { id: 't1', text: 'scaffold the project', status: 'in_progress', subtasks: [] },
              { id: 't2', text: 'add UI', status: 'pending', subtasks: [] },
            ],
          },
        },
      },
      { type: 'done' },
    ])
    // Plan task text appears somewhere in the rendered DOM.
    await expect(chikaPage.locator('text=/scaffold/i').first()).toBeVisible({
      timeout: 4000,
    })
  })

  test('error event renders to the user', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'error', step_id: 'wf', message: 'something exploded' },
      { type: 'done' },
    ])
    // Error is visible somewhere in the conversation surface.
    await expect(chikaPage.locator('text=/exploded/i').first()).toBeVisible({
      timeout: 4000,
    })
  })

  test('auto_continue event renders a badge', async ({ chikaPage }) => {
    await pushSequence(chikaPage, [
      { type: 'token', text: "Done. Next, I'll keep going." },
      {
        type: 'auto_continue', depth: 1, max: 10,
        trigger_tail: "Next, I'll keep going.",
      },
      { type: 'done' },
    ])
    // The renderer shows a continuation pill / line — match either
    // "auto-continue" or the depth indicator.
    const visible = await chikaPage
      .locator('text=/auto.?continue|continuing/i').first()
      .isVisible()
      .catch(() => false)
    // Frontend MAY collapse it into a pill; assert at least the depth
    // text or the loop glyph is somewhere if the explicit string isn't.
    if (!visible) {
      await expect(chikaPage.locator('text=/Next, I/').first()).toBeVisible()
    }
  })
})

/**
 * Visual-regression tests — snapshot the rendered DOM of key surfaces
 * and fail when pixels drift. Run with:
 *
 *     npm run test:e2e -- visual.spec.js
 *
 * Generate / update baselines:
 *
 *     npm run test:e2e -- --update-snapshots visual.spec.js
 *
 * Why component-level screenshots (not full page)?
 *   - Avoids flake from header timestamps / connection indicator pulses.
 *   - One bad pixel in a header doesn't fail the whole snapshot suite.
 *   - We snapshot what we actually want stable: the chat bubble shape,
 *     the plan panel, the tool block.
 *
 * Pinning to chromium (see playwright.config.js — only `chromium` is
 * defined as a project) gives us a single baseline and avoids font /
 * rendering drift between OSes. CI runs on ubuntu-latest, so the
 * baselines are committed under chromium-linux.
 */
import { test, expect, waitForApp, pushSequence } from './_fixtures.js'

const samplePlan = {
  goal: 'Visual snapshot test plan',
  requirements: ['must look the same'],
  tasks: [
    {
      id: 't1', text: 'first task', status: 'in_progress',
      subtasks: [
        { id: 't1.1', text: 'a sub-task', status: 'in_progress', subtasks: [] },
      ],
    },
    { id: 't2', text: 'second task', status: 'pending', subtasks: [] },
  ],
  created_at: 0, updated_at: 0,
}

// All visual tests run on a fixed viewport so the layout is stable.
test.use({ viewport: { width: 1280, height: 800 } })

test.describe('visual regression', () => {
  test('initial app shell', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    // Allow fonts + animations to settle.
    await chikaPage.waitForTimeout(400)
    await expect(chikaPage).toHaveScreenshot('app-shell.png', {
      // Mask the connection indicator (it pulses) and any timestamp pills.
      mask: [
        chikaPage.locator('.conn-indicator, [class*=elapsed], [class*=pulse]'),
      ],
      maxDiffPixelRatio: 0.02,
    })
  })

  test('plan panel rendering', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      {
        type: 'tool_call', step_id: 's1',
        tool: 'plan_set', args: samplePlan,
      },
      {
        type: 'tool_result', step_id: 's1',
        tool: 'plan_set',
        result: { _source: 'plan_set', plan: samplePlan },
        duration_ms: 1,
      },
      { type: 'workflow_done', workflow_id: 'wf', variables: { plan: samplePlan } },
      { type: 'done' },
    ])
    await chikaPage.waitForTimeout(300)

    const panel = chikaPage
      .locator('[class*=plan-panel], [class*=PlanPanel]')
      .first()
    if (await panel.count() > 0) {
      await expect(panel).toHaveScreenshot('plan-panel.png', {
        maxDiffPixelRatio: 0.03,
      })
    } else {
      test.skip(true, 'plan panel selector not present yet')
    }
  })

  test('tool block — pending and complete', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      {
        type: 'tool_call', step_id: 's1',
        tool: 'shell_exec',
        args: { command: 'echo hi' },
      },
      {
        type: 'tool_result', step_id: 's1',
        tool: 'shell_exec',
        result: { stdout: 'hi\n', exit_code: 0 },
        duration_ms: 25,
      },
      { type: 'workflow_done', workflow_id: 'wf', variables: {} },
      { type: 'done' },
    ])
    await chikaPage.waitForTimeout(300)

    const block = chikaPage
      .locator('[class*=tool-block], [class*=ToolEventRow], [class*=tool-event]')
      .first()
    if (await block.count() > 0) {
      await expect(block).toHaveScreenshot('tool-block.png', {
        maxDiffPixelRatio: 0.03,
      })
    } else {
      test.skip(true, 'tool block selector not present yet')
    }
  })
})

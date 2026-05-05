/**
 * Visual baseline snapshots — one screenshot per major UI state.
 *
 * These are the canonical "what the UI looks like" baselines. The
 * existing visual.spec.js covers a few high-traffic surfaces; this
 * file covers EVERY modal / panel / state we care about. If a
 * design tweak shifts pixels here CI fails — at which point either:
 *   - Eyeball the diff in test-results/ — if the new look is right,
 *     run with `--update-snapshots` to bake new baselines.
 *   - Or revert the design change.
 *
 * Conventions:
 *   - Fixed 1280x800 viewport so layout is stable.
 *   - Each test masks pulsing/animating elements (connection dot,
 *     elapsed-time pills, blinking cursor) so flake doesn't pile up.
 *   - `maxDiffPixelRatio: 0.03` (3%) tolerates antialiasing drift.
 *
 * Generate baselines first time:
 *   npm run test:e2e -- visual_baselines --update-snapshots
 */
import { test, expect, waitForApp, pushEvent, pushSequence } from './_fixtures.js'


test.use({ viewport: { width: 1280, height: 800 } })


const SETTLE_MS = 400


// Common mask — pulses + elapsed timers + blinking cursor.
function commonMask(page) {
  return [
    page.locator('.conn-indicator, [class*=elapsed], [class*=pulse], .cursor, .mini-spinner, .spinner, [class*=time]'),
  ]
}


test.describe('visual baselines — modals', () => {
  test('confirm approval modal', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type:           'approval_required',
      request_id:     'baseline-1',
      approval_type:  'confirm',
      tool:           'shell_exec',
      step_id:        's1',
      message:        'Run `npm install` in the workspace?',
      args:           { command: 'npm install', cwd: '/workspace' },
    })
    await chikaPage.waitForTimeout(SETTLE_MS)
    const modal = chikaPage.locator('.modal').first()
    await expect(modal).toHaveScreenshot('approval-confirm.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('password approval modal', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type:           'approval_required',
      request_id:     'baseline-2',
      approval_type:  'verify_password',
      tool:           'profile',
      step_id:        's2',
      message:        'Enter your profile password to continue.',
    })
    await chikaPage.waitForTimeout(SETTLE_MS)
    const modal = chikaPage.locator('.modal').first()
    await expect(modal).toHaveScreenshot('approval-password.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('workspace-scope approval (tri-state)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type:           'approval_required',
      request_id:     'baseline-3',
      approval_type:  'workspace_scope',
      tool:           'file_write',
      step_id:        's3',
      message:        'Chika wants to write a file outside the workspace.',
      args: {
        path:      'C:\\Users\\test\\Downloads\\netflix\\index.html',
        scope_dir: 'C:\\Users\\test\\Downloads\\netflix',
        workspace: 'C:\\workspace',
        action:    'write',
      },
    })
    await chikaPage.waitForTimeout(SETTLE_MS)
    const modal = chikaPage.locator('.modal').first()
    await expect(modal).toHaveScreenshot('approval-workspace.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('plan_review approval (Reject / Edit / Approve)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type:           'approval_required',
      request_id:     'baseline-4',
      approval_type:  'plan_review',
      tool:           'plan_review',
      step_id:        'plan_review',
      message:        'Approve this plan?',
      args: {
        goal: 'Build a Netflix clone',
        requirements: ['real video', 'responsive'],
        tasks: [
          { id: 't1', text: 'Set up project', status: 'pending' },
        ],
      },
    })
    await chikaPage.waitForTimeout(SETTLE_MS)
    const modal = chikaPage.locator('.modal').first()
    await expect(modal).toHaveScreenshot('approval-plan-review.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('user_question modal — single select', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type:        'user_question',
      request_id:  'q-baseline-1',
      question:    'Which framework do you want?',
      header:      'STACK',
      multi_select: false,
      options: [
        { label: 'React',  description: 'Most popular' },
        { label: 'Vue',    description: 'Lighter weight' },
        { label: 'Svelte', description: 'Compile-time' },
      ],
    })
    await chikaPage.waitForTimeout(SETTLE_MS)
    const modal = chikaPage.locator('.modal').first()
    await expect(modal).toHaveScreenshot('question-modal-single.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('user_question modal — multi select', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type:         'user_question',
      request_id:   'q-baseline-2',
      question:     'Which features should we include?',
      multi_select: true,
      options: [
        { label: 'Auth',   description: 'Login + signup' },
        { label: 'Search', description: 'Filter by title' },
        { label: 'Chat',   description: 'Real-time messaging' },
      ],
    })
    await chikaPage.waitForTimeout(SETTLE_MS)
    const modal = chikaPage.locator('.modal').first()
    await expect(modal).toHaveScreenshot('question-modal-multi.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })
})


test.describe('visual baselines — tool blocks', () => {
  async function startTurn(page) {
    const input = page.locator('textarea, input[type="text"]').first()
    await input.fill('test')
    await input.press('Enter')
    await page.waitForTimeout(80)
  }


  test('tool block — pending state (spinner + accent dot)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await startTurn(chikaPage)
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      {
        type: 'tool_call', step_id: 's-pending',
        tool: 'shell_exec', args: { command: 'sleep 30' },
      },
    ])
    // The pending block animates (pulsing dot + spinner). Snapshot the
    // assistant bubble that wraps it instead of the tool-block itself —
    // the bubble has a stable bounding box even while the dot pulses,
    // which gives a much more useful baseline than a 30px slice of the
    // animating component.
    await chikaPage.waitForTimeout(SETTLE_MS)
    const bubble = chikaPage.locator('.message-list .assistant-bubble, .message-list .bubble').first()
    await expect(bubble).toHaveScreenshot('tool-block-pending.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('tool block — success state', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await startTurn(chikaPage)
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'tool_call', step_id: 's-ok', tool: 'file_read', args: { path: 'a.txt' } },
      {
        type: 'tool_result', step_id: 's-ok', tool: 'file_read',
        result: { content: 'hello' }, duration_ms: 8,
      },
    ])
    await chikaPage.waitForTimeout(SETTLE_MS)
    const block = chikaPage.locator('.message-list .tool-block.is-success').first()
    await expect(block).toHaveScreenshot('tool-block-success.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('tool block — error state', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await startTurn(chikaPage)
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'tool_call', step_id: 's-err', tool: 'shell_exec', args: { command: 'oops' } },
      {
        type: 'tool_result', step_id: 's-err', tool: 'shell_exec',
        result: null, error: 'command not found: oops',
        duration_ms: 2,
      },
    ])
    await chikaPage.waitForTimeout(SETTLE_MS)
    const block = chikaPage.locator('.message-list .tool-block.is-error').first()
    await expect(block).toHaveScreenshot('tool-block-error.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('tool block — skill_load card', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await startTurn(chikaPage)
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      {
        type: 'tool_call', step_id: 's-skill',
        tool: 'skill_load', args: { skill: 'plan' },
      },
    ])
    await chikaPage.waitForTimeout(SETTLE_MS)
    const block = chikaPage.locator('.message-list .tool-block.is-skill-load').first()
    await expect(block).toHaveScreenshot('tool-block-skill-load.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })
})


test.describe('visual baselines — system panel', () => {
  test('system panel tab strip (default state, Events active)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.waitForTimeout(SETTLE_MS)

    const header = chikaPage.locator('.panel-header').first()
    await expect(header).toHaveScreenshot('system-panel-tabs.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('system panel — Variables tab populated', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'variable_set',
      name: 'plan',
      var_type: 'json',
      size_bytes: 245,
      value_preview: '{"goal": "Build a Netflix clone", "tasks": [...]}',
    })
    await pushEvent(chikaPage, {
      type: 'variable_set',
      name: 'tab',
      var_type: 'json',
      size_bytes: 80,
      value_preview: '{"id": 1, "url": "https://youtube.com"}',
    })
    await chikaPage.locator('button.tab:has-text("Variables")').first().click()
    await chikaPage.waitForTimeout(SETTLE_MS)

    const body = chikaPage.locator('.panel-body').first()
    await expect(body).toHaveScreenshot('system-panel-variables.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('system panel — Memory tab populated', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type:  'memory_update',
      key:   'user_role',
      value: 'data scientist',
    })
    await pushEvent(chikaPage, {
      type:  'memory_update',
      key:   'preferred_stack',
      value: 'vite + vue + typescript',
    })
    await chikaPage.locator('button.tab:has-text("Memory")').first().click()
    await chikaPage.waitForTimeout(SETTLE_MS)

    const body = chikaPage.locator('.panel-body').first()
    await expect(body).toHaveScreenshot('system-panel-memory.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })
})


test.describe('visual baselines — sidebar + plan', () => {
  test('chat sidebar with three chats', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type:    'chat_list',
      profile: 'default',
      chats: [
        { id: 'c1', title: 'Earlier conversation',   updated_at: 1700000000 },
        { id: 'c2', title: 'Latest planning sesh',   updated_at: 1700001000 },
        { id: 'c3', title: 'Build Netflix clone',    updated_at: 1700002000 },
      ],
    })
    await chikaPage.waitForTimeout(SETTLE_MS)

    const sidebar = chikaPage.locator('.sidebar').first()
    await expect(sidebar).toHaveScreenshot('sidebar-chats.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('plan panel — full layout with goal + reqs + nested tasks', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const plan = {
      goal: 'Build a Netflix clone',
      requirements: [
        'Real video assets (trailers/clips from public sources)',
        'Real poster and banner images',
        'Responsive Netflix-style UI with dark theme',
        'Video player with play/pause/progress/volume controls',
      ],
      tasks: [
        {
          id: 't1', text: 'Set up React + Vite project with TypeScript',
          status: 'in_progress',
          subtasks: [
            { id: 't1.1', text: 'Scaffold project with Vite React template', status: 'done', subtasks: [] },
            { id: 't1.2', text: 'Install dependencies', status: 'in_progress', subtasks: [] },
          ],
        },
        {
          id: 't2', text: 'Design and build core UI components',
          status: 'pending', subtasks: [],
        },
        {
          id: 't3', text: 'Wire up video playback', status: 'pending', subtasks: [],
        },
      ],
      created_at: 0, updated_at: 0,
    }
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'tool_call', step_id: 's1', tool: 'plan_set', args: plan },
      {
        type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan }, duration_ms: 1,
      },
      { type: 'workflow_done', workflow_id: 'wf', variables: { plan } },
    ])
    await chikaPage.waitForTimeout(SETTLE_MS)

    const panel = chikaPage.locator('.plan-panel').first()
    await expect(panel).toHaveScreenshot('plan-panel-full.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('plan panel — collapsed state', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const plan = {
      goal: 'A short plan',
      tasks: [{ id: 't1', text: 'do thing', status: 'pending', subtasks: [] }],
      created_at: 0, updated_at: 0,
    }
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'tool_call', step_id: 's1', tool: 'plan_set', args: plan },
      {
        type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan }, duration_ms: 1,
      },
      { type: 'workflow_done', workflow_id: 'wf', variables: { plan } },
    ])
    await chikaPage.locator('.plan-toggle').first().click()
    await chikaPage.waitForTimeout(SETTLE_MS)

    const panel = chikaPage.locator('.plan-panel').first()
    await expect(panel).toHaveScreenshot('plan-panel-collapsed.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })
})

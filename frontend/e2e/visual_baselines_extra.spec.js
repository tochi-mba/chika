/**
 * Extra visual baselines — variants and edge states the main
 * visual_baselines.spec.js doesn't cover.
 *
 * Pinned snapshots for: dark mode, hover state hints, edge layouts
 * (single message, packed plan, error-heavy panels), input states,
 * password modal show/hide, plan-edit textarea visible, settings
 * tabs.
 */
import { test, expect, waitForApp, pushEvent, pushSequence } from './_fixtures.js'


test.use({ viewport: { width: 1280, height: 800 } })


const SETTLE_MS = 350


function commonMask(page) {
  return [page.locator(
    '.conn-indicator, [class*=elapsed], [class*=pulse], .cursor, .mini-spinner, .spinner, [class*=time]',
  )]
}


async function setDark(page) {
  await page.evaluate(() => {
    document.documentElement.classList.add('dark')
    localStorage.setItem('chika_theme', 'dark')
  })
  await page.waitForTimeout(80)
}


async function startTurn(page, text = 'test') {
  const input = page.locator('textarea, input[type="text"]').first()
  await input.fill(text)
  await input.press('Enter')
  await page.waitForTimeout(80)
}


test.describe('visual baselines extra — dark mode', () => {
  test('app shell — dark mode', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await setDark(chikaPage)
    await chikaPage.waitForTimeout(SETTLE_MS)
    await expect(chikaPage).toHaveScreenshot('app-shell-dark.png', {
      mask: commonMask(chikaPage),
      maxDiffPixelRatio: 0.03,
    })
  })


  test('chat input dark mode — focused', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await setDark(chikaPage)
    const input = chikaPage.locator('textarea').first()
    await input.click()
    await chikaPage.waitForTimeout(SETTLE_MS)
    const inputBox = chikaPage.locator('.input-box').first()
    await expect(inputBox).toHaveScreenshot('chat-input-dark-focused.png', {
      maxDiffPixelRatio: 0.03,
    })
  })


  test('plan panel dark mode', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await setDark(chikaPage)
    const plan = {
      goal: 'Build the demo',
      requirements: ['ships in browser', '60fps'],
      tasks: [
        { id: 't1', text: 'Set up project', status: 'in_progress', subtasks: [] },
        { id: 't2', text: 'Build UI', status: 'pending', subtasks: [] },
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
    await expect(panel).toHaveScreenshot('plan-panel-dark.png', {
      maxDiffPixelRatio: 0.03,
    })
  })


  test('approval modal dark mode (workspace tri-state)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await setDark(chikaPage)
    await pushEvent(chikaPage, {
      type:           'approval_required',
      request_id:     'ws-1',
      approval_type:  'workspace_scope',
      tool:           'file_write',
      step_id:        's1',
      message:        'Chika wants to write outside the workspace.',
      args: {
        path: 'C:\\Users\\test\\Downloads\\netflix\\index.html',
        workspace: 'C:\\workspace', action: 'write',
      },
    })
    await chikaPage.waitForTimeout(SETTLE_MS)
    const modal = chikaPage.locator('.modal').first()
    await expect(modal).toHaveScreenshot('approval-workspace-dark.png', {
      maxDiffPixelRatio: 0.03,
    })
  })


  test('question modal dark mode (multi-select)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await setDark(chikaPage)
    await pushEvent(chikaPage, {
      type:         'user_question',
      request_id:   'q-dark',
      question:     'Which features should we include?',
      multi_select: true,
      options: [
        { label: 'Auth', description: 'Login + signup' },
        { label: 'Search', description: 'Filter by title' },
        { label: 'Chat', description: 'Real-time messaging' },
      ],
    })
    await chikaPage.waitForTimeout(SETTLE_MS)
    const modal = chikaPage.locator('.modal').first()
    await expect(modal).toHaveScreenshot('question-modal-multi-dark.png', {
      maxDiffPixelRatio: 0.03,
    })
  })
})


test.describe('visual baselines extra — interaction states', () => {
  test('plan panel — collapsed with progress in header', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    // Distinct from visual_baselines.spec.js's collapsed snapshot
    // (which has a different goal). Here we set partial progress so
    // the header bar shows a non-empty fill — that's the regression
    // surface we want pinned.
    const plan = {
      goal: 'Collapsed plan with partial progress',
      tasks: [
        { id: 't1', text: 'first',  status: 'done',        subtasks: [] },
        { id: 't2', text: 'second', status: 'in_progress', subtasks: [] },
        { id: 't3', text: 'third',  status: 'pending',     subtasks: [] },
        { id: 't4', text: 'fourth', status: 'pending',     subtasks: [] },
      ],
      created_at: 0, updated_at: 0,
    }
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      {
        type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan }, duration_ms: 1,
      },
      { type: 'workflow_done', workflow_id: 'wf', variables: { plan } },
    ])
    await chikaPage.locator('.plan-toggle').first().click()
    await chikaPage.waitForTimeout(SETTLE_MS)
    const panel = chikaPage.locator('.plan-panel').first()
    await expect(panel).toHaveScreenshot('plan-panel-collapsed-progress.png', {
      maxDiffPixelRatio: 0.03,
    })
  })


  test('plan panel — edit textarea expanded', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const plan = {
      goal: 'Build something cool',
      tasks: [
        { id: 't1', text: 'first',  status: 'pending', subtasks: [] },
        { id: 't2', text: 'second', status: 'pending', subtasks: [] },
      ],
      created_at: 0, updated_at: 0,
    }
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      {
        type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan }, duration_ms: 1,
      },
      { type: 'workflow_done', workflow_id: 'wf', variables: { plan } },
    ])
    await chikaPage.locator('.plan-btn-edit').first().click()
    await chikaPage.locator('.plan-edit-input').first().fill('use TypeScript')
    await chikaPage.waitForTimeout(SETTLE_MS)
    const panel = chikaPage.locator('.plan-panel').first()
    await expect(panel).toHaveScreenshot('plan-panel-edit-mode.png', {
      maxDiffPixelRatio: 0.03,
    })
  })


  test('chat input — typing state with text', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.locator('textarea').first().fill('build me a Netflix clone')
    await chikaPage.waitForTimeout(SETTLE_MS)
    const inputBox = chikaPage.locator('.input-box').first()
    await expect(inputBox).toHaveScreenshot('chat-input-typed.png', {
      maxDiffPixelRatio: 0.03,
    })
  })


  test('question modal — option selected (single)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type:        'user_question',
      request_id:  'q-sel',
      question:    'Pick a stack',
      multi_select: false,
      options: [
        { label: 'React' },
        { label: 'Vue' },
        { label: 'Svelte' },
      ],
    })
    await chikaPage.locator('button.option:has-text("Vue")').first().click()
    await chikaPage.waitForTimeout(SETTLE_MS)
    const modal = chikaPage.locator('.modal').first()
    await expect(modal).toHaveScreenshot('question-modal-selected.png', {
      maxDiffPixelRatio: 0.03,
    })
  })


  test('question modal — multi-select with two options chosen', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type:         'user_question',
      request_id:   'q-multi',
      question:     'Which features should we include?',
      multi_select: true,
      options: [
        { label: 'Auth' },
        { label: 'Search' },
        { label: 'Chat' },
      ],
    })
    await chikaPage.locator('button.option:has-text("Auth")').first().click()
    await chikaPage.locator('button.option:has-text("Chat")').first().click()
    await chikaPage.waitForTimeout(SETTLE_MS)
    const modal = chikaPage.locator('.modal').first()
    await expect(modal).toHaveScreenshot('question-modal-multi-selected.png', {
      maxDiffPixelRatio: 0.03,
    })
  })
})


test.describe('visual baselines extra — sidebar states', () => {
  test('sidebar — empty (no chats)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'chat_list', profile: 'default', chats: [],
    })
    await chikaPage.waitForTimeout(SETTLE_MS)
    const sidebar = chikaPage.locator('.sidebar').first()
    await expect(sidebar).toHaveScreenshot('sidebar-empty.png', {
      maxDiffPixelRatio: 0.03,
    })
  })


  test('sidebar — single chat highlighted as active', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'chat_list', profile: 'default',
      chats: [
        { id: 'active', title: 'Active conversation',  updated_at: 1700001000 },
        { id: 'old',    title: 'Earlier conversation', updated_at: 1700000000 },
      ],
    })
    // Force-set the active chat id to "active".
    await chikaPage.evaluate(() => {
      const stores = window.__pinia__?._s
      if (stores) {
        const chat = stores.get('chat')
        if (chat) chat.sessionId = 'active'
      }
    })
    await chikaPage.waitForTimeout(SETTLE_MS)
    const sidebar = chikaPage.locator('.sidebar').first()
    await expect(sidebar).toHaveScreenshot('sidebar-active-chat.png', {
      maxDiffPixelRatio: 0.03,
    })
  })


  test('sidebar — many chats (5+)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'chat_list', profile: 'default',
      chats: Array.from({ length: 8 }, (_, i) => ({
        id: `chat-${i}`,
        title: `Conversation ${i + 1}: ${[
          'Planning', 'Refactor', 'Bug hunt', 'Dependency upgrade',
          'Doc writing', 'Demo prep', 'Test sweep', 'Release notes',
        ][i] || 'misc'}`,
        updated_at: 1700000000 + i * 1000,
      })),
    })
    await chikaPage.waitForTimeout(SETTLE_MS)
    const sidebar = chikaPage.locator('.sidebar').first()
    await expect(sidebar).toHaveScreenshot('sidebar-many-chats.png', {
      maxDiffPixelRatio: 0.03,
    })
  })
})


test.describe('visual baselines extra — system panel variations', () => {
  test('system panel — tab strip dark mode', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await setDark(chikaPage)
    await chikaPage.waitForTimeout(SETTLE_MS)
    const header = chikaPage.locator('.panel-header').first()
    await expect(header).toHaveScreenshot('system-panel-tabs-dark.png', {
      maxDiffPixelRatio: 0.03,
    })
  })


  test('system panel — variables tab with multiple types', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    for (const v of [
      { name: 'plan',     var_type: 'json',      size_bytes: 245, value_preview: '{"goal": "x"}' },
      { name: 'summary',  var_type: 'text',      size_bytes: 1240, value_preview: 'A summary of...' },
      { name: 'image',    var_type: 'file_path', size_bytes: 80, value_preview: '/tmp/screenshot.png' },
      { name: 'rawbytes', var_type: 'bytes',     size_bytes: 4096, value_preview: '<binary>' },
    ]) {
      await pushEvent(chikaPage, { type: 'variable_set', ...v })
    }
    await chikaPage.locator('button.tab:has-text("Variables")').first().click()
    await chikaPage.waitForTimeout(SETTLE_MS)
    const body = chikaPage.locator('.panel-body').first()
    await expect(body).toHaveScreenshot('system-panel-variables-multi.png', {
      maxDiffPixelRatio: 0.03,
    })
  })


  test('system panel — events tab populated', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf-events', name: 'sample' },
      { type: 'tool_call',   step_id: 's1', tool: 'web_search',
        args: { query: 'test' } },
      { type: 'tool_result', step_id: 's1', tool: 'web_search',
        result: { results: [] }, duration_ms: 200 },
      { type: 'tool_call',   step_id: 's2', tool: 'shell_exec',
        args: { command: 'echo hi' } },
      { type: 'tool_result', step_id: 's2', tool: 'shell_exec',
        result: { stdout: 'hi\n' }, duration_ms: 5 },
    ])
    await chikaPage.waitForTimeout(SETTLE_MS)
    const body = chikaPage.locator('.panel-body').first()
    await expect(body).toHaveScreenshot('system-panel-events-populated.png', {
      maxDiffPixelRatio: 0.03,
    })
  })
})


test.describe('visual baselines extra — tool block edge cases', () => {
  test('tool block — long arg pill values', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await startTurn(chikaPage)
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'tool_call', step_id: 's-long', tool: 'web_fetch',
        args: { url: 'https://very-long-domain-name-with-lots-of-path/segments/and/parameters?q=really+long+query' } },
      { type: 'tool_result', step_id: 's-long', tool: 'web_fetch',
        result: { status: 200, bytes: 1234 }, duration_ms: 200 },
    ])
    await chikaPage.waitForTimeout(SETTLE_MS)
    const block = chikaPage.locator('.message-list .tool-block').first()
    await expect(block).toHaveScreenshot('tool-block-long-args.png', {
      maxDiffPixelRatio: 0.03,
    })
  })


  test('tool block — many arg pills (4+)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await startTurn(chikaPage)
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'tool_call', step_id: 's-many', tool: 'browser_fill_input',
        args: {
          tab_id: 42, selector: 'input[name=email]',
          value: 'user@example.com', clear_first: true, submit: false,
        } },
    ])
    await chikaPage.waitForTimeout(SETTLE_MS)
    const block = chikaPage.locator('.message-list .tool-block').first()
    await expect(block).toHaveScreenshot('tool-block-many-args.png', {
      maxDiffPixelRatio: 0.03,
    })
  })
})

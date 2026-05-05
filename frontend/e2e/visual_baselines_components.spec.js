/**
 * Component-level visual baselines — every distinct UI piece in
 * isolation, light + dark mode where applicable.
 */
import { test, expect, waitForApp, pushEvent, pushSequence } from './_fixtures.js'


test.use({ viewport: { width: 1280, height: 800 } })


async function setDark(page, dark = true) {
  await page.evaluate((d) => {
    localStorage.setItem('chika_theme', d ? 'dark' : 'light')
    document.documentElement.classList.toggle('dark', d)
  }, dark)
  await page.waitForTimeout(50)
}


async function startTurn(page, text = 'go') {
  const input = page.locator('textarea, input[type="text"]').first()
  await input.fill(text)
  await input.press('Enter')
  await page.waitForTimeout(80)
}


test.describe('component visual baselines — message bubbles', () => {
  test('user message bubble', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.locator('textarea').first().fill('Build a Netflix clone')
    await chikaPage.locator('textarea').first().press('Enter')
    await chikaPage.waitForTimeout(300)
    const bubble = chikaPage.locator('.message-list .user-bubble, .message-list .bubble.user-bubble').first()
    await expect(bubble).toHaveScreenshot('msg-user-bubble.png', { maxDiffPixelRatio: 0.03 })
  })


  test('assistant streaming bubble (cursor visible)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await startTurn(chikaPage, 'hi')
    await pushEvent(chikaPage, { type: 'token', text: 'Hello there!' })
    await chikaPage.waitForTimeout(200)
    const bubble = chikaPage.locator('.message-list .bubble').last()
    await expect(bubble).toHaveScreenshot('msg-assistant-streaming.png', {
      mask: [chikaPage.locator('.cursor, [class*=cursor]')],
      maxDiffPixelRatio: 0.03,
    })
  })


  test('assistant message with markdown', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await startTurn(chikaPage, 'go')
    await pushSequence(chikaPage, [
      { type: 'token', text: 'Here is the **answer**:\n\n- React\n- Vue\n- Svelte\n\nUse `vite` to scaffold.' },
      { type: 'done' },
    ])
    await chikaPage.waitForTimeout(300)
    const bubble = chikaPage.locator('.message-list .bubble').last()
    await expect(bubble).toHaveScreenshot('msg-assistant-markdown.png', {
      maxDiffPixelRatio: 0.03,
    })
  })


  test('user message dark mode', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await setDark(chikaPage)
    await chikaPage.locator('textarea').first().fill('test')
    await chikaPage.locator('textarea').first().press('Enter')
    await chikaPage.waitForTimeout(200)
    const bubble = chikaPage.locator('.message-list .user-bubble, .message-list .bubble.user-bubble').first()
    await expect(bubble).toHaveScreenshot('msg-user-bubble-dark.png', { maxDiffPixelRatio: 0.03 })
  })
})


test.describe('component visual baselines — buttons', () => {
  test('primary action button (plan approve)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const plan = {
      goal: 'do thing', tasks: [{ id: 't', text: 'x', status: 'pending', subtasks: [] }],
      created_at: 0, updated_at: 0,
    }
    await pushSequence(chikaPage, [
      { type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan }, duration_ms: 1 },
      { type: 'workflow_done', workflow_id: 'wf', variables: { plan } },
    ])
    await chikaPage.waitForTimeout(200)
    const btn = chikaPage.locator('.plan-btn-accept').first()
    await expect(btn).toHaveScreenshot('btn-plan-approve.png', { maxDiffPixelRatio: 0.05 })
  })


  test('secondary edit button (plan edit)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const plan = {
      goal: 'do thing', tasks: [{ id: 't', text: 'x', status: 'pending', subtasks: [] }],
      created_at: 0, updated_at: 0,
    }
    await pushSequence(chikaPage, [
      { type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan }, duration_ms: 1 },
      { type: 'workflow_done', workflow_id: 'wf', variables: { plan } },
    ])
    await chikaPage.waitForTimeout(200)
    const btn = chikaPage.locator('.plan-btn-edit').first()
    await expect(btn).toHaveScreenshot('btn-plan-edit.png', { maxDiffPixelRatio: 0.05 })
  })


  test('reject button (plan reject)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const plan = {
      goal: 'do thing', tasks: [{ id: 't', text: 'x', status: 'pending', subtasks: [] }],
      created_at: 0, updated_at: 0,
    }
    await pushSequence(chikaPage, [
      { type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan }, duration_ms: 1 },
      { type: 'workflow_done', workflow_id: 'wf', variables: { plan } },
    ])
    await chikaPage.waitForTimeout(200)
    const btn = chikaPage.locator('.plan-btn-reject').first()
    await expect(btn).toHaveScreenshot('btn-plan-reject.png', { maxDiffPixelRatio: 0.05 })
  })
})


test.describe('component visual baselines — chat input states', () => {
  test('chat input — empty state', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const box = chikaPage.locator('.input-box').first()
    await expect(box).toHaveScreenshot('input-empty.png', { maxDiffPixelRatio: 0.03 })
  })


  test('chat input — with text (send enabled)', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.locator('textarea').first().fill('Hello world')
    const box = chikaPage.locator('.input-box').first()
    await expect(box).toHaveScreenshot('input-with-text.png', { maxDiffPixelRatio: 0.03 })
  })


  test('chat input — multi-line', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.locator('textarea').first().fill('line one\nline two\nline three\nline four')
    const box = chikaPage.locator('.input-box').first()
    await expect(box).toHaveScreenshot('input-multiline.png', { maxDiffPixelRatio: 0.03 })
  })
})


test.describe('component visual baselines — header', () => {
  test('header — default state', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const header = chikaPage.locator('.header').first()
    await expect(header).toHaveScreenshot('header-default.png', {
      mask: [chikaPage.locator('.conn-indicator')],
      maxDiffPixelRatio: 0.03,
    })
  })


  test('header — with chat title', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'chat_title', title: 'Build a Netflix clone — current chat',
    })
    await chikaPage.waitForTimeout(200)
    const header = chikaPage.locator('.header').first()
    await expect(header).toHaveScreenshot('header-with-title.png', {
      mask: [chikaPage.locator('.conn-indicator')],
      maxDiffPixelRatio: 0.03,
    })
  })


  test('header — with extension paired indicator', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, { type: 'extension_status', connected: true })
    await chikaPage.waitForTimeout(200)
    const header = chikaPage.locator('.header').first()
    await expect(header).toHaveScreenshot('header-extension-paired.png', {
      mask: [chikaPage.locator('.conn-indicator:not(.ext-indicator)')],
      maxDiffPixelRatio: 0.03,
    })
  })


  test('header — dark mode', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await setDark(chikaPage)
    const header = chikaPage.locator('.header').first()
    await expect(header).toHaveScreenshot('header-dark.png', {
      mask: [chikaPage.locator('.conn-indicator')],
      maxDiffPixelRatio: 0.03,
    })
  })
})


test.describe('component visual baselines — modals at viewport scale', () => {
  test('approval-confirm modal full viewport', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type:           'approval_required',
      request_id:     'a-vp-1',
      approval_type:  'confirm',
      tool:           'shell_exec',
      step_id:        's1',
      message:        'Run `npm install`?',
      args:           { command: 'npm install' },
    })
    await chikaPage.waitForTimeout(300)
    await expect(chikaPage).toHaveScreenshot('viewport-approval-confirm.png', {
      mask: [chikaPage.locator('.conn-indicator, .cursor')],
      maxDiffPixelRatio: 0.03,
    })
  })


  test('question modal full viewport', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'user_question', request_id: 'q-vp-1',
      question: 'Pick a stack', multi_select: false,
      options: [{ label: 'React' }, { label: 'Vue' }, { label: 'Svelte' }],
    })
    await chikaPage.waitForTimeout(300)
    await expect(chikaPage).toHaveScreenshot('viewport-question.png', {
      mask: [chikaPage.locator('.conn-indicator, .cursor')],
      maxDiffPixelRatio: 0.03,
    })
  })


  test('plan panel full viewport', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const plan = {
      goal: 'Build a Netflix clone',
      requirements: ['real video', 'responsive UI', 'works offline'],
      tasks: [
        { id: 't1', text: 'set up', status: 'in_progress', subtasks: [] },
        { id: 't2', text: 'build core', status: 'pending', subtasks: [] },
        { id: 't3', text: 'add auth', status: 'pending', subtasks: [] },
      ],
      created_at: 0, updated_at: 0,
    }
    await pushSequence(chikaPage, [
      { type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan }, duration_ms: 1 },
      { type: 'workflow_done', workflow_id: 'wf', variables: { plan } },
    ])
    await chikaPage.waitForTimeout(300)
    await expect(chikaPage).toHaveScreenshot('viewport-plan-panel.png', {
      mask: [chikaPage.locator('.conn-indicator, .cursor')],
      maxDiffPixelRatio: 0.03,
    })
  })
})


test.describe('component visual baselines — tool block matrix', () => {
  // Per-tool args differ so the rendered tool-block visibly differs
  // (different arg pills, different result summary). Otherwise the
  // duplicate-detection guard correctly flags every tool as identical.
  const TOOLS = [
    { tool: 'file_read', args: { path: 'src/main.py', start_line: 1, end_line: 30 },
      result: { content: 'def main(): pass' } },
    { tool: 'file_write', args: { path: 'out.txt', content: 'hello' },
      result: { bytes_written: 5 } },
    { tool: 'file_replace', args: { path: 'main.py', old: 'DEBUG=True', new: 'DEBUG=False' },
      result: { replacements: 1 } },
    { tool: 'shell_exec', args: { command: 'ls -la' },
      result: { stdout: 'README.md\nmain.py', exit_code: 0 } },
    { tool: 'web_search', args: { query: 'best vue ui library 2026', max_results: 5 },
      result: { count: 5 } },
    { tool: 'web_fetch', args: { url: 'https://example.com/data.json' },
      result: { status: 200, bytes: 4321 } },
    { tool: 'browser_navigate', args: { url: 'https://github.com/anthropics/claude-code' },
      result: { tab_id: 42 } },
    { tool: 'browser_click', args: { selector: 'button[type=submit]' },
      result: { clicked: true } },
    { tool: 'memory_persist', args: { name: 'user_role', body: 'data scientist' },
      result: { saved: true } },
    { tool: 'memory_recall', args: { query: 'preferred stack' },
      result: { matches: 2 } },
    { tool: 'git_status', args: {},
      result: { branch: 'main', ahead: 2, modified: ['src/x.py'] } },
    { tool: 'git_commit', args: { message: 'feat: ship demo' },
      result: { sha: 'abc1234' } },
    { tool: 'plan_update', args: { task_id: 't2', status: 'done' },
      result: { _source: 'plan_update' } },
    { tool: 'verify_url', args: { url: 'https://example.com' },
      result: { status: 200, valid: true } },
  ]
  for (const { tool, args, result } of TOOLS) {
    test(`tool block — success state for ${tool}`, async ({ chikaPage }) => {
      await chikaPage.goto('/')
      await waitForApp(chikaPage)
      // Drive the chat store directly with a pre-built assistant
      // message. The toolEvents array carries one settled tool_call
      // (pending:false) plus its tool_result so both rows render in
      // their final state. This avoids the pending→success race that
      // makes WS-driven snapshots all look identical.
      await chikaPage.evaluate(({ tool, args, result }) => {
        const stores = window.__pinia__?._s
        const chatStore = stores?.get('chat')
        if (!chatStore) throw new Error('chat store not found')
        chatStore.messages = [{
          id: 'baseline-msg',
          role: 'assistant',
          text: '',
          warnings: [],
          streaming: false,
          toolEvents: [
            { type: 'tool_call',   step_id: 's1', tool, args,
              pending: false, _ts: 0 },
            { type: 'tool_result', step_id: 's1', tool, result,
              duration_ms: 8, _ts: 0 },
          ],
        }]
      }, { tool, args, result })
      // Tool events are hidden in a collapsed `.activity` accordion
      // by default — expand it so the tool-block + arg pills show in
      // the snapshot. Without this each tool just shows "1 tool" and
      // every baseline ends up byte-identical.
      await chikaPage.locator('.message.assistant .activity-header').first().click()
      await chikaPage.waitForSelector(
        '.message-list .tool-block.is-success', { timeout: 4000 },
      )
      await chikaPage.waitForTimeout(200)
      const wrap = chikaPage.locator('.message-list .message.assistant').last()
      await expect(wrap).toHaveScreenshot(`tool-block-${tool}.png`, {
        mask: [chikaPage.locator('.cursor, [class*=elapsed]')],
        maxDiffPixelRatio: 0.05,
      })
    })
  }
})

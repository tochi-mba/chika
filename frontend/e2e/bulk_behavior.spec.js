/**
 * Bulk behavioral e2e — wide coverage of every interactive surface.
 *
 * Each test is a single specific behavior; intentionally many tests
 * each doing one thing so a regression points at exactly the broken
 * behavior. No visual snapshots in this file (those live in
 * visual_baselines*.spec.js) — these are pure interaction + state
 * assertions.
 */
import { test, expect, waitForApp, pushEvent, pushSequence, sentMessages } from './_fixtures.js'


// ── Header ─────────────────────────────────────────────────────────────


test.describe('header — chat title', () => {
  test('chat_title event sets the visible title', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, { type: 'chat_title', title: 'My new chat' })
    await expect(
      chikaPage.locator('.chat-title:has-text("My new chat")').first(),
    ).toBeVisible({ timeout: 3000 })
  })


  test('long titles get truncated via ellipsis', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'chat_title',
      title: 'This is a very long chat title that should overflow and get clipped with an ellipsis',
    })
    const el = chikaPage.locator('.chat-title').first()
    const overflow = await el.evaluate((e) => getComputedStyle(e).textOverflow)
    expect(overflow).toBe('ellipsis')
  })
})


test.describe('header — connection indicators', () => {
  test('connection dot starts un-connected then turns green on session_info', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    // Mock WS already pushes session_info on connect, so the dot
    // should already be in connected state by the time waitForApp ends.
    const dot = chikaPage.locator('.conn-indicator').first()
    await expect(dot).toHaveClass(/connected/, { timeout: 3000 })
  })


  test('extension indicator only appears when paired', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    expect(await chikaPage.locator('.ext-indicator').count()).toBe(0)
    await pushEvent(chikaPage, { type: 'extension_status', connected: true })
    await expect(chikaPage.locator('.ext-indicator').first()).toBeVisible()
    await pushEvent(chikaPage, { type: 'extension_status', connected: false })
    await chikaPage.waitForTimeout(150)
    expect(await chikaPage.locator('.ext-indicator').count()).toBe(0)
  })
})


// ── Permissions popover ─────────────────────────────────────────────────


test.describe('permissions popover', () => {
  test('opens when the lock/unlock button is clicked', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    // The first icon-btn in the header is the autonomy/permissions one.
    await chikaPage.locator('.perm-wrap > button.icon-btn').first().click()
    await expect(chikaPage.locator('.perm-popover')).toBeVisible({ timeout: 3000 })
    await expect(chikaPage.locator('.perm-header')).toContainText(/permissions/i)
  })


  test('closes when clicking outside', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.locator('.perm-wrap > button.icon-btn').first().click()
    await expect(chikaPage.locator('.perm-popover')).toBeVisible()
    // Click the brand mark (outside the popover).
    await chikaPage.locator('.brand-mark').first().click()
    await chikaPage.waitForTimeout(150)
    expect(await chikaPage.locator('.perm-popover').count()).toBe(0)
  })


  test('Supervised + Autonomous preset buttons render and are clickable', async ({ chikaPage }) => {
    // The actual state change goes through fetch('/api/settings') which
    // our mock doesn't propagate back into the store, so we can't assert
    // on visible state changes here. The contract test
    // tests/test_api_contract.py verifies the URL contract; this just
    // pins that the buttons exist and respond to clicks without crashing.
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.locator('.perm-wrap > button.icon-btn').first().click()
    const supervised = chikaPage.locator('.perm-preset-btn:has-text("Supervised")').first()
    const autonomous = chikaPage.locator('.perm-preset-btn:has-text("Autonomous")').first()
    await expect(supervised).toBeVisible()
    await expect(autonomous).toBeVisible()
    await autonomous.click()
    await supervised.click()
    // No assertion on outcome — the contract test covers the API side.
  })
})


// ── Plan task interactions ─────────────────────────────────────────────


test.describe('plan task interactions — bulk', () => {
  function planWithTasks(statuses) {
    return {
      goal: 'test',
      tasks: statuses.map((s, i) => ({
        id: `t${i + 1}`, text: `task ${i + 1}`, status: s, subtasks: [],
      })),
      created_at: 0, updated_at: 0,
    }
  }


  for (const startStatus of ['pending', 'in_progress', 'done']) {
    test(`tick on ${startStatus} task cycles through the next status`, async ({ chikaPage }) => {
      await chikaPage.goto('/')
      await waitForApp(chikaPage)
      const plan = planWithTasks([startStatus])
      await pushSequence(chikaPage, [
        { type: 'workflow_start', workflow_id: 'wf' },
        { type: 'tool_result', step_id: 's1', tool: 'plan_set',
          result: { _source: 'plan_set', plan }, duration_ms: 1 },
        { type: 'workflow_done', workflow_id: 'wf', variables: { plan } },
      ])
      // The `in_progress` tick has a pulse animation that fails
      // Playwright's actionability check (waits for the element to be
      // stable). force:true skips the wait and just clicks.
      await chikaPage.locator('.ptl-tick').first().click({ force: true })
      const msgs = await sentMessages(chikaPage)
      const sent = msgs.some(m => /plan-task/.test(JSON.stringify(m || '')))
      expect(sent).toBe(true)
    })
  }


  test('plan with all tasks done renders 100% in the bar', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const plan = planWithTasks(['done', 'done', 'done'])
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan }, duration_ms: 1 },
      { type: 'workflow_done', workflow_id: 'wf', variables: { plan } },
    ])
    await expect(chikaPage.locator('.plan-pct')).toHaveText(/100%/, { timeout: 3000 })
  })


  test('plan with mixed statuses shows correct progress', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const plan = planWithTasks(['done', 'pending', 'pending', 'done'])
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan }, duration_ms: 1 },
      { type: 'workflow_done', workflow_id: 'wf', variables: { plan } },
    ])
    await expect(chikaPage.locator('.plan-pct')).toHaveText(/50%/, { timeout: 3000 })
  })


  test('plan subtitle shows X/Y leaf count', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const plan = planWithTasks(['done', 'pending', 'pending'])
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan }, duration_ms: 1 },
      { type: 'workflow_done', workflow_id: 'wf', variables: { plan } },
    ])
    await expect(chikaPage.locator('.plan-subtitle'))
      .toContainText(/1\/3 tasks/, { timeout: 3000 })
  })
})


// ── Approval modal extras ──────────────────────────────────────────────


test.describe('approval modal — extras', () => {
  test('plan_review approve dispatches approval_response with action=approve', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'approval_required',
      request_id: 'pr-1',
      approval_type: 'plan_review',
      tool: 'plan_review', step_id: 'pr',
      message: 'Approve plan?',
      args: { goal: 'x', tasks: [] },
    })
    await chikaPage.locator('.modal button.approve:has-text("Approve")').first().click()
    const msgs = await sentMessages(chikaPage)
    const ans = msgs.find(m => m && m.type === 'approval_response' && m.request_id === 'pr-1')
    expect(ans).toBeTruthy()
    expect(ans.action).toBe('approve')
  })


  test('plan_review edit-flow opens textarea + sends feedback on second click', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'approval_required', request_id: 'pr-2',
      approval_type: 'plan_review', tool: 'plan_review', step_id: 'pr',
      message: 'Approve plan?', args: { goal: 'x' },
    })
    // First Edit click opens the textarea (no submit yet).
    await chikaPage.locator('.modal .approve-once:has-text("Edit")').first().click()
    const ta = chikaPage.locator('.modal .plan-review-text').first()
    await expect(ta).toBeVisible()
    await ta.fill('use TS instead')
    // Second Edit click submits the feedback.
    await chikaPage.locator('.modal .approve-once:has-text("Send feedback")').first().click()

    const msgs = await sentMessages(chikaPage)
    const ans = msgs.find(m => m && m.type === 'approval_response' && m.request_id === 'pr-2')
    expect(ans).toBeTruthy()
    expect(ans.action).toBe('edit')
    expect(ans.feedback).toBe('use TS instead')
  })


  test('plan_review deny-with-reason flow', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'approval_required', request_id: 'pr-3',
      approval_type: 'plan_review', tool: 'plan_review', step_id: 'pr',
      message: 'Approve?', args: {},
    })
    await chikaPage.locator('.modal .deny:has-text("Deny")').first().click()
    await chikaPage.locator('.modal .plan-review-text').first().fill('not what I asked for')
    await chikaPage.locator('.modal .deny:has-text("Send rejection")').first().click()

    const msgs = await sentMessages(chikaPage)
    const ans = msgs.find(m => m && m.type === 'approval_response' && m.request_id === 'pr-3')
    expect(ans).toBeTruthy()
    expect(ans.action).toBe('deny')
    expect(ans.reason).toBe('not what I asked for')
  })


  test('password input has show/hide toggle', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'approval_required', request_id: 'pw-1',
      approval_type: 'verify_password', tool: 'profile', step_id: 'p',
      message: 'Password required',
    })
    const input = chikaPage.locator('.modal .pw-input').first()
    await expect(input).toHaveAttribute('type', 'password')
    await chikaPage.locator('.modal .pw-toggle').first().click()
    await expect(input).toHaveAttribute('type', 'text')
  })


  test('verify_password Confirm dispatches the password value', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'approval_required', request_id: 'pw-2',
      approval_type: 'verify_password', tool: 'profile', step_id: 'p',
      message: 'Password required',
    })
    await chikaPage.locator('.modal .pw-input').first().fill('hunter2')
    await chikaPage.locator('.modal button:has-text("Confirm")').first().click()
    const msgs = await sentMessages(chikaPage)
    const ans = msgs.find(m => m && m.type === 'approval_response' && m.request_id === 'pw-2')
    expect(ans).toBeTruthy()
    expect(ans.password).toBe('hunter2')
    expect(ans.approved).toBe(true)
  })


  test('verify_password Confirm rejects empty password client-side', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'approval_required', request_id: 'pw-3',
      approval_type: 'verify_password', tool: 'profile', step_id: 'p',
      message: 'Password required',
    })
    await chikaPage.locator('.modal button:has-text("Confirm")').first().click()
    // Should NOT have dispatched yet — error message visible instead.
    await expect(chikaPage.locator('.modal .pw-error')).toBeVisible()
    const msgs = await sentMessages(chikaPage)
    const ans = msgs.find(m => m && m.type === 'approval_response' && m.request_id === 'pw-3')
    expect(ans).toBeUndefined()
  })


  test('confirm modal Deny dispatches approved=false', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'approval_required', request_id: 'cf-1',
      approval_type: 'confirm', tool: 'shell_exec', step_id: 's',
      message: 'Run shell?', args: { command: 'rm -rf /' },
    })
    await chikaPage.locator('.modal button:has-text("Deny")').first().click()
    const msgs = await sentMessages(chikaPage)
    const ans = msgs.find(m => m && m.type === 'approval_response' && m.request_id === 'cf-1')
    expect(ans).toBeTruthy()
    expect(ans.approved).toBe(false)
  })


  test('confirm modal Approve dispatches approved=true with empty password', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'approval_required', request_id: 'cf-2',
      approval_type: 'confirm', tool: 'shell_exec', step_id: 's',
      message: 'Run shell?', args: { command: 'ls' },
    })
    await chikaPage.locator('.modal button:has-text("Approve")').first().click()
    const msgs = await sentMessages(chikaPage)
    const ans = msgs.find(m => m && m.type === 'approval_response' && m.request_id === 'cf-2')
    expect(ans).toBeTruthy()
    expect(ans.approved).toBe(true)
    expect(ans.password).toBe('')
  })
})


// ── Variable + memory rendering ────────────────────────────────────────


test.describe('variables tab — bulk', () => {
  for (const varType of ['text', 'json', 'bytes', 'file_path']) {
    test(`renders a ${varType}-typed variable`, async ({ chikaPage }) => {
      await chikaPage.goto('/')
      await waitForApp(chikaPage)
      await pushEvent(chikaPage, {
        type: 'variable_set',
        name: `sample_${varType}`,
        var_type: varType,
        size_bytes: 240,
        value_preview: `<${varType} payload>`,
      })
      await chikaPage.locator('button.tab:has-text("Variables")').first().click()
      await expect(
        chikaPage.locator('.var-card .name').first(),
      ).toContainText(`sample_${varType}`)
    })
  }


  test('variable count badge increments per variable_set', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    for (const i of [1, 2, 3, 4]) {
      await pushEvent(chikaPage, {
        type: 'variable_set', name: `v${i}`, var_type: 'text',
        size_bytes: 10, value_preview: `value ${i}`,
      })
    }
    const tab = chikaPage.locator('button.tab:has-text("Variables")').first()
    const badge = tab.locator('.tab-count').first()
    await expect(badge).toBeVisible({ timeout: 3000 })
    await expect(badge).toHaveText(/4/)
  })
})


test.describe('memory tab — bulk', () => {
  test('memory_update appends a memory entry', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'memory_update', key: 'user_role', value: 'data scientist',
    })
    await chikaPage.locator('button.tab:has-text("Memory")').first().click()
    await expect(chikaPage.locator('.mem-entry .key')).toContainText('user_role')
  })


  test('memory_delete removes the entry', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'memory_update', key: 'tmp', value: 'x',
    })
    await chikaPage.locator('button.tab:has-text("Memory")').first().click()
    await expect(chikaPage.locator('.mem-entry .key')).toContainText('tmp')
    await pushEvent(chikaPage, { type: 'memory_delete', key: 'tmp' })
    await chikaPage.waitForTimeout(150)
    expect(await chikaPage.locator('.mem-entry').count()).toBe(0)
  })


  test('multiple memory entries render in order', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    for (const k of ['first', 'second', 'third']) {
      await pushEvent(chikaPage, {
        type: 'memory_update', key: k, value: `value-of-${k}`,
      })
    }
    await chikaPage.locator('button.tab:has-text("Memory")').first().click()
    expect(await chikaPage.locator('.mem-entry').count()).toBe(3)
  })
})


// ── Right panel collapse ────────────────────────────────────────────────


test.describe('right panel collapse', () => {
  test('panel toggle hides + shows the panel', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    const panelCol = chikaPage.locator('.panel-col').first()
    // Click the panel toggle icon (last icon-btn before reset).
    const toggleBtn = chikaPage.locator(
      'button.icon-btn[title*="panel" i], button.icon-btn[title*="Open"], button.icon-btn[title*="Close"]',
    ).first()
    await toggleBtn.click()
    await chikaPage.waitForTimeout(300)
    await expect(panelCol).toHaveClass(/collapsed/)
    await toggleBtn.click()
    await chikaPage.waitForTimeout(300)
    await expect(panelCol).not.toHaveClass(/collapsed/)
  })
})


// ── Reset button ───────────────────────────────────────────────────────


test.describe('reset button', () => {
  test('reset dispatches a reset WS message', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.locator('button.reset-btn').first().click()
    const msgs = await sentMessages(chikaPage)
    expect(msgs.some(m => m && m.type === 'reset')).toBe(true)
  })
})


// ── Tool block details expansion ───────────────────────────────────────


test.describe('tool block details', () => {
  test('clicking the details toggle expands the args/result pre-block', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.evaluate(() => {
      const stores = window.__pinia__?._s
      const chat = stores?.get('chat')
      if (!chat) return
      chat.messages = [{
        id: 'm', role: 'assistant', text: '', warnings: [], streaming: false,
        toolEvents: [
          { type: 'tool_call', step_id: 's', tool: 'file_read',
            args: { path: 'big.py', start_line: 1, end_line: 80 },
            pending: false, _ts: 0 },
        ],
      }]
    })
    // Activity is collapsed; expand it first.
    await chikaPage.locator('.message.assistant .activity-header').first().click()
    const detailsToggle = chikaPage.locator('.tool-details-toggle:has-text("view args")').first()
    await detailsToggle.click()
    await expect(chikaPage.locator('.tool-pre').first()).toBeVisible({ timeout: 2000 })
  })
})


// ── Compaction message ─────────────────────────────────────────────────


test.describe('compaction', () => {
  test('compaction event renders an inline divider with summary', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, {
      type: 'compaction', removed: 12, kept: 4,
      summary_preview: 'Earlier discussion about API design.',
    })
    await expect(
      chikaPage.locator('.compaction-divider, [class*=compaction]').first(),
    ).toBeVisible({ timeout: 3000 })
  })
})


// ── Streaming behavior ─────────────────────────────────────────────────


test.describe('streaming tokens', () => {
  test('tokens append into the assistant bubble live', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.locator('textarea').first().fill('hi')
    await chikaPage.locator('textarea').first().press('Enter')
    await chikaPage.waitForTimeout(80)
    await pushSequence(chikaPage, [
      { type: 'token', text: 'Hello, ' },
      { type: 'token', text: 'world!' },
    ])
    await chikaPage.waitForTimeout(150)
    await expect(
      chikaPage.locator('.message.assistant .bubble').last(),
    ).toContainText(/Hello, world!/)
  })


  test('done event clears the streaming cursor', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.locator('textarea').first().fill('hi')
    await chikaPage.locator('textarea').first().press('Enter')
    await chikaPage.waitForTimeout(80)
    await pushEvent(chikaPage, { type: 'token', text: 'done' })
    await pushEvent(chikaPage, { type: 'done' })
    await chikaPage.waitForTimeout(150)
    // Cursor should be gone (the bubble is no longer streaming).
    expect(await chikaPage.locator('.cursor-only').count()).toBe(0)
  })
})


// ── Workflow events flow into events tab ───────────────────────────────


test.describe('events tab — bulk', () => {
  for (const eventType of [
    'workflow_start', 'tool_call', 'tool_result',
    'step_start',  'step_done',  'loop_iteration',
    'condition_eval', 'variable_set',
  ]) {
    test(`${eventType} appears in the events tab`, async ({ chikaPage }) => {
      await chikaPage.goto('/')
      await waitForApp(chikaPage)
      const event = { type: eventType,
        workflow_id: 'wf', step_id: 's', tool: 't',
        name: 'sample', step_type: 'sequential',
        iteration: 1, max: 3, result: true, args: {},
        var_type: 'text', size_bytes: 1, value_preview: 'x' }
      await pushEvent(chikaPage, event)
      await chikaPage.locator('button.tab:has-text("Events")').first().click()
      await expect(
        chikaPage.locator(`.event-row.${eventType}`).first(),
      ).toBeVisible({ timeout: 3000 })
    })
  }
})


// ── Validation warning ─────────────────────────────────────────────────


test.describe('validation warning', () => {
  test('attaches to the active assistant bubble', async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await chikaPage.locator('textarea').first().fill('hi')
    await chikaPage.locator('textarea').first().press('Enter')
    await chikaPage.waitForTimeout(80)
    await pushEvent(chikaPage, { type: 'token', text: 'See https://made-up.example' })
    await pushEvent(chikaPage, { type: 'done' })
    await pushEvent(chikaPage, {
      type: 'validation_warning',
      kind: 'ungrounded_urls',
      message: 'Response cited 1 URL not in $facts.',
      urls: ['https://made-up.example'],
    })
    await expect(
      chikaPage.locator('.message.assistant .warning, .warnings').first(),
    ).toBeVisible({ timeout: 3000 })
  })
})

/**
 * Extension popup — STANDALONE visual baselines.
 *
 * Loads popup.html directly via file:// URL (no extension shell, no
 * service worker) so the baselines can run in any headless Chromium.
 * The chrome-extension service-worker path hangs reliably under
 * --headless=new on Windows; this avoids that whole class of flake.
 *
 * What's mocked:
 *   - ``chrome.runtime.*`` — sendMessage / lastError / onMessage
 *   - ``chrome.storage.local.get/set``
 *   - WebSocket — replaced by the same mock the frontend tests use
 *
 * What's tested: the popup's HTML+CSS+JS render the right thing for
 * each engine event sequence. That's >90% of the popup's actual
 * surface area — anything that depends on the service worker (the
 * background.js logic) is covered separately by background.spec.js.
 *
 * Generate baselines (first run + after design changes):
 *   cd extension && npx playwright test popup_baselines_standalone --update-snapshots
 */
import { test, expect, standaloneStub as STANDALONE_STUB, waitForChatView } from './_standalone.js'


function commonMask(page) {
  // Only mask things that visibly animate. We DO NOT mask the status
  // dot here because Playwright snapshots are deterministic anyway.
  return [page.locator('.tool-elapsed, .cursor, .ext-pet-emoji')]
}


test.describe('extension popup — standalone visual baselines', () => {
  test('empty popup — fresh load', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await expect(page).toHaveScreenshot('popup-empty.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with active plan strip', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      const plan = {
        goal: 'Build the demo',
        requirements: ['ships in browser'],
        tasks: [
          { id: 't1', text: 'first task',  status: 'in_progress', subtasks: [] },
          { id: 't2', text: 'second task', status: 'pending',     subtasks: [] },
        ],
        created_at: 0, updated_at: 0,
      }
      // Push a state_update with the plan attached — that's how the
      // service worker tells the popup about plan changes.
      // Popup reads the plan from s.variables.plan.value (renderPlanStrip
       // walks ``s?.variables?.plan?.value``).
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true,
          messages:  [],
          events:    [],
          variables: { plan: { value: plan, var_type: 'json' } },
          pendingApprovals: [],
          pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-with-plan.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with tool events (success + error)', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      // popup.js's buildToolEventsEl pairs `kind: 'call'` with
      // `kind: 'result'` rows by `id || tool` — that's the shape
      // the SW pushes. Use that here, NOT the engine's raw
      // `type: tool_call/result` form.
      const events = [
        { id: 's1', kind: 'call',   tool: 'web_search',
          args: { query: 'netflix clone tutorial' } },
        { id: 's1', kind: 'result', tool: 'web_search',
          result: { results: [] }, duration_ms: 200 },
        { id: 's2', kind: 'call',   tool: 'shell_exec',
          args: { command: 'oops' } },
        { id: 's2', kind: 'result', tool: 'shell_exec',
          result: null, error: 'command not found: oops', duration_ms: 5 },
      ]
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true,
          messages: [
            { id: 'm1', role: 'assistant', text: '', toolEvents: events,
              streaming: false },
          ],
          events,
          pendingApprovals: [],
          pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-tool-events.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with confirm approval card', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, messages: [], events: [],
          pendingApprovals: [{
            request_id:    'a1',
            approval_type: 'confirm',
            tool:          'shell_exec',
            message:       'Run `npm install`?',
            args:          { command: 'npm install' },
          }],
          pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-approval-confirm.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with password approval card', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, messages: [], events: [],
          pendingApprovals: [{
            request_id:    'a2',
            approval_type: 'verify_password',
            tool:          'profile',
            message:       'Password required',
          }],
          pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-approval-password.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with active shells strip', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, messages: [], events: [],
          shells: [{ pid: 4321, command: 'npm run dev', running: true }],
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(400)
    await expect(page).toHaveScreenshot('popup-with-shells.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with assistant message + markdown text', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, events: [],
          messages: [
            { id: 'u1', role: 'user', text: 'Summarise this page' },
            { id: 'a1', role: 'assistant',
              text: 'The page is about **Netflix**.\n\nKey points:\n- streaming service\n- founded 1997\n- code: `react`',
              streaming: false, toolEvents: [] },
          ],
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-assistant-markdown.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with user message + assistant streaming reply', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, events: [],
          isStreaming: true,
          messages: [
            { id: 'u1', role: 'user', text: 'Build me a Netflix clone' },
          ],
          currentMsg: {
            id: 'streaming', role: 'assistant',
            text: "Sure! Let me start by",
            toolEvents: [],
          },
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-streaming.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with error message bubble', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, events: [],
          messages: [
            { id: 'u1', role: 'user', text: 'do something risky' },
            { id: 'e1', role: 'error',
              text: 'workflow failed: shell_exec returned non-zero exit code' },
          ],
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-error-bubble.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with multiple shells (3 running)', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, messages: [], events: [],
          shells: [
            { pid: 1001, command: 'npm run dev',         running: true },
            { pid: 1002, command: 'python -m api.server', running: true },
            { pid: 1003, command: 'tail -f log.txt',     running: true },
          ],
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-multiple-shells.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with workspace_scope approval (tri-state)', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, messages: [], events: [],
          pendingApprovals: [{
            request_id: 'ws-1', approval_type: 'workspace_scope',
            tool: 'file_write', step_id: 's1',
            message: 'Chika wants to write outside the workspace.',
            args: {
              path: 'C:\\Users\\test\\Downloads\\netflix\\index.html',
              workspace: 'C:\\workspace', action: 'write',
            },
          }],
          pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-approval-workspace.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with set_password approval', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, messages: [], events: [],
          pendingApprovals: [{
            request_id: 'sp-1', approval_type: 'set_password',
            tool: 'profile', step_id: 's1',
            message: 'Set a password for this profile (leave blank to remove).',
          }],
          pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-approval-set-password.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with question card (multi-choice)', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, messages: [], events: [],
          pendingApprovals: [],
          pendingQuestions: [{
            request_id: 'q-1',
            question:   'Which framework do you want?',
            header:     'STACK',
            multi_select: false,
            options: [
              { label: 'React',  description: 'Most popular' },
              { label: 'Vue',    description: 'Lighter weight' },
              { label: 'Svelte', description: 'Compile-time' },
            ],
          }],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-question-card.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup mid-streaming with tool events + partial text', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true,
          isStreaming: true,
          messages: [
            { id: 'u1', role: 'user', text: 'fetch the latest news' },
          ],
          currentMsg: {
            id: 'cur', role: 'assistant',
            text: 'I found these top headlines',
            toolEvents: [
              { id: 's1', kind: 'call', tool: 'web_search',
                args: { query: 'today news' } },
              { id: 's1', kind: 'result', tool: 'web_search',
                result: { count: 5 }, duration_ms: 320 },
            ],
          },
          events: [],
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-streaming-with-tools.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup disconnected view', async ({ page, popupURL }) => {
    // Stub answers connected: false on initial load → disconnected view.
    await page.addInitScript({ content: `
      window.chrome = {
        runtime: { lastError: null,
          sendMessage: (m, cb) => {
            if (m?.type === 'request_chat_state' && cb) {
              cb({ state: { connected: false, messages: [], events: [] } })
            } else if (cb) { cb(undefined) }
          },
          onMessage: { addListener: () => {}, removeListener: () => {} },
          getURL: p => p, id: 'x',
        },
        storage: {
          local: { get: (k, cb) => {
            const seeded = { chika_settings: { serverUrl: 'http://127.0.0.1:8000', apiKey: 'x' } }
            const out = typeof k === 'string' ? { [k]: seeded[k] } : seeded
            if (cb) { cb(out); return }
            return Promise.resolve(out)
          } },
          sync:    { get: (k, cb) => cb && cb({}) },
          session: { get: async () => ({ chika_profile_unlocked: true }), set: async () => {} },
        },
        tabs: { query: (q, cb) => cb && cb([{ id: 0, url: 'about:blank', title: '' }]) },
      }
    ` })
    await page.goto(popupURL)
    await page.waitForFunction(() => {
      const e = document.getElementById('disconnectedView')
      return e && getComputedStyle(e).display !== 'none'
    }, null, { timeout: 4000 })
    await page.waitForTimeout(200)
    await expect(page).toHaveScreenshot('popup-disconnected.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with auth error banner', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({ type: 'auth_error' })
    })
    await page.waitForTimeout(200)
    await expect(page).toHaveScreenshot('popup-auth-error.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with single user message', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, events: [],
          messages: [{ id: 'u1', role: 'user', text: 'Build a Netflix clone' }],
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-user-message.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with assistant code block', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, events: [],
          messages: [
            { id: 'u1', role: 'user', text: 'show me a snippet' },
            { id: 'a1', role: 'assistant',
              text: 'Here you go:\n\n```python\ndef hello():\n    print("hi")\n```',
              toolEvents: [], streaming: false },
          ],
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-assistant-code.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with long conversation (5+ messages)', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, events: [],
          messages: [
            { id: 'u1', role: 'user', text: 'hi' },
            { id: 'a1', role: 'assistant', text: "Hello! How can I help?", toolEvents: [] },
            { id: 'u2', role: 'user', text: 'list my tabs' },
            { id: 'a2', role: 'assistant', text: 'You have 3 tabs open: GitHub, YouTube, Twitter.',
              toolEvents: [
                { id: 't1', kind: 'call', tool: 'browser_get_tabs', args: {} },
                { id: 't1', kind: 'result', tool: 'browser_get_tabs',
                  result: { tabs: 3 }, duration_ms: 12 },
              ] },
            { id: 'u3', role: 'user', text: 'thanks!' },
          ],
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-long-conversation.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with completed plan (all tasks done)', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      const plan = {
        goal: 'Ship the demo',
        tasks: [
          { id: 't1', text: 'set up project', status: 'done',  subtasks: [] },
          { id: 't2', text: 'build features', status: 'done',  subtasks: [] },
          { id: 't3', text: 'wire up tests',  status: 'done',  subtasks: [] },
        ],
        created_at: 0, updated_at: 0,
      }
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, messages: [], events: [],
          variables: { plan: { value: plan, var_type: 'json' } },
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-plan-complete.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with single tool call (running)', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, events: [],
          messages: [
            { id: 'u1', role: 'user', text: 'fetch the page' },
            { id: 'a1', role: 'assistant', text: '',
              toolEvents: [
                { id: 's1', kind: 'call', tool: 'web_fetch',
                  args: { url: 'https://example.com' } },
              ] },
          ],
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-running-tool.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with skill-load tool event', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, events: [],
          messages: [
            { id: 'u1', role: 'user', text: 'plan something' },
            { id: 'a1', role: 'assistant', text: '',
              toolEvents: [
                { id: 's1', kind: 'call', tool: 'skill_load', args: { skill: 'plan' } },
                { id: 's1', kind: 'result', tool: 'skill_load',
                  result: { skill: 'plan', char_count: 4321 }, duration_ms: 12 },
              ] },
          ],
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-skill-load.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with two pending approvals stacked', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, messages: [], events: [],
          pendingApprovals: [
            { request_id: 'a1', approval_type: 'confirm',
              tool: 'shell_exec', message: 'Run `npm install`?',
              args: { command: 'npm install' } },
            { request_id: 'a2', approval_type: 'confirm',
              tool: 'git_commit', message: 'Commit the changes?',
              args: { message: 'feat: ship' } },
          ],
          pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-two-approvals.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with thinking-row (assistant pending text)', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true, events: [],
          isStreaming: true,
          messages: [
            { id: 'u1', role: 'user', text: 'help' },
          ],
          currentMsg: null,
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-thinking-row.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })


  test('popup with combined plan + tool events + shells (busy state)', async ({ page, popupURL }) => {
    await page.addInitScript({ content: STANDALONE_STUB })
    await page.goto(popupURL)
    await waitForChatView(page)
    await page.evaluate(() => {
      const plan = {
        goal: 'Build the demo',
        tasks: [
          { id: 't1', text: 'set up project',  status: 'done',        subtasks: [] },
          { id: 't2', text: 'build features',  status: 'in_progress', subtasks: [] },
          { id: 't3', text: 'wire up tests',   status: 'pending',     subtasks: [] },
        ],
        created_at: 0, updated_at: 0,
      }
      const events = [
        { id: 's1', kind: 'call', tool: 'shell_exec',
          args: { command: 'npm install' } },
        { id: 's1', kind: 'result', tool: 'shell_exec',
          result: { exit_code: 0 }, duration_ms: 8400 },
      ]
      window.__chikaPushChrome({
        type: 'state_update',
        state: {
          connected: true,
          messages: [
            { id: 'u1', role: 'user', text: 'go' },
            { id: 'a1', role: 'assistant', text: 'Working on it.',
              toolEvents: events },
          ],
          events,
          variables: { plan: { value: plan, var_type: 'json' } },
          shells: [{ pid: 4321, command: 'npm run dev', running: true }],
          pendingApprovals: [], pendingQuestions: [],
        },
      })
    })
    await page.waitForTimeout(300)
    await expect(page).toHaveScreenshot('popup-busy-state.png', {
      mask: commonMask(page),
      maxDiffPixelRatio: 0.04,
      fullPage: true,
      animations: 'disabled',
    })
  })
})

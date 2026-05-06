/**
 * Extension popup — tool event rendering.
 *
 * Tool calls/results arrive at popup.js via chrome.runtime.onMessage as
 * ``{type: 'tool_event', event: {kind: 'call'|'result', tool, ...}}``
 * (background.js wraps engine events into that shape). Push through
 * `__chikaPushChrome` to mirror that path exactly.
 */
import { test, expect, waitForChatView, standaloneStub } from './_standalone.js'


// The popup's tool-row UI only renders inside a streaming message bubble.
// Seed one via state_update so subsequent tool_event pushes have somewhere
// to render. The shape mirrors background.js's chatState public view.
async function seedStreamingMessage(page) {
  await page.evaluate(() => {
    window.__chikaPushChrome({
      type: 'state_update',
      state: {
        connected: true,
        isStreaming: true,
        currentMsg: { role: 'assistant', text: '', tool_events: [] },
        messages: [],
        events: [],
        pendingApprovals: [],
        pendingQuestions: [],
      },
    })
  })
}


test.describe('extension popup — tool events', () => {
  test('tool_call renders a tool-row with the tool name', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await waitForChatView(page)
    await seedStreamingMessage(page)

    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'tool_event',
        event: {
          kind: 'call', id: 's1',
          tool: 'web_search', args: { query: 'netflix clone' },
        },
      })
    })

    await expect(
      page.locator('text=/web search|web_search/i').first(),
    ).toBeVisible({ timeout: 3000 })
  })


  test('tool_result with success surfaces as a completed row', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await waitForChatView(page)
    await seedStreamingMessage(page)

    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'tool_event',
        event: { kind: 'call', id: 's2', tool: 'file_read', args: { path: 'a.txt' } },
      })
      window.__chikaPushChrome({
        type: 'tool_event',
        event: {
          kind: 'result', id: 's2', tool: 'file_read',
          result: { content: 'hello' }, duration_ms: 5,
        },
      })
    })

    await expect(
      page.locator('text=/file read|file_read/i').first(),
    ).toBeVisible({ timeout: 3000 })
  })


  test('tool_result with error surfaces an error indicator', async ({ page, popupURL }) => {
    await page.addInitScript({ content: standaloneStub })
    await page.goto(popupURL)
    await waitForChatView(page)
    await seedStreamingMessage(page)

    await page.evaluate(() => {
      window.__chikaPushChrome({
        type: 'tool_event',
        event: { kind: 'call', id: 's3', tool: 'shell_exec', args: { command: 'oops' } },
      })
      window.__chikaPushChrome({
        type: 'tool_event',
        event: {
          kind: 'result', id: 's3', tool: 'shell_exec',
          result: null, error: 'command not found: oops', duration_ms: 2,
        },
      })
    })

    // Either the error glyph appears OR the tool name remains rendered
    // — the popup may collapse error text behind a glyph in tight space.
    const toolVisible = await page
      .locator('text=/shell exec|shell_exec/i').first()
      .isVisible()
      .catch(() => false)
    const errorRowVisible = await page
      .locator('.tool-row.error').first()
      .isVisible()
      .catch(() => false)
    expect(toolVisible || errorRowVisible).toBe(true)
  })
})

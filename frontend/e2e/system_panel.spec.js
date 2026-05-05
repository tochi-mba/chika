/**
 * Right-side system panel — tab strip + per-tab content.
 *
 * The panel has six tabs: Events / Workflow / Shells / Variables /
 * Memory / Raw. Each tab pulls from the system store; switching tabs
 * must NOT re-trigger network calls and the active tab must visibly
 * stand out (accent text + bottom border).
 *
 * Coverage:
 *   - All six tabs render in the strip.
 *   - Clicking a tab activates it and shows its content.
 *   - Tab count badges appear when their store has data.
 *   - Variable / memory / events content renders when WS pushes data.
 *   - Collapse toggle hides the panel body.
 */
import { test, expect, waitForApp, pushEvent, pushSequence } from './_fixtures.js'


test.describe('system panel', () => {
  test.beforeEach(async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
  })


  test('renders all six tabs', async ({ chikaPage }) => {
    for (const label of ['Events', 'Workflow', 'Shells', 'Variables', 'Memory', 'Raw']) {
      await expect(
        chikaPage.locator(`button.tab:has-text("${label}")`).first(),
      ).toBeVisible({ timeout: 4000 })
    }
  })


  test('clicking a tab activates it (gets accent color via .active class)', async ({ chikaPage }) => {
    const variables = chikaPage.locator('button.tab:has-text("Variables")').first()
    await variables.click()
    await expect(variables).toHaveClass(/active/)

    const events = chikaPage.locator('button.tab:has-text("Events")').first()
    await events.click()
    await expect(events).toHaveClass(/active/)
    // Variables is no longer active.
    await expect(variables).not.toHaveClass(/active/)
  })


  test('event count badge appears after WS pushes events', async ({ chikaPage }) => {
    // Push a couple of WS events so the events store fills up.
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf' },
      { type: 'tool_call', step_id: 's1', tool: 'file_read', args: { path: 'x' } },
      { type: 'tool_result', step_id: 's1', tool: 'file_read', result: { content: 'ok' } },
    ])

    const eventsTab = chikaPage.locator('button.tab:has-text("Events")').first()
    // The .tab-count badge should now display a number.
    const badge = eventsTab.locator('.tab-count').first()
    await expect(badge).toBeVisible({ timeout: 3000 })
    const txt = (await badge.textContent() || '').trim()
    expect(parseInt(txt, 10)).toBeGreaterThan(0)
  })


  test('Variables tab shows variable cards when variable_set fires', async ({ chikaPage }) => {
    await pushEvent(chikaPage, {
      type:        'variable_set',
      name:        'plan',
      var_type:    'json',
      size_bytes:  120,
      value_preview: '{"goal": "test"}',
    })

    await chikaPage.locator('button.tab:has-text("Variables")').first().click()
    // The variable name renders as mono accent text.
    await expect(chikaPage.locator('.var-card .name').first()).toContainText('plan')
  })


  test('Memory tab shows memory entries when memory_update fires', async ({ chikaPage }) => {
    await pushEvent(chikaPage, {
      type:  'memory_update',
      key:   'user_role',
      value: 'data scientist',
    })

    await chikaPage.locator('button.tab:has-text("Memory")').first().click()
    await expect(chikaPage.locator('.mem-entry').first()).toBeVisible({ timeout: 3000 })
    await expect(chikaPage.locator('.mem-entry .key').first()).toContainText('user_role')
  })


  test('Raw tab shows raw JSON of every event', async ({ chikaPage }) => {
    await pushEvent(chikaPage, {
      type: 'workflow_start',
      workflow_id: 'wf-raw',
      name: 'sample',
    })
    await chikaPage.locator('button.tab:has-text("Raw")').first().click()

    // The raw panel renders each event as <pre.raw-line>. The events
    // store also has setup events (session_info, settings_info) so the
    // workflow_start row may not be first — match across all rows.
    const matching = chikaPage.locator('.raw-line', { hasText: 'wf-raw' }).first()
    await expect(matching).toBeVisible({ timeout: 3000 })
  })


  test('collapse toggle hides the tab strip body', async ({ chikaPage }) => {
    const collapse = chikaPage.locator('.collapse-btn').first()
    await expect(collapse).toBeVisible({ timeout: 3000 })

    // Before click: panel body has events container visible.
    const panelBody = chikaPage.locator('.panel-body').first()
    await expect(panelBody).toBeVisible()

    await collapse.click()
    // After collapse, the .panel-col gets `.collapsed`. We don't
    // directly assert that class because the toggle wires through
    // App.vue — instead we check the panel width / content visibility
    // shrinks. The simplest assertion: the panel-body either becomes
    // hidden or its bounding box shrinks to zero.
    await chikaPage.waitForTimeout(300)
    const box = await panelBody.boundingBox().catch(() => null)
    // Either hidden (boundingBox returns null) or width collapsed.
    if (box) {
      expect(box.width).toBeLessThan(50)
    }
  })
})

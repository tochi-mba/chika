/**
 * Workspace-scope approval e2e — covers the tri-state grant flow.
 *
 * When a tool tries to write outside the active profile's workspace,
 * the engine fires an ``approval_required`` event with
 * ``approval_type: 'workspace_scope'``. The modal must offer THREE
 * choices: Deny, Allow once, Allow for session — and dispatch the
 * user's pick back as ``approval_response`` with a ``scope`` field
 * (``deny`` | ``once`` | ``session``) so the WorkspacePolicy on the
 * backend can record session grants correctly.
 *
 * Bug this guards against:
 *   The approval modal previously only had Approve / Deny. The
 *   tri-state was added so the user can grant a folder for the rest
 *   of the session. If the rendering regresses to a binary choice
 *   the user can never grant session scope and every write outside
 *   the workspace prompts again — exactly the retry-loop pattern
 *   caught by the engine circuit-breaker.
 */
import { test, expect, waitForApp, pushEvent, sentMessages } from './_fixtures.js'


function workspaceRequest() {
  return {
    type:           'approval_required',
    request_id:     'ws-req-1',
    approval_type:  'workspace_scope',
    tool:           'file_write',
    step_id:        's1',
    message:        'Chika wants to write a file OUTSIDE the workspace.',
    args: {
      path:      'C:\\Users\\test\\Downloads\\netflix-clone\\index.html',
      scope_dir: 'C:\\Users\\test\\Downloads\\netflix-clone',
      workspace: 'C:\\workspace',
      action:    'write',
    },
  }
}


async function findApprovalResponse(page, requestId) {
  const msgs = await sentMessages(page)
  return msgs.find(m =>
    m && m.type === 'approval_response' && m.request_id === requestId,
  )
}


test.describe('workspace-scope approval', () => {
  test.beforeEach(async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, workspaceRequest())
  })


  test('renders all three buttons (Deny / Allow once / Allow for session)', async ({ chikaPage }) => {
    await expect(
      chikaPage.locator('text=/wants to write a file OUTSIDE the workspace/i').first(),
    ).toBeVisible({ timeout: 3000 })
    await expect(chikaPage.locator('button:has-text("Deny")').first()).toBeVisible()
    await expect(chikaPage.locator('button:has-text("Allow once")').first()).toBeVisible()
    await expect(chikaPage.locator('button:has-text("Allow for session")').first()).toBeVisible()
  })


  test('Deny dispatches scope=deny', async ({ chikaPage }) => {
    await chikaPage.locator('button:has-text("Deny")').first().click()
    const answer = await findApprovalResponse(chikaPage, 'ws-req-1')
    expect(answer).toBeTruthy()
    expect(answer.scope).toBe('deny')
    // Workspace deny must NOT be reported as approved.
    expect(answer.approved).toBe(false)
  })


  test('Allow once dispatches scope=once', async ({ chikaPage }) => {
    await chikaPage.locator('button:has-text("Allow once")').first().click()
    const answer = await findApprovalResponse(chikaPage, 'ws-req-1')
    expect(answer).toBeTruthy()
    expect(answer.scope).toBe('once')
    expect(answer.approved).toBe(true)
  })


  test('Allow for session dispatches scope=session', async ({ chikaPage }) => {
    await chikaPage.locator('button:has-text("Allow for session")').first().click()
    const answer = await findApprovalResponse(chikaPage, 'ws-req-1')
    expect(answer).toBeTruthy()
    expect(answer.scope).toBe('session')
    expect(answer.approved).toBe(true)
  })
})

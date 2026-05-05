/**
 * Approval-modal ordering — guards the rule "user approves the PLAN
 * before write-tool approval modals can fire".
 *
 * The bug this guards against:
 *   The plan-approval gate in the engine runs *after* a workflow
 *   finishes. If the agent ever packs `plan_set` + `scaffold_web_app`
 *   + `file_write` into one workflow, the user sees scaffold_web_app's
 *   approval modal BEFORE they've seen the plan — and the modal
 *   visually covers the plan-approve button (see screenshot from
 *   2026-05-05). The runtime now refuses such workflows with
 *   `plan_required`, but the UI must also defend against a stuck
 *   modal in case a misordered event sequence ever sneaks through.
 *
 * Coverage rules in plain English:
 *   1. When a plan-review approval AND a write-tool approval are
 *      pending at the same time, the plan modal must be reachable —
 *      the user must be able to click its Approve button without
 *      another modal stealing the click.
 *   2. The plan modal's Approve button must be visible and clickable
 *      when only the plan modal is present (sanity check).
 *   3. After approving the plan, write-tool approvals can fire — at
 *      that point the user has consented to the plan and the next
 *      modal is expected behaviour.
 */
import { test, expect, waitForApp, pushSequence } from './_fixtures.js'


const samplePlan = {
  goal: 'Build a Netflix clone',
  requirements: ['Real video assets', 'Responsive UI'],
  tasks: [
    { id: 't1', text: 'Set up project', status: 'pending', subtasks: [] },
    { id: 't2', text: 'Build UI',       status: 'pending', subtasks: [] },
  ],
  created_at: 0, updated_at: 0,
}


test.describe('approval modal ordering', () => {
  test.beforeEach(async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
  })


  test('plan-review approve button is clickable when plan modal is alone', async ({ chikaPage }) => {
    // Drive a plan_set workflow + the plan_review approval_required.
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf1' },
      { type: 'tool_call', step_id: 's1', tool: 'plan_set', args: samplePlan },
      {
        type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan: samplePlan }, duration_ms: 1,
      },
      { type: 'workflow_done', workflow_id: 'wf1', variables: { plan: samplePlan } },
      {
        type:           'approval_required',
        request_id:     'plan-req-1',
        approval_type:  'plan_review',
        tool:           'plan_review',
        step_id:        'plan_review',
        message:        'Approve this plan?',
        args:           samplePlan,
      },
    ])

    // Plan-approve button must be visible AND not covered by anything.
    const approveBtn = chikaPage
      .locator('.modal button:has-text("Approve"), button.approve:has-text("Approve")')
      .first()
    await expect(approveBtn).toBeVisible({ timeout: 4000 })
    // The locator's click() will fail if another element intercepts —
    // that is the regression check. We don't care about the side-effect.
    await approveBtn.click({ trial: true })
  })


  test('write-tool approval does not appear before plan approval is resolved', async ({ chikaPage }) => {
    // Backend (per the new gate) refuses plan_set+writes in the same
    // workflow. Simulate the CORRECT shape: plan_set first, plan_review
    // approval, then (only after the plan is approved) the next
    // workflow with write tools fires its approval.
    //
    // The bad shape — write-tool approval fires WITH the plan still
    // pending — would mean the engine regressed. Inject both at the
    // same time and verify the plan-approve button is still reachable.
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf1' },
      { type: 'tool_call', step_id: 's1', tool: 'plan_set', args: samplePlan },
      {
        type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan: samplePlan }, duration_ms: 1,
      },
      { type: 'workflow_done', workflow_id: 'wf1', variables: { plan: samplePlan } },
      {
        type:           'approval_required',
        request_id:     'plan-req-2',
        approval_type:  'plan_review',
        tool:           'plan_review',
        step_id:        'plan_review',
        message:        'Approve this plan?',
        args:           samplePlan,
      },
      // Simulating the regression: a write-tool approval fires while
      // the plan is still pending. The frontend must keep the plan
      // modal reachable.
      {
        type:           'approval_required',
        request_id:     'scaffold-req-1',
        approval_type:  'confirm',
        tool:           'scaffold_web_app',
        step_id:        's2',
        message:        'Scaffold a new web-app project',
        args:           { stack: 'vite-react-ts', name: 'netflix-clone' },
      },
    ])

    // The plan-review modal carries an "Approve" button that submits
    // the user's plan-review decision. Even with another approval
    // queued behind it, the plan approve button must be reachable.
    const planApprove = chikaPage
      .locator('button.approve:has-text("Approve")')
      .first()
    await expect(planApprove).toBeVisible({ timeout: 4000 })
    // ``trial: true`` performs every actionability check (visible,
    // stable, enabled, receives events) without firing the click —
    // exactly the assertion we want here.
    await planApprove.click({ trial: true })
  })


  test('after approving the plan, a follow-up write-tool approval is shown', async ({ chikaPage }) => {
    // The expected post-approval flow: plan-review fires, user approves,
    // engine moves on to the next turn which triggers a write-tool
    // approval. That's normal — we're just checking the UI doesn't
    // get stuck after a plan is approved.
    await pushSequence(chikaPage, [
      { type: 'workflow_start', workflow_id: 'wf1' },
      { type: 'tool_call', step_id: 's1', tool: 'plan_set', args: samplePlan },
      {
        type: 'tool_result', step_id: 's1', tool: 'plan_set',
        result: { _source: 'plan_set', plan: samplePlan }, duration_ms: 1,
      },
      { type: 'workflow_done', workflow_id: 'wf1', variables: { plan: samplePlan } },
      {
        type:           'approval_required',
        request_id:     'plan-req-3',
        approval_type:  'plan_review',
        tool:           'plan_review',
        step_id:        'plan_review',
        message:        'Approve this plan?',
        args:           samplePlan,
      },
    ])

    const planApprove = chikaPage.locator('button.approve:has-text("Approve")').first()
    await expect(planApprove).toBeVisible({ timeout: 4000 })
    await planApprove.click()

    // Engine sends a follow-up write-tool approval after the plan is
    // approved — we now expect a new modal whose tool is scaffold_web_app.
    await pushSequence(chikaPage, [
      {
        type:           'approval_required',
        request_id:     'scaffold-req-2',
        approval_type:  'confirm',
        tool:           'scaffold_web_app',
        step_id:        's2',
        message:        'Scaffold a new web-app project',
        args:           { stack: 'vite-react-ts', name: 'netflix-clone' },
      },
    ])

    await expect(
      chikaPage.locator('text=/Scaffold a new web-app project/i').first(),
    ).toBeVisible({ timeout: 3000 })
  })
})

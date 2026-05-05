<template>
  <Teleport to="body">
    <div class="overlay" v-if="approvals.length > 0">
      <div
        class="modal"
        v-for="req in approvals"
        :key="req.request_id"
      >
        <!-- Header -->
        <div class="modal-header">
          <span class="icon">{{ iconFor(req.approval_type) }}</span>
          <span class="title">{{ titleFor(req.approval_type) }}</span>
        </div>

        <!-- Message -->
        <p class="approval-msg" v-if="req.message">{{ req.message }}</p>

        <!-- Tool badge -->
        <div class="tool-row">
          <span class="tool-badge">{{ req.tool }}</span>
        </div>

        <!-- Args (skip for password types and plan_review — the plan
             panel already displays the full plan above the modal). -->
        <div
          class="args-block"
          v-if="req.args && Object.keys(req.args).length
                && !req.approval_type?.includes('password')
                && req.approval_type !== 'plan_review'"
        >
          <div class="args-label">Arguments</div>
          <pre class="args-pre">{{ JSON.stringify(req.args, null, 2) }}</pre>
        </div>

        <!-- ── Password input ── -->
        <div
          class="pw-block"
          v-if="req.approval_type === 'set_password' || req.approval_type === 'verify_password'"
        >
          <label class="pw-label">
            {{ req.approval_type === 'verify_password' ? 'Password' : 'New password' }}
            <span class="pw-hint" v-if="req.approval_type === 'set_password'">
              (leave blank to remove)
            </span>
          </label>
          <div class="pw-input-wrap">
            <input
              :ref="el => { if (el) pwInputs[req.request_id] = el }"
              class="pw-input"
              :type="showPw[req.request_id] ? 'text' : 'password'"
              :placeholder="req.approval_type === 'verify_password' ? 'Enter password…' : 'Set a password…'"
              v-model="passwords[req.request_id]"
              @keydown.enter="handleApprove(req)"
              @keydown.esc="emit('deny', req.request_id)"
              autocomplete="off"
              autocorrect="off"
              spellcheck="false"
            />
            <button
              class="pw-toggle"
              type="button"
              @click="togglePw(req.request_id)"
              :title="showPw[req.request_id] ? 'Hide' : 'Show'"
            >{{ showPw[req.request_id] ? '🙈' : '👁' }}</button>
          </div>

          <!-- Wrong password feedback -->
          <p class="pw-error" v-if="pwError[req.request_id]">
            {{ pwError[req.request_id] }}
          </p>
        </div>

        <!-- plan_review — three-way action picker with optional
             feedback / reason textarea. The textarea expands when
             the user clicks "Edit" or "Deny" so they can attach a
             message; "Approve" submits straight away. -->
        <div class="plan-review-block" v-if="req.approval_type === 'plan_review'">
          <textarea
            v-if="planReviewMode[req.request_id]"
            class="plan-review-text"
            :ref="el => { if (el) planReviewInputs[req.request_id] = el }"
            v-model="planReviewMessages[req.request_id]"
            :placeholder="
              planReviewMode[req.request_id] === 'edit'
                ? 'What should change about the plan?'
                : 'Why are you rejecting this plan?'
            "
            rows="3"
            @keydown.ctrl.enter="submitPlanReview(req)"
          ></textarea>
          <div class="actions">
            <button
              class="btn deny"
              :disabled="pendingIds.has(req.request_id)"
              :class="{ 'btn--armed': planReviewMode[req.request_id] === 'deny' }"
              @click="armPlanReview(req, 'deny')"
            >{{ planReviewMode[req.request_id] === 'deny' ? '✕ Send rejection' : '✕ Deny' }}</button>
            <button
              class="btn approve-once"
              :disabled="pendingIds.has(req.request_id)"
              :class="{ 'btn--armed': planReviewMode[req.request_id] === 'edit' }"
              @click="armPlanReview(req, 'edit')"
            >{{ planReviewMode[req.request_id] === 'edit' ? '✎ Send feedback' : '✎ Edit' }}</button>
            <button
              class="btn approve"
              :disabled="pendingIds.has(req.request_id)"
              @click="approvePlanReview(req)"
            >✓ Approve</button>
          </div>
        </div>

        <!-- Actions — workspace_scope shows three-way scope picker
             so the user controls how long the grant lives. Other
             approval types keep the existing two-button layout. -->
        <div class="actions" v-else-if="req.approval_type === 'workspace_scope'">
          <button
            class="btn deny"
            :disabled="pendingIds.has(req.request_id)"
            @click="handleWorkspace(req, 'deny')"
          >✕ Deny</button>
          <button
            class="btn approve-once"
            :disabled="pendingIds.has(req.request_id)"
            :title="`Allow once for ${req.args?.path || 'this path'}`"
            @click="handleWorkspace(req, 'once')"
          >Allow once</button>
          <button
            class="btn approve"
            :disabled="pendingIds.has(req.request_id)"
            :title="`Allow this folder for the whole session`"
            @click="handleWorkspace(req, 'session')"
          >Allow for session</button>
        </div>
        <div class="actions" v-else>
          <button
            class="btn deny"
            @click="emit('deny', req.request_id)"
          >✕ Deny</button>
          <button
            class="btn approve"
            :disabled="pendingIds.has(req.request_id)"
            @click="handleApprove(req)"
          >
            <span v-if="pendingIds.has(req.request_id)" class="spinner" />
            <span v-else>✓ {{ req.approval_type === 'verify_password' ? 'Confirm' : 'Approve' }}</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, reactive, watch, nextTick } from 'vue'

const props = defineProps({
  approvals: { type: Array, default: () => [] }
})
const emit = defineEmits(['approve', 'deny'])

// Per-request-id password values
const passwords = reactive({})
// Per-request-id show/hide toggle
const showPw    = reactive({})
// Per-request-id input refs (for auto-focus)
const pwInputs  = reactive({})
// Per-request-id error messages
const pwError   = reactive({})
// Prevents double-click: set of request_ids with a pending resolve
const pendingIds = ref(new Set())

// plan_review state — per-request-id: which mode the textarea is for
// ('edit' | 'deny' | undefined) + the user's message + the textarea ref.
const planReviewMode     = reactive({})
const planReviewMessages = reactive({})
const planReviewInputs   = reactive({})

// Auto-focus password input when a new password-type approval appears
watch(
  () => props.approvals.length,
  async () => {
    await nextTick()
    for (const req of props.approvals) {
      if (req.approval_type?.includes('password') && pwInputs[req.request_id]) {
        pwInputs[req.request_id].focus()
        break
      }
    }
  }
)

function iconFor(type) {
  if (type === 'verify_password') return '🔐'
  if (type === 'set_password')    return '🔑'
  if (type === 'workspace_scope') return '📁'
  return '⚠️'
}

function titleFor(type) {
  if (type === 'verify_password') return 'Password Required'
  if (type === 'set_password')    return 'Set Password'
  if (type === 'workspace_scope') return 'Write outside workspace?'
  if (type === 'plan_review')     return 'Approve Plan?'
  return 'Approval Required'
}

function armPlanReview(req, mode) {
  // First click on Edit/Deny: open the textarea so the user can write
  // a reason or feedback. Second click on the SAME button submits.
  if (planReviewMode[req.request_id] === mode) {
    submitPlanReview(req)
    return
  }
  planReviewMode[req.request_id] = mode
  planReviewMessages[req.request_id] = planReviewMessages[req.request_id] || ''
  // Focus the textarea on the next tick so the user can start typing.
  nextTick(() => {
    const el = planReviewInputs[req.request_id]
    if (el) el.focus()
  })
}

function approvePlanReview(req) {
  // Approve doesn't need a message — submit straight away.
  if (pendingIds.value.has(req.request_id)) return
  pendingIds.value = new Set([...pendingIds.value, req.request_id])
  emit('approve', req.request_id, { action: 'approve' })
  _cleanupPlanReview(req.request_id)
}

function submitPlanReview(req) {
  if (pendingIds.value.has(req.request_id)) return
  const mode = planReviewMode[req.request_id]
  if (!mode) {
    // No mode armed — treat as approve.
    approvePlanReview(req)
    return
  }
  const message = (planReviewMessages[req.request_id] || '').trim()
  pendingIds.value = new Set([...pendingIds.value, req.request_id])
  if (mode === 'edit') {
    emit('approve', req.request_id, {
      action:   'edit',
      feedback: message,
    })
  } else {
    emit('approve', req.request_id, {
      action: 'deny',
      reason: message,
    })
  }
  _cleanupPlanReview(req.request_id)
}

function _cleanupPlanReview(rid) {
  delete planReviewMode[rid]
  delete planReviewMessages[rid]
  delete planReviewInputs[rid]
  pendingIds.value = new Set([...pendingIds.value].filter(id => id !== rid))
}

function handleWorkspace(req, scope) {
  // Workspace approvals carry the user's scope choice as part of the
  // approval payload so the WorkspacePolicy on the backend can honour
  // 'session' / 'once' / 'deny' distinctly. We re-use the 'approve'
  // event with a scope payload — the backend handler unpacks it.
  if (pendingIds.value.has(req.request_id)) return
  pendingIds.value = new Set([...pendingIds.value, req.request_id])
  emit('approve', req.request_id, { scope })
  // Clear the pending flag the same way handleApprove does — the
  // parent component removes the request from ``approvals`` once the
  // backend confirms, but we don't want a stale spinner if the user
  // double-clicks during the WS round-trip.
  pendingIds.value = new Set(
    [...pendingIds.value].filter(id => id !== req.request_id),
  )
}

function togglePw(id) {
  showPw[id] = !showPw[id]
}

function handleApprove(req) {
  if (pendingIds.value.has(req.request_id)) return

  const type = req.approval_type || 'confirm'
  const pwd  = passwords[req.request_id] || ''

  // For verify_password, do client-side non-empty check
  if (type === 'verify_password' && !pwd) {
    pwError[req.request_id] = 'Please enter your password.'
    pwInputs[req.request_id]?.focus()
    return
  }

  pwError[req.request_id] = ''

  // Mark as pending to prevent double-submission
  pendingIds.value = new Set([...pendingIds.value, req.request_id])

  emit('approve', req.request_id, pwd)

  // Clean up local state
  delete passwords[req.request_id]
  delete showPw[req.request_id]
  delete pwInputs[req.request_id]
  pendingIds.value = new Set([...pendingIds.value].filter(id => id !== req.request_id))
}
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  gap: 16px;
  flex-direction: column;
  padding: 24px;
  backdrop-filter: blur(2px);
}

.modal {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 24px 28px;
  width: 460px;
  max-width: 100%;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.18);
  animation: pop 160ms var(--spring);
}
:root.dark .modal {
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
}

@keyframes pop {
  from { transform: scale(0.94); opacity: 0; }
  to   { transform: scale(1);    opacity: 1; }
}

.modal-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.icon  { font-size: 18px; }
.title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-1);
  letter-spacing: -0.015em;
}

.approval-msg {
  font-size: 13.5px;
  color: var(--text-2);
  margin: 0 0 16px;
  line-height: 1.55;
}

.tool-row { margin-bottom: 14px; }
.tool-badge {
  display: inline-block;
  background: var(--accent-dim);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 500;
  padding: 3px 9px;
  border-radius: 6px;
}

.args-label {
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-3);
  font-weight: 600;
  margin-bottom: 6px;
}
.args-pre {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-2);
  max-height: 180px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0 0 18px;
  line-height: 1.5;
}

/* ── Password block ── */
.pw-block { margin-bottom: 20px; }

.pw-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 8px;
}
.pw-hint { font-weight: 400; color: var(--text-3); text-transform: none; letter-spacing: 0; }

.pw-input-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pw-input {
  flex: 1;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 9px 12px;
  color: var(--text-1);
  font-size: 14px;
  font-family: inherit;
  outline: none;
  transition: border-color 140ms var(--spring);
}
.pw-input:focus { border-color: var(--accent); }
.pw-input::placeholder { color: var(--text-3); }

.pw-toggle {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 10px;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  color: var(--text-3);
  transition: background 140ms, color 140ms;
}
.pw-toggle:hover {
  background: var(--surface-3, var(--surface-2));
  color: var(--text-1);
}

.pw-error {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--error);
}

/* ── Actions ── */
.actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 4px;
}
.btn {
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-2);
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 140ms var(--spring);
  display: flex;
  align-items: center;
  gap: 6px;
}
.btn:hover:not(:disabled) {
  color: var(--text-1);
  border-color: var(--border-strong);
  transform: translateY(-1px);
}
.btn:active { transform: scale(0.98); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

.btn.deny {
  background: transparent;
  color: var(--text-3);
}
.btn.deny:hover:not(:disabled) {
  color: var(--error);
  border-color: var(--error);
  background: color-mix(in srgb, var(--error) 8%, transparent);
}

.btn.approve {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
  min-width: 100px;
  justify-content: center;
}
.btn.approve:hover:not(:disabled) {
  background: var(--accent-2);
  border-color: var(--accent-2);
  color: #fff;
}

.btn.approve-once {
  background: transparent;
  color: var(--accent);
  border-color: var(--accent);
}
.btn.approve-once:hover:not(:disabled) {
  background: var(--accent-dim);
  color: var(--accent);
}

/* plan_review — stacked block: textarea (when armed) + 3-button row. */
.plan-review-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 6px;
}
.plan-review-text {
  width: 100%;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-1);
  font: inherit;
  font-size: 13px;
  line-height: 1.5;
  padding: 9px 11px;
  resize: vertical;
  min-height: 60px;
  max-height: 160px;
  transition: border-color 140ms var(--spring);
}
.plan-review-text:focus {
  outline: none;
  border-color: var(--accent);
}

.btn--armed {
  background: var(--accent-dim);
  border-color: var(--accent);
  color: var(--accent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 25%, transparent);
}

/* Spinner */
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>

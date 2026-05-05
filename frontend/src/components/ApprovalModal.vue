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

        <!-- Args (only for non-password types to avoid leaking context) -->
        <div
          class="args-block"
          v-if="req.args && Object.keys(req.args).length && !req.approval_type?.includes('password')"
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

        <!-- Actions — workspace_scope shows three-way scope picker
             so the user controls how long the grant lives. Other
             approval types keep the existing two-button layout. -->
        <div class="actions" v-if="req.approval_type === 'workspace_scope'">
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
  return 'Approval Required'
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
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  gap: 16px;
  flex-direction: column;
}

.modal {
  background: #1a1a24;
  border: 1px solid #6c63ff88;
  border-radius: 14px;
  padding: 24px 28px;
  width: 460px;
  max-width: 90vw;
  box-shadow: 0 8px 40px rgba(0,0,0,0.6), 0 0 0 1px #6c63ff33;
  animation: pop 0.15s ease-out;
}

@keyframes pop {
  from { transform: scale(0.92); opacity: 0; }
  to   { transform: scale(1);    opacity: 1; }
}

.modal-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.icon  { font-size: 20px; }
.title { font-size: 16px; font-weight: 700; color: #e8e8f0; }

.approval-msg {
  font-size: 14px;
  color: #c8c8d8;
  margin: 0 0 14px;
  line-height: 1.5;
}

.tool-row { margin-bottom: 14px; }
.tool-badge {
  display: inline-block;
  background: #2a2a3d;
  border: 1px solid #6c63ff55;
  color: #a89fff;
  font-family: monospace;
  font-size: 13px;
  padding: 4px 10px;
  border-radius: 6px;
}

.args-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #555;
  margin-bottom: 6px;
}
.args-pre {
  background: #111118;
  border: 1px solid #2a2a35;
  border-radius: 8px;
  padding: 10px 12px;
  font-family: monospace;
  font-size: 12px;
  color: #b8b8c8;
  max-height: 180px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0 0 18px;
}

/* ── Password block ── */
.pw-block { margin-bottom: 20px; }

.pw-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 8px;
}
.pw-hint { font-weight: 400; color: #555; text-transform: none; letter-spacing: 0; }

.pw-input-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pw-input {
  flex: 1;
  background: #111118;
  border: 1px solid #2a2a42;
  border-radius: 8px;
  padding: 9px 12px;
  color: #e8e8f0;
  font-size: 14px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s;
}
.pw-input:focus { border-color: #6c63ff; }
.pw-input::placeholder { color: #404058; }

.pw-toggle {
  background: #1e1e2a;
  border: 1px solid #2a2a3a;
  border-radius: 8px;
  padding: 8px 10px;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  color: #888;
  transition: background 0.15s;
}
.pw-toggle:hover { background: #2a2a38; }

.pw-error {
  margin: 6px 0 0;
  font-size: 12px;
  color: #f85149;
}

/* ── Actions ── */
.actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 4px;
}
.btn {
  padding: 8px 20px;
  border-radius: 8px;
  border: none;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, transform 0.1s;
  display: flex;
  align-items: center;
  gap: 6px;
}
.btn:active { transform: scale(0.97); }
.btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }

.btn.deny {
  background: #2a2a35;
  color: #cc4444;
  border: 1px solid #cc444440;
}
.btn.deny:hover { background: #3a2020; }

.btn.approve {
  background: #6c63ff;
  color: #fff;
  min-width: 100px;
  justify-content: center;
}
.btn.approve:hover:not(:disabled) { background: #7c72ff; }

/* Workspace-scope picker — middle button is a softer "allow once". */
.btn.approve-once {
  background: #2a2a35;
  color: #6c63ff;
  border: 1px solid #6c63ff60;
}
.btn.approve-once:hover:not(:disabled) {
  background: rgba(108, 99, 255, 0.12);
}

/* Spinner */
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>

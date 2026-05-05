import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

// Pet state machine — driven by engine events.
// states: 'idle' | 'thinking' | 'working' | 'celebrate' | 'sad' | 'sleeping'
// Each non-idle state carries a `bubble` (one-shot speech) + `since` ts.
const TOOL_BUBBLES = {
  shell_exec:        { kind: 'working', text: 'running a command…' },
  bg_shell_exec:     { kind: 'working', text: 'spawning a process…' },
  file_read:         { kind: 'working', text: 'reading…' },
  file_write:        { kind: 'working', text: 'writing…' },
  file_edit_lines:   { kind: 'working', text: 'editing…' },
  file_replace:      { kind: 'working', text: 'replacing text…' },
  web_search:        { kind: 'working', text: 'searching the web…' },
  web_fetch:         { kind: 'working', text: 'fetching a page…' },
  verify_url:        { kind: 'working', text: 'checking a link…' },
  git_status:        { kind: 'working', text: 'looking at git…' },
  git_commit:        { kind: 'working', text: 'committing…' },
  git_push:          { kind: 'working', text: 'pushing…' },
  memory_persist:    { kind: 'working', text: 'remembering…' },
  memory_recall:     { kind: 'working', text: 'recalling…' },
  browser_navigate:  { kind: 'working', text: 'navigating…' },
  browser_screenshot:{ kind: 'working', text: 'snapping a shot…' },
  browser_click:     { kind: 'working', text: 'clicking…' },
}

function derivePetState(prev, event) {
  const t = event.type
  if (t === 'thinking')        return { ...prev, state: 'thinking', bubble: null,                    tickedAt: Date.now() }
  if (t === 'workflow_start')  return { ...prev, state: 'working',  bubble: 'getting to work…',      tickedAt: Date.now() }
  if (t === 'tool_call') {
    const reaction = TOOL_BUBBLES[event.tool]
    return { ...prev, state: 'working', bubble: reaction?.text || `using ${event.tool}…`, tickedAt: Date.now() }
  }
  if (t === 'tool_result' && event.error)  return { ...prev, state: 'sad',       bubble: 'oops, that failed', tickedAt: Date.now() }
  if (t === 'workflow_done')               return { ...prev, state: 'celebrate', bubble: 'done!',            tickedAt: Date.now() }
  if (t === 'error')                       return { ...prev, state: 'sad',       bubble: 'something broke',  tickedAt: Date.now() }
  if (t === 'cancelled')                   return { ...prev, state: 'sad',       bubble: 'stopped.',          tickedAt: Date.now() }
  if (t === 'done') {
    // After a successful turn settle back to idle within 2s
    return { ...prev, state: prev.state === 'sad' ? 'sad' : 'idle', bubble: null, tickedAt: Date.now() }
  }
  return prev
}

export const useSystemStore = defineStore('system', () => {
  // Raw event feed (all events in order)
  const events = ref([])

  // Live workflow tree — the currently executing workflow
  const activeWorkflow = ref(null)

  // Variables map: name → { name, var_type, size_bytes, value_preview }
  const variables = ref({})

  // Memory map: key → { key, value, created, accessed, ttl_days }
  const memory = ref({})

  // Pending approval requests: [{ request_id, tool, args, step_id }]
  const pendingApprovals = ref([])

  // Pending ask_user questions: [{ request_id, question, options, header, multi_select }]
  const pendingQuestions = ref([])

  // Shell processes: pid → { pid, command, running, exit_code, stdout, stderr }
  const shellProcesses = ref({})

  // Connection state
  const connected = ref(false)
  const sessionId = ref('')
  const connectionError = ref(null)  // null or error string (4.3)

  // Chrome extension connection state
  const extensionConnected = ref(false)

  // Active profile + pet
  const profile = ref({ name: 'default', workspace: '', pet_id: null })
  // The pet currently animated for this profile.  Initially the
  // server/profile pet_id; "state" is 'idle' | 'working' | 'celebrate' | 'sad'.
  const petState = ref({ id: null, state: 'idle', tickedAt: 0 })

  // Audit log of every SKILL.md the agent has loaded this session.
  // Each entry: { skill, char_count, condensed, at }
  // The system panel renders a count so the user can SEE whether the agent
  // is actually consulting skill docs or working from prompt-only memory.
  const skillLoads = ref([])

  // Autonomy mode: "supervised" | "autonomous"
  const autonomy = ref('supervised')
  // Per-category permission overrides: category_id → "ask" | "skip"
  const toolPermissions = ref({})
  // Category metadata from server: category_id → label string
  const permissionCategories = ref({})

  function setAutonomy(val) {
    if (val === 'supervised' || val === 'autonomous') {
      autonomy.value = val
    }
  }

  function setSettings(data) {
    if (data.autonomy) autonomy.value = data.autonomy
    if (data.tool_permissions) toolPermissions.value = { ...data.tool_permissions }
    if (data.categories) permissionCategories.value = { ...data.categories }
  }

  function setConnected(val, sid) {
    connected.value = val
    if (sid) sessionId.value = sid
  }

  function setExtensionConnected(val) {
    extensionConnected.value = !!val
  }

  function setConnectionError(msg) {
    connectionError.value = msg || null
  }

  function pushEvent(event) {
    // Keep last 500 events to avoid memory leak
    events.value.push({ ...event, _ts: Date.now() })
    if (events.value.length > 500) events.value.shift()

    // Pet state piggybacks on engine events. Done before the switch so it
    // reacts to ALL events that imply work happening, even ones that have
    // no other store-level effect (token, thinking, step_start).
    petState.value = derivePetState(petState.value, event)

    // Derive state from specific event types
    switch (event.type) {
      case 'workflow_start':
        activeWorkflow.value = {
          id: event.workflow_id,
          name: event.name,
          steps: [],
          status: 'running',
          startedAt: Date.now(),
        }
        break

      case 'variable_set':
        variables.value[event.name] = {
          name: event.name,
          var_type: event.var_type,
          size_bytes: event.size_bytes,
          value_preview: event.value_preview || '',
          updatedAt: Date.now(),
        }
        break

      case 'memory_update':
        memory.value[event.key] = {
          key: event.key,
          value: event.value,
          updatedAt: Date.now(),
        }
        break

      case 'memory_delete':
        delete memory.value[event.key]
        break

      case 'session_info':
        // Clear any stale approval dialogs from a previous connection
        pendingApprovals.value = []
        break

      case 'approval_required':
        pendingApprovals.value.push({
          request_id:    event.request_id,
          tool:          event.tool,
          args:          event.args,
          step_id:       event.step_id,
          message:       event.message || '',
          approval_type: event.approval_type || 'confirm',
        })
        break

      case 'user_question':
        pendingQuestions.value.push({
          request_id:   event.request_id,
          question:     event.question || '',
          options:      event.options || [],
          header:       event.header || '',
          multi_select: !!event.multi_select,
        })
        break

      case 'tool_result':
        // Remove any approval for this step once a result arrives (approved or denied)
        pendingApprovals.value = pendingApprovals.value.filter(
          a => a.step_id !== event.step_id
        )
        // Plan-tool results carry the full plan payload — surface it on
        // variables.plan.value so PlanPanel can render the full structure
        // (not just the truncated 120-char value_preview from variable_set).
        if (
          event.tool && event.tool.startsWith('plan_')
          && event.result && typeof event.result === 'object'
          && event.result.plan
        ) {
          variables.value['plan'] = {
            ...(variables.value['plan'] || {}),
            name: 'plan',
            var_type: 'json',
            value: event.result.plan,
            updatedAt: Date.now(),
          }
        }
        break

      case 'workflow_done':
        // Pull every variable produced by the workflow so PlanPanel and any
        // other variable-driven UI gets the FULL value (variable_set only
        // carries a truncated preview). The engine emits this as a flat
        // {name: value} dict in event.variables.
        if (event.variables && typeof event.variables === 'object') {
          for (const [name, value] of Object.entries(event.variables)) {
            const prev = variables.value[name] || {}
            variables.value[name] = {
              ...prev,
              name,
              value,
              updatedAt: Date.now(),
            }
          }
        }
        if (activeWorkflow.value) {
          activeWorkflow.value.status = 'done'
          activeWorkflow.value.finishedAt = Date.now()
        }
        break

      case 'done':
        if (activeWorkflow.value && activeWorkflow.value.status === 'running') {
          activeWorkflow.value.status = 'done'
        }
        pendingApprovals.value = []
        break

      case 'settings_info':
      case 'settings_update':
        setSettings(event)
        break

      case 'profile_info':
        profile.value = {
          name:      event.name,
          workspace: event.workspace,
          pet_id:    event.pet_id ?? null,
        }
        petState.value = { id: event.pet_id ?? null, state: 'idle', tickedAt: Date.now() }
        break

      case 'pet_changed':
        // Server-broadcast pet swap. Apply only if it's the active profile.
        if (event.profile === profile.value.name) {
          profile.value = { ...profile.value, pet_id: event.pet_id }
          petState.value = { id: event.pet_id, state: 'celebrate', tickedAt: Date.now() }
        }
        break

      case 'shell_process_start':
        shellProcesses.value[event.pid] = {
          pid: event.pid,
          command: event.command,
          running: true,
          exit_code: null,
          stdout: [],
          stderr: [],
          startedAt: Date.now(),
        }
        break

      case 'shell_output':
        if (shellProcesses.value[event.pid]) {
          const proc = shellProcesses.value[event.pid]
          if (event.stream === 'stdout') {
            proc.stdout.push(...event.lines)
            // Keep last 500 lines to avoid memory bloat
            if (proc.stdout.length > 500) proc.stdout = proc.stdout.slice(-500)
          } else {
            proc.stderr.push(...event.lines)
            if (proc.stderr.length > 500) proc.stderr = proc.stderr.slice(-500)
          }
          // Trigger reactivity
          shellProcesses.value[event.pid] = { ...proc }
        }
        break

      case 'shell_process_done':
        if (shellProcesses.value[event.pid]) {
          shellProcesses.value[event.pid] = {
            ...shellProcesses.value[event.pid],
            running: false,
            exit_code: event.exit_code,
            finishedAt: Date.now(),
          }
        }
        break
    }
  }

  function resolveApproval(request_id) {
    pendingApprovals.value = pendingApprovals.value.filter(a => a.request_id !== request_id)
  }

  function resolveQuestion(request_id) {
    pendingQuestions.value = pendingQuestions.value.filter(q => q.request_id !== request_id)
  }

  // Sync memory from REST snapshot
  function setMemorySnapshot(entries) {
    memory.value = {}
    for (const e of entries) {
      memory.value[e.key] = e
    }
  }

  // Sync variables from REST snapshot
  function setVariablesSnapshot(vars) {
    variables.value = {}
    for (const v of vars) {
      variables.value[v.name] = v
    }
  }

  function clearSession() {
    events.value = []
    activeWorkflow.value = null
    variables.value = {}
    memory.value = {}
    shellProcesses.value = {}
  }

  const eventCount = computed(() => events.value.length)
  const variableCount = computed(() => Object.keys(variables.value).length)
  const memoryCount = computed(() => Object.keys(memory.value).length)
  const shellCount = computed(() => Object.keys(shellProcesses.value).length)
  const runningShellCount = computed(() =>
    Object.values(shellProcesses.value).filter(p => p.running).length
  )

  return {
    events, activeWorkflow, variables, memory, shellProcesses,
    connected, sessionId, connectionError, profile, petState,
    extensionConnected,
    pendingApprovals, pendingQuestions,
    autonomy, toolPermissions, permissionCategories,
    setConnected, setConnectionError, setExtensionConnected, setAutonomy, setSettings,
    pushEvent, setMemorySnapshot, setVariablesSnapshot, clearSession,
    resolveApproval, resolveQuestion,
    eventCount, variableCount, memoryCount, shellCount, runningShellCount,
  }
})

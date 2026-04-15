import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

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

  // Shell processes: pid → { pid, command, running, exit_code, stdout, stderr }
  const shellProcesses = ref({})

  // Connection state
  const connected = ref(false)
  const sessionId = ref('')

  // Active profile
  const profile = ref({ name: 'default', workspace: '' })

  function setConnected(val, sid) {
    connected.value = val
    if (sid) sessionId.value = sid
  }

  function pushEvent(event) {
    // Keep last 500 events to avoid memory leak
    events.value.push({ ...event, _ts: Date.now() })
    if (events.value.length > 500) events.value.shift()

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

      case 'workflow_done':
        if (activeWorkflow.value) {
          activeWorkflow.value.status = 'done'
          activeWorkflow.value.finishedAt = Date.now()
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

      case 'tool_result':
        // Remove any approval for this step once a result arrives (approved or denied)
        pendingApprovals.value = pendingApprovals.value.filter(
          a => a.step_id !== event.step_id
        )
        break

      case 'done':
        if (activeWorkflow.value && activeWorkflow.value.status === 'running') {
          activeWorkflow.value.status = 'done'
        }
        pendingApprovals.value = []
        break

      case 'profile_info':
        profile.value = { name: event.name, workspace: event.workspace }
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
    connected, sessionId, profile,
    pendingApprovals,
    setConnected, pushEvent, setMemorySnapshot, setVariablesSnapshot, clearSession,
    resolveApproval,
    eventCount, variableCount, memoryCount, shellCount, runningShellCount,
  }
})

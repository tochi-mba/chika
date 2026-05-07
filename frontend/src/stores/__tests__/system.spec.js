/**
 * Unit tests for the system Pinia store — pet state machine, settings,
 * connection state, autonomy.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSystemStore } from '../system.js'

describe('system store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('starts disconnected with no events', () => {
    const s = useSystemStore()
    expect(s.connected).toBe(false)
    expect(s.events).toEqual([])
  })

  it('setConnected toggles connection flag', () => {
    const s = useSystemStore()
    s.setConnected(true, 'sess-x')
    expect(s.connected).toBe(true)
    s.setConnected(false)
    expect(s.connected).toBe(false)
  })

  it('pet state goes working on workflow_start', () => {
    const s = useSystemStore()
    s.pushEvent({ type: 'workflow_start', workflow_id: 'wf' })
    expect(s.petState.state).toBe('working')
  })

  it('pet state goes celebrate on workflow_done', () => {
    const s = useSystemStore()
    s.pushEvent({ type: 'workflow_start' })
    s.pushEvent({ type: 'workflow_done', workflow_id: 'wf', variables: {} })
    expect(s.petState.state).toBe('celebrate')
  })

  it('pet state goes sad on error', () => {
    const s = useSystemStore()
    s.pushEvent({ type: 'error', message: 'boom' })
    expect(s.petState.state).toBe('sad')
  })

  it('pet bubble reflects the running tool', () => {
    const s = useSystemStore()
    s.pushEvent({ type: 'tool_call', tool: 'shell_exec' })
    expect(s.petState.bubble).toMatch(/command/)
  })

  it('settings_info populates autonomy', () => {
    const s = useSystemStore()
    s.pushEvent({
      type: 'settings_info',
      autonomy: 'autonomous',
      categories: {},
      tool_permissions: {},
    })
    expect(s.autonomy).toBe('autonomous')
  })

  it('plan_archived event populates lastPlanArchive notice', () => {
    const s = useSystemStore()
    s.pushEvent({
      type: 'plan_archived',
      goal: 'Build a Powder Toy clone',
      reason: 'superseded by plan_set (2/4 tasks done)',
      tasks_total: 4,
      tasks_done: 2,
      auto: true,
      source: 'plan_set',
      history_count: 1,
    })
    expect(s.lastPlanArchive).toBeTruthy()
    expect(s.lastPlanArchive.goal).toBe('Build a Powder Toy clone')
    expect(s.lastPlanArchive.tasks_done).toBe(2)
    expect(s.lastPlanArchive.tasks_total).toBe(4)
    expect(s.lastPlanArchive.auto).toBe(true)
  })

  it('dismissPlanArchive clears the notice', () => {
    const s = useSystemStore()
    s.pushEvent({
      type: 'plan_archived',
      goal: 'g', reason: 'shipped',
      tasks_total: 1, tasks_done: 1, auto: false,
    })
    expect(s.lastPlanArchive).toBeTruthy()
    s.dismissPlanArchive()
    expect(s.lastPlanArchive).toBeNull()
  })
})

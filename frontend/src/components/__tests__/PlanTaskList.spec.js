/**
 * Component test for PlanTaskList — recursive plan rendering, status
 * cycling, nested sub-tasks.
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import PlanTaskList from '../PlanTaskList.vue'

const tasks = [
  {
    id: 't1', text: 'first', status: 'in_progress',
    subtasks: [
      { id: 't1.1', text: 'sub one', status: 'in_progress', subtasks: [] },
      { id: 't1.2', text: 'sub two', status: 'pending', subtasks: [] },
    ],
  },
  { id: 't2', text: 'second', status: 'done', subtasks: [] },
  { id: 't3', text: 'third',  status: 'pending', subtasks: [] },
]

describe('PlanTaskList', () => {
  it('renders all top-level tasks', () => {
    const wrapper = mount(PlanTaskList, { props: { tasks } })
    expect(wrapper.text()).toContain('first')
    expect(wrapper.text()).toContain('second')
    expect(wrapper.text()).toContain('third')
  })

  it('renders nested subtasks recursively', () => {
    const wrapper = mount(PlanTaskList, { props: { tasks } })
    expect(wrapper.text()).toContain('sub one')
    expect(wrapper.text()).toContain('sub two')
  })

  it('shows ✓ for done tasks', () => {
    const wrapper = mount(PlanTaskList, { props: { tasks } })
    const ticks = wrapper.findAll('.ptl-done')
    expect(ticks.length).toBeGreaterThan(0)
  })

  it('shows … for in_progress tasks', () => {
    const wrapper = mount(PlanTaskList, { props: { tasks } })
    const inprog = wrapper.findAll('.ptl-in_progress')
    expect(inprog.length).toBeGreaterThan(0)
  })

  it('clicking the tick emits toggle with next status', async () => {
    const wrapper = mount(PlanTaskList, { props: { tasks } })
    const buttons = wrapper.findAll('.ptl-tick')
    await buttons[0].trigger('click')
    const events = wrapper.emitted('toggle')
    expect(events).toBeTruthy()
    // First task is in_progress → next should be done.
    expect(events[0]).toEqual(['t1', 'done'])
  })

  it('cycles pending → in_progress', async () => {
    const wrapper = mount(PlanTaskList, { props: { tasks } })
    const buttons = wrapper.findAll('.ptl-tick')
    // Find the t3 button (pending).
    await buttons[buttons.length - 1].trigger('click')
    const events = wrapper.emitted('toggle')
    const last = events[events.length - 1]
    expect(last).toEqual(['t3', 'in_progress'])
  })

  it('renders empty list without crashing', () => {
    const wrapper = mount(PlanTaskList, { props: { tasks: [] } })
    expect(wrapper.findAll('.ptl-row').length).toBe(0)
  })
})

/**
 * Chat-sidebar e2e — list rendering, new-chat button, switch chat,
 * delete chat.
 *
 * The sidebar reads the chat list from the chats store, populated by
 * the WS event ``chat_list`` (shape: ``{type, chats: [...], profile}``).
 *
 * User actions dispatch:
 *   - new_chat       → ``{type: 'new_chat'}``
 *   - switch_chat    → ``{type: 'switch_chat', chat_id}``
 *   - delete_chat    → ``{type: 'delete_chat', chat_id}``
 */
import { test, expect, waitForApp, pushEvent, sentMessages } from './_fixtures.js'


function chatListPayload() {
  return {
    type:    'chat_list',
    profile: 'default',
    chats: [
      { id: 'chat-1', title: 'Earlier conversation', updated_at: 1700000000 },
      { id: 'chat-2', title: 'Latest planning sesh', updated_at: 1700001000 },
      { id: 'chat-3', title: 'Build Netflix clone',  updated_at: 1700002000 },
    ],
  }
}


test.describe('chat sidebar', () => {
  test.beforeEach(async ({ chikaPage }) => {
    await chikaPage.goto('/')
    await waitForApp(chikaPage)
    await pushEvent(chikaPage, chatListPayload())
  })


  test('renders every chat title in the list', async ({ chikaPage }) => {
    for (const title of [
      'Earlier conversation', 'Latest planning sesh', 'Build Netflix clone',
    ]) {
      await expect(
        chikaPage.locator(`.chat-item:has-text("${title}")`).first(),
      ).toBeVisible({ timeout: 4000 })
    }
  })


  test('"New chat" button dispatches new_chat WS message', async ({ chikaPage }) => {
    await chikaPage.locator('button.new-btn:has-text("New chat")').first().click()
    const msgs = await sentMessages(chikaPage)
    expect(msgs.some(m => m && m.type === 'new_chat')).toBe(true)
  })


  test('clicking a chat row dispatches switch_chat with that chat id', async ({ chikaPage }) => {
    await chikaPage
      .locator('.chat-item:has-text("Latest planning sesh")')
      .first()
      .click()
    const msgs = await sentMessages(chikaPage)
    const switchMsg = msgs.find(m => m && m.type === 'switch_chat')
    expect(switchMsg).toBeTruthy()
    expect(switchMsg.chat_id).toBe('chat-2')
  })


  test('hovering a chat reveals the delete (X) button', async ({ chikaPage }) => {
    const row = chikaPage.locator('.chat-item:has-text("Build Netflix clone")').first()
    await row.hover()
    const del = row.locator('.delete-btn').first()
    // Visible per CSS: `.chat-item:hover .delete-btn { opacity: 1 }`.
    await expect(del).toBeVisible({ timeout: 2000 })
  })


  test('delete button dispatches delete_chat with the right chat id', async ({ chikaPage }) => {
    const row = chikaPage.locator('.chat-item:has-text("Earlier conversation")').first()
    await row.hover()
    await row.locator('.delete-btn').first().click()
    const msgs = await sentMessages(chikaPage)
    const delMsg = msgs.find(m => m && m.type === 'delete_chat')
    expect(delMsg).toBeTruthy()
    expect(delMsg.chat_id).toBe('chat-1')
  })
})

import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useChatsStore = defineStore('chats', () => {
  const chatList   = ref([])
  const profile    = ref('')

  // Called when server sends chat_list event
  function setChats(data) {
    chatList.value = data.chats || []
    profile.value  = data.profile || ''
  }

  return { chatList, profile, setChats }
})

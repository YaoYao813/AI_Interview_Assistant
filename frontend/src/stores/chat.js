import { ref, computed, watch } from 'vue'
import { defineStore } from 'pinia'

const STORAGE_KEY = 'ai_interview_chats'

function loadFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

export const useChatStore = defineStore('chat', () => {
  // ===== 状态 =====
  const conversations = ref(loadFromStorage())
  const activeId = ref(conversations.value[0]?.id || null)

  // ===== 计算属性 =====
  const activeConversation = computed(() =>
    conversations.value.find(c => c.id === activeId.value) || null
  )

  const sortedConversations = computed(() =>
    [...conversations.value].sort((a, b) => b.updatedAt - a.updatedAt)
  )

  // ===== 持久化 =====
  function persist() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.value))
  }

  // ===== 对话 CRUD =====

  function createConversation() {
    const now = Date.now()
    const conv = {
      id: now.toString(36) + Math.random().toString(36).slice(2, 6),
      title: '新对话',
      messages: [],
      createdAt: now,
      updatedAt: now,
    }
    conversations.value.unshift(conv)
    activeId.value = conv.id
    persist()
    return conv
  }

  function deleteConversation(id) {
    const idx = conversations.value.findIndex(c => c.id === id)
    if (idx === -1) return
    conversations.value.splice(idx, 1)
    if (activeId.value === id) {
      activeId.value = conversations.value[0]?.id || null
    }
    persist()
  }

  function switchConversation(id) {
    if (conversations.value.find(c => c.id === id)) {
      activeId.value = id
    }
  }

  function ensureActiveConversation() {
    if (!activeConversation.value) {
      createConversation()
    }
  }

  // ===== 消息操作 =====

  function addMessage(role, content, sources = [], conversationId = null) {
    const conv = conversationId
      ? conversations.value.find(c => c.id === conversationId)
      : activeConversation.value
    if (!conv) return
    conv.messages.push({ role, content, sources, timestamp: Date.now(), isLoading: false })
    conv.updatedAt = Date.now()
    // 用第一条用户消息的前 20 字作为标题
    if (conv.title === '新对话' && role === 'user') {
      conv.title = content.slice(0, 20) + (content.length > 20 ? '...' : '')
    }
    persist()
  }

  function getHistoryForApi(maxMessages = 10, conversationId = null) {
    const conv = conversationId
      ? conversations.value.find(c => c.id === conversationId)
      : activeConversation.value
    if (!conv || conv.messages.length === 0) return []
    // 返回最近 N 条（不含当前正在发送的）
    return conv.messages.slice(-maxMessages).map(m => ({
      role: m.role,
      content: m.content,
    }))
  }

  function updateMessage(conversationId, index, patch) {
    const conv = conversations.value.find(c => c.id === conversationId)
    if (!conv || !conv.messages[index]) return
    Object.assign(conv.messages[index], patch)
    conv.updatedAt = Date.now()
    persist()
  }

  return {
    conversations,
    activeId,
    activeConversation,
    sortedConversations,
    createConversation,
    deleteConversation,
    switchConversation,
    ensureActiveConversation,
    addMessage,
    updateMessage,
    getHistoryForApi,
  }
})

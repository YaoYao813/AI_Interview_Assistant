import { ref, computed, watch } from 'vue'
import { defineStore } from 'pinia'

const STORAGE_KEY = 'ai_interview_chats'
// 与 stores/conversation.js 的工厂保持同一上限。整包 JSON.stringify 写 localStorage，
// 攒多了会撞配额：那时写入开始静默失败，用户看着还能聊，刷新后新消息全没了。
const MAX_CONVERSATIONS = 20

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
  // 流式回答逐 token 触发写入，这边节流到每 PERSIST_THROTTLE_MS 最多一次。
  // 写入失败（localStorage 配额溢出）只告警不抛出：异常若从 persist 冒出去，
  // 会冲出流式读取循环并被外层 catch 吞掉，表现为回答打到一半突然中断。
  const PERSIST_THROTTLE_MS = 300
  let persistTimer = null

  function writeToStorage() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.value))
    } catch (e) {
      console.warn('[chat] 会话持久化失败，可能已超出 localStorage 配额：', e)
    }
  }

  function persist() {
    if (persistTimer) return
    persistTimer = setTimeout(() => {
      persistTimer = null
      writeToStorage()
    }, PERSIST_THROTTLE_MS)
  }

  // 结构性操作与流结束时用：立即落盘，不等节流窗口
  function flushPersist() {
    if (persistTimer) {
      clearTimeout(persistTimer)
      persistTimer = null
    }
    writeToStorage()
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
    if (conversations.value.length > MAX_CONVERSATIONS) {
      conversations.value.splice(MAX_CONVERSATIONS)
    }
    activeId.value = conv.id
    flushPersist()
    return conv
  }

  function deleteConversation(id) {
    const idx = conversations.value.findIndex(c => c.id === id)
    if (idx === -1) return
    conversations.value.splice(idx, 1)
    if (activeId.value === id) {
      activeId.value = conversations.value[0]?.id || null
    }
    flushPersist()
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
    flushPersist,
  }
})

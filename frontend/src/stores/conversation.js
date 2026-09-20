import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

const MAX_CONVERSATIONS = 20

function loadFromStorage(storageKey) {
  try {
    const raw = localStorage.getItem(storageKey)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function genId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
}

/**
 * 通用「历史会话」store 工厂
 * 提供会话列表管理（新建/切换/删除/更新/persist），各模块用不同 storeId + storageKey 隔离。
 * defaults 定义模块会话对象的默认字段，createConversation(initial) 时合并。
 */
export function createConversationStore(storeId, storageKey, defaults = {}) {
  return defineStore(storeId, () => {
    const conversations = ref(loadFromStorage(storageKey))
    const activeId = ref(conversations.value[0]?.id || null)

    const activeConversation = computed(() =>
      conversations.value.find(c => c.id === activeId.value) || null
    )

    const sortedConversations = computed(() =>
      [...conversations.value].sort((a, b) => b.updatedAt - a.updatedAt)
    )

    function persist() {
      // 配额溢出只告警不抛出。这里不是流式热路径（三个模块都刻意把流式内容攒在
      // 组件内、流结束才写一次），但异常若冒出去，会打断调用它的业务流程。
      try {
        localStorage.setItem(storageKey, JSON.stringify(conversations.value))
      } catch (e) {
        console.warn(`[${storeId}] 会话持久化失败，可能已超出 localStorage 配额：`, e)
      }
    }

    function createConversation(initial = {}) {
      const now = Date.now()
      const conv = {
        id: genId(),
        createdAt: now,
        updatedAt: now,
        ...defaults,
        ...initial,
      }
      conversations.value.unshift(conv)
      if (conversations.value.length > MAX_CONVERSATIONS) {
        conversations.value.splice(MAX_CONVERSATIONS)
      }
      activeId.value = conv.id
      persist()
      return conv
    }

    function switchConversation(id) {
      if (conversations.value.find(c => c.id === id)) {
        activeId.value = id
      }
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

    function updateConversation(id, patch) {
      const conv = conversations.value.find(c => c.id === id)
      if (!conv) return
      Object.assign(conv, patch)
      conv.updatedAt = Date.now()
      persist()
    }

    function ensureActiveConversation() {
      if (!activeConversation.value) {
        createConversation()
      }
    }

    return {
      conversations,
      activeId,
      activeConversation,
      sortedConversations,
      persist,
      createConversation,
      switchConversation,
      deleteConversation,
      updateConversation,
      ensureActiveConversation,
    }
  })
}

<template>
  <div class="knowledge-chat">
    <!-- 二级侧栏：历史对话 -->
    <ConversationSidebar
      :conversations="chatStore.sortedConversations"
      :active-id="chatStore.activeId"
      :title-of="titleOf"
      :summary-of="summaryOf"
      workspace-icon="chat"
      workspace-name="知识问答"
      empty-icon="chat"
      empty-title="暂无对话"
      empty-desc="点击上方按钮开始新对话"
      @create="chatStore.createConversation()"
      @switch="chatStore.switchConversation"
      @delete="handleDeleteConversation"
    >
      <template #footer>
        <span class="stat-line">
          <LineIcon name="book" :size="13" /> {{ stats.document_count }} 文档 |
          <LineIcon name="grid" :size="13" /> {{ stats.chunk_count }} 块
        </span>
      </template>
    </ConversationSidebar>

    <!-- 右侧聊天区 -->
    <div class="chat-main">
      <!-- 空状态 -->
      <EmptyState
        v-if="!chatStore.activeConversation"
        icon="chat"
        title="选择或创建一个对话"
        description="基于知识库的 AI 智能问答"
      />

      <!-- 对话内容 -->
      <template v-else>
        <div class="chat-messages" ref="msgContainer">
          <EmptyState
            v-if="chatStore.activeConversation.messages.length === 0"
            icon="inbox"
            title="开始提问"
            description="输入技术问题，AI 将基于你的知识库回答"
          />

          <ChatMessage
            v-for="(msg, idx) in chatStore.activeConversation.messages"
            :key="idx"
            :role="msg.role"
            :content="msg.content"
            :sources="msg.sources"
            :isLoading="msg.isLoading"
          />
        </div>

        <ChatInput :loading="isLoading" @send="handleSend" />
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { chatQuery, getKnowledgeStatistics } from '@/api/knowledge'
import { useChatStore } from '@/stores/chat'
import ChatMessage from '@/components/chat/ChatMessage.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ConversationSidebar from '@/components/common/ConversationSidebar.vue'
import LineIcon from '@/components/common/LineIcon.vue'

const chatStore = useChatStore()
const loadingConvIds = ref(new Set())
const isLoading = computed(() => loadingConvIds.value.has(chatStore.activeId))
const msgContainer = ref(null)
const stats = ref({ document_count: 0, chunk_count: 0 })

// convId -> AbortController：删除会话、离开页面时掐断仍在读的流。
// 切换会话不掐断——loading 已是会话级的，后台流跑完属于预期行为。
const streamControllers = new Map()

function abortStream(convId) {
  const controller = streamControllers.get(convId)
  if (controller) {
    controller.abort()
    streamControllers.delete(convId)
  }
}

function handleDeleteConversation(id) {
  abortStream(id)
  chatStore.deleteConversation(id)
}

onUnmounted(() => {
  for (const controller of streamControllers.values()) controller.abort()
  streamControllers.clear()
})

onMounted(async () => {
  chatStore.ensureActiveConversation()
  try {
    const res = await getKnowledgeStatistics()
    stats.value = res.data || {}
  } catch { /* ignore */ }
})

async function handleSend({ question, top_k, threshold, stream }) {
  const convId = chatStore.activeId
  if (loadingConvIds.value.has(convId) || !chatStore.activeConversation) return

  chatStore.addMessage('user', question, [], convId)
  scrollToBottom()
  loadingConvIds.value.add(convId)

  const history = chatStore.getHistoryForApi(10, convId)

  if (stream) {
    await sendStream(question, top_k, threshold, history, convId)
  } else {
    try {
      const res = await chatQuery({ question, top_k, threshold, history })
      const data = res.data || {}
      chatStore.addMessage('assistant', data.answer || '', data.sources || [], convId)
    } catch {
      chatStore.addMessage('assistant', '请求失败，请检查后端服务。', [], convId)
    }
  }

  loadingConvIds.value.delete(convId)
  await nextTick()
  scrollToBottom()
}

async function sendStream(question, top_k, threshold, history, convId) {
  chatStore.addMessage('assistant', '', [], convId)
  const conv = chatStore.conversations.find(c => c.id === convId)
  const msgIndex = conv.messages.length - 1
  chatStore.updateMessage(convId, msgIndex, { isLoading: true })

  const controller = new AbortController()
  streamControllers.set(convId, controller)
  let aborted = false

  try {
    const response = await fetch('/api/v1/rag/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, top_k, threshold, history }),
      signal: controller.signal,
    })
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let sep
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const rawEvent = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        for (const line of rawEvent.split('\n')) {
          if (!line.startsWith('data: ')) continue
          let evt
          try { evt = JSON.parse(line.slice(6)) } catch { continue }
          applyStreamEvent(evt, convId, msgIndex)
        }
      }
    }
  } catch (e) {
    // 主动中断不是错误，不必上报；其余异常必须留痕，否则问题无从定位
    if (e?.name === 'AbortError') {
      aborted = true
    } else {
      console.warn('[KnowledgeChat] 流式请求中断：', e)
    }
  } finally {
    streamControllers.delete(convId)
    const msg = chatStore.conversations.find(c => c.id === convId)?.messages[msgIndex]
    const patch = { isLoading: false }
    if (msg && !msg.content) {
      patch.content = aborted ? '（已停止生成）' : '请求失败，请检查后端服务。'
    }
    chatStore.updateMessage(convId, msgIndex, patch)
    // 流结束后立刻落盘，不等节流窗口
    chatStore.flushPersist()
  }
}

function applyStreamEvent(evt, convId, msgIndex) {
  const conv = chatStore.conversations.find(c => c.id === convId)
  const msg = conv?.messages[msgIndex]
  if (!msg) return

  if (evt.type === 'sources') {
    chatStore.updateMessage(convId, msgIndex, { sources: evt.data || [] })
  } else if (evt.type === 'token') {
    chatStore.updateMessage(convId, msgIndex, { content: msg.content + (evt.data || '') })
  } else if (evt.type === 'done') {
    chatStore.updateMessage(convId, msgIndex, { isLoading: false })
  }
}

function scrollToBottom() {
  if (msgContainer.value) {
    msgContainer.value.scrollTop = msgContainer.value.scrollHeight
  }
}

function titleOf(conv) {
  return conv.title || '新对话'
}

function summaryOf(conv) {
  const msgs = conv.messages || []
  const last = msgs[msgs.length - 1]
  if (!last) return ''
  const c = last.content || ''
  return c.length > 20 ? c.slice(0, 20) + '...' : c
}
</script>

<style scoped>
.knowledge-chat { height: 100%; display: flex; }

/* 聊天区 */
.chat-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.chat-messages { flex: 1; overflow-y: auto; padding: 0 24px; }

.stat-line { display: inline-flex; align-items: center; gap: 4px; }
</style>

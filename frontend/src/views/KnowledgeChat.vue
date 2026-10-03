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

        <ChatInput :loading="isLoading" @send="handleSend" @stop="handleStop" />
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, onDeactivated, nextTick } from 'vue'
import { chatQuery, getKnowledgeStatistics, RAG_CHAT_STREAM_URL } from '@/api/knowledge'
import { streamSSE } from '@/utils/sse'
import { useChatStore } from '@/stores/chat'
import ChatMessage from '@/components/chat/ChatMessage.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ConversationSidebar from '@/components/common/ConversationSidebar.vue'
import LineIcon from '@/components/common/LineIcon.vue'

const chatStore = useChatStore()
// convId -> AbortController。这一份映射同时承担「该会话是否有请求在跑」，
// 所以必须是响应式的、由它派生 isLoading，不能再另开一个平行的 Set 记录 loading。
// 只放 AbortController：Vue 不会把它包成响应式代理，下面两处 === 身份比较才成立
// （换成普通对象会被代理，比较恒为 false，finally 就永远清不掉、loading 卡死）。
const streamControllers = ref(new Map())
const isLoading = computed(() => streamControllers.value.has(chatStore.activeId))
const msgContainer = ref(null)
const stats = ref({ document_count: 0, chunk_count: 0 })

function abortStream(convId) {
  const controller = streamControllers.value.get(convId)
  if (controller) {
    controller.abort()
    streamControllers.value.delete(convId)
  }
}

function handleStop() {
  abortStream(chatStore.activeId)
}

function handleDeleteConversation(id) {
  abortStream(id)
  chatStore.deleteConversation(id)
}

// 切换会话刻意不断开：loading 是会话级的，后台跑完落回自己的会话属于预期行为。
// 离开页面则要断开，否则流会在后台继续跑、白白消耗 token。
// 注意 AppLayout 外面套了 <keep-alive>：路由切走只触发 deactivated、不触发 unmounted，
// 所以断开必须挂在 onDeactivated 上（onUnmounted 只在整体卸载时兜底）。
function abortAllStreams() {
  for (const controller of streamControllers.value.values()) controller.abort()
  streamControllers.value.clear()
}
onDeactivated(abortAllStreams)
onUnmounted(abortAllStreams)

onMounted(async () => {
  chatStore.ensureActiveConversation()
  try {
    const res = await getKnowledgeStatistics()
    stats.value = res.data || {}
  } catch { /* ignore */ }
})

async function handleSend({ question, top_k, threshold, stream }) {
  const convId = chatStore.activeId
  if (!chatStore.activeConversation) return

  // 同一会话还有请求在跑：先掐断旧的，让新问题立刻发出去
  abortStream(convId)

  const controller = new AbortController()
  streamControllers.value.set(convId, controller)

  chatStore.addMessage('user', question, [], convId)
  scrollToBottom()

  const history = chatStore.getHistoryForApi(10, convId)

  if (stream) {
    await sendStream(question, top_k, threshold, history, convId, controller)
  } else {
    try {
      const res = await chatQuery(
        { question, top_k, threshold, history },
        { signal: controller.signal },
      )
      const data = res.data || {}
      chatStore.addMessage('assistant', data.answer || '', data.sources || [], convId)
    } catch (e) {
      // 被新问题掐断的请求不提示失败
      const aborted = e?.name === 'CanceledError' || e?.name === 'AbortError'
      if (!aborted) {
        chatStore.addMessage('assistant', '请求失败，请检查后端服务。', [], convId)
      }
    } finally {
      if (streamControllers.value.get(convId) === controller) {
        streamControllers.value.delete(convId)
      }
    }
  }

  await nextTick()
  scrollToBottom()
}

async function sendStream(question, top_k, threshold, history, convId, controller) {
  chatStore.addMessage('assistant', '', [], convId)
  const conv = chatStore.conversations.find(c => c.id === convId)
  const msgIndex = conv.messages.length - 1
  chatStore.updateMessage(convId, msgIndex, { isLoading: true })

  let aborted = false
  let lost = false
  let failed = false

  try {
    await streamSSE(
      RAG_CHAT_STREAM_URL,
      { question, top_k, threshold, history },
      (evt) => applyStreamEvent(evt, convId, msgIndex),
      { signal: controller.signal },
    )
  } catch (e) {
    // 主动中断不是错误，不必上报；其余异常必须留痕，否则问题无从定位
    if (e?.name === 'AbortError') {
      aborted = true
    } else if (e?.idleTimeout) {
      lost = true
      console.warn('[KnowledgeChat] 流式请求空闲超时：', e)
    } else {
      failed = true
      console.warn('[KnowledgeChat] 流式请求中断：', e)
    }
  } finally {
    // 只有当映射里还是自己时才清理：新一轮请求可能已经顶掉了这个位置
    if (streamControllers.value.get(convId) === controller) {
      streamControllers.value.delete(convId)
    }
    const msg = chatStore.conversations.find(c => c.id === convId)?.messages[msgIndex]
    const patch = { isLoading: false }
    if (msg) {
      const tail = aborted
        ? '已停止生成，回答不完整'
        : lost
          ? '连接空闲超时，已中断'
          : failed
            ? '响应中断，回答可能不完整'
            : ''
      if (!msg.content) {
        // 一个字都没生成：给一句能看懂的话，别留一个空气泡
        patch.content = aborted
          ? '（已停止生成）'
          : lost
            ? '（连接空闲超时，已中断）'
            : failed
              ? '请求失败，请检查后端服务。'
              : ''
      } else if (tail) {
        // 已经生成了一部分：必须留下断点标记，否则半截回答看起来和完整回答一模一样
        patch.content = `${msg.content}\n\n（${tail}）`
      }
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

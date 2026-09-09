<template>
  <div class="knowledge-chat">
    <!-- 左侧对话列表 -->
    <aside class="chat-sidebar">
      <div class="sidebar-header">
        <el-button type="primary" @click="chatStore.createConversation()" style="width:100%">
          ＋ 新对话
        </el-button>
      </div>
      <div class="conversation-list">
        <div
          v-for="conv in chatStore.sortedConversations"
          :key="conv.id"
          class="conv-item"
          :class="{ active: conv.id === chatStore.activeId }"
          @click="chatStore.switchConversation(conv.id)"
        >
          <span class="conv-title">{{ conv.title }}</span>
          <span class="conv-date">{{ formatDate(conv.updatedAt) }}</span>
          <el-popconfirm
            title="删除此对话？"
            @confirm="chatStore.deleteConversation(conv.id)"
            @click.stop
          >
            <template #reference>
              <span class="conv-delete" @click.stop>🗑</span>
            </template>
          </el-popconfirm>
        </div>
        <EmptyState
          v-if="chatStore.conversations.length === 0"
          icon="💬"
          title="暂无对话"
          description="点击上方按钮开始新对话"
        />
      </div>
      <div class="sidebar-footer">
        <span>📚 {{ stats.document_count }} 文档 | 🧩 {{ stats.chunk_count }} 块</span>
      </div>
    </aside>

    <!-- 右侧聊天区 -->
    <div class="chat-main">
      <!-- 空状态 -->
      <EmptyState
        v-if="!chatStore.activeConversation"
        icon="💬"
        title="选择或创建一个对话"
        description="基于知识库的 AI 智能问答"
      />

      <!-- 对话内容 -->
      <template v-else>
        <div class="chat-messages" ref="msgContainer">
          <EmptyState
            v-if="chatStore.activeConversation.messages.length === 0"
            icon="📭"
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
import { ref, computed, onMounted, nextTick } from 'vue'
import { chatQuery, getKnowledgeStatistics } from '@/api/knowledge'
import { useChatStore } from '@/stores/chat'
import ChatMessage from '@/components/chat/ChatMessage.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const chatStore = useChatStore()
const loadingConvIds = ref(new Set())
const isLoading = computed(() => loadingConvIds.value.has(chatStore.activeId))
const msgContainer = ref(null)
const stats = ref({ document_count: 0, chunk_count: 0 })

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

  try {
    const response = await fetch('/api/v1/rag/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, top_k, threshold, history }),
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
  } catch {
    // 出错时保留已生成内容
  } finally {
    const msg = chatStore.conversations.find(c => c.id === convId)?.messages[msgIndex]
    const patch = { isLoading: false }
    if (msg && !msg.content) patch.content = '请求失败，请检查后端服务。'
    chatStore.updateMessage(convId, msgIndex, patch)
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

function formatDate(ts) {
  const d = new Date(ts)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
</script>

<style scoped>
.knowledge-chat { height: 100%; display: flex; }

/* 侧栏 */
.chat-sidebar {
  width: 260px; background: var(--bg-white); border-right: 1px solid var(--border-color);
  display: flex; flex-direction: column; flex-shrink: 0;
}
.sidebar-header { padding: 16px; border-bottom: 1px solid var(--border-color); }
.conversation-list { flex: 1; overflow-y: auto; }
.conv-item {
  display: grid; grid-template-columns: 1fr 24px; grid-template-rows: auto auto;
  padding: 12px 16px; cursor: pointer; border-bottom: 1px solid #f0f0f0;
  transition: background 0.15s;
}
.conv-item:hover { background: var(--bg-page); }
.conv-item.active { background: var(--primary-light); border-left: 3px solid var(--primary); }
.conv-title {
  font-size: 14px; font-weight: 500; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; grid-column: 1; grid-row: 1;
}
.conv-date { font-size: 12px; color: var(--text-secondary); grid-column: 1; grid-row: 2; margin-top: 2px; }
.conv-delete {
  font-size: 12px; cursor: pointer; opacity: 0; transition: opacity 0.15s;
  grid-column: 2; grid-row: 1 / 3; align-self: center; text-align: center;
}
.conv-item:hover .conv-delete { opacity: 0.6; }
.conv-item:hover .conv-delete:hover { opacity: 1; }
.sidebar-footer {
  padding: 10px 16px; font-size: 12px; color: var(--text-secondary);
  border-top: 1px solid var(--border-color);
}

/* 聊天区 */
.chat-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.chat-messages { flex: 1; overflow-y: auto; padding: 0 24px; }
</style>

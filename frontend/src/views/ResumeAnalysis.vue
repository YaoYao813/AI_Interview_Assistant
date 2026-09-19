<template>
  <div class="resume-analysis">
    <!-- 左侧历史对话列表 -->
    <ConversationSidebar
      :conversations="store.sortedConversations"
      :active-id="store.activeId"
      :title-of="titleOf"
      :summary-of="summaryOf"
      workspace-icon="file"
      workspace-name="简历分析"
      empty-icon="file"
      empty-title="暂无历史对话"
      empty-desc="上传简历或点击上方新建对话"
      @create="store.createConversation()"
      @switch="store.switchConversation"
      @delete="store.deleteConversation"
    />

    <!-- 右侧对话区 -->
    <div class="resume-main">
      <!-- 无活跃会话 -->
      <EmptyState
        v-if="!store.activeConversation"
        icon="file"
        title="选择或创建一个对话"
        description="上传简历，AI 将深度分析并提供优化建议"
      />

      <template v-else>
        <!-- 上传状态 -->
        <div v-if="!result && !loading" class="upload-state">
          <div class="upload-card">
            <div class="upload-icon"><LineIcon name="file" :size="48" :stroke-width="1.3" /></div>
            <h2>简历智能分析</h2>
            <p>上传简历文件，AI 将从面试官视角深度分析你的简历</p>
            <div class="upload-features">
              <div class="feature"><LineIcon class="feature-icon" name="search" :size="22" :stroke-width="1.4" /><span>亮点挖掘</span></div>
              <div class="feature"><LineIcon class="feature-icon" name="alert" :size="22" :stroke-width="1.4" /><span>不足诊断</span></div>
              <div class="feature"><LineIcon class="feature-icon" name="target" :size="22" :stroke-width="1.4" /><span>岗位匹配</span></div>
              <div class="feature"><LineIcon class="feature-icon" name="lightbulb" :size="22" :stroke-width="1.4" /><span>追问优化</span></div>
            </div>
            <el-upload
              class="upload-trigger"
              drag
              :auto-upload="false"
              :show-file-list="false"
              :on-change="handleFileSelect"
              accept=".pdf,.docx,.doc,.txt,.md"
            >
              <div class="upload-drop-zone">
                <span class="upload-drop-icon"><LineIcon name="folder" :size="40" :stroke-width="1.3" /></span>
                <span>将简历拖到此处，或 <em>点击上传</em></span>
                <span class="upload-hint">支持 PDF、Word、TXT、Markdown，最大 20MB</span>
              </div>
            </el-upload>
          </div>
        </div>

        <!-- 分析中 -->
        <div v-else-if="loading" class="analyzing-state">
          <el-skeleton :rows="4" animated style="width: 60%; max-width: 520px" />
          <p class="analyzing-tip"><LineIcon name="bot" :size="15" /> AI 正在分析简历，预计需要 10~20 秒...</p>
        </div>

        <!-- 对话模式 -->
        <div v-else class="chat-state">
          <!-- 顶部工具栏 -->
          <div class="chat-toolbar">
            <span class="toolbar-title"><LineIcon name="paperclip" :size="14" /> {{ filename }}</span>
          </div>

          <!-- 消息列表 -->
          <div class="chat-messages" ref="msgContainer">
            <!-- 系统欢迎语 -->
            <div v-if="result" class="system-tip">
              <LineIcon name="bot" :size="14" /> 简历分析完成，你可以继续追问：
              <span class="tip-tag" @click="question = '这个项目经历怎么写更好？'">"这个项目经历怎么写更好？"</span>
              <span class="tip-tag" @click="question = '我应该补充哪些技能？'">"我应该补充哪些技能？"</span>
              <span class="tip-tag" @click="question = '面试官会问什么问题？'">"面试官会问什么问题？"</span>
            </div>

            <ChatMessage
              v-for="(msg, idx) in messages"
              :key="idx"
              :role="msg.role"
              :content="msg.content"
              :sources="[]"
              :is-loading="false"
            />

            <!-- 分析报告卡片 -->
            <div v-if="result" class="report-card">
              <!-- 解析错误 -->
              <el-alert
                v-if="result._parse_error"
                title="AI 返回格式异常，部分结果可能不完整"
                type="warning" show-icon :closable="false"
                style="margin-bottom: 16px"
              />

              <section class="result-section">
                <h3 class="section-title"><LineIcon name="clipboard" :size="16" /> 简历概况</h3>
                <el-descriptions :column="2" border size="default">
                  <el-descriptions-item label="经验年限">{{ result.overview?.years_of_experience || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="当前职位">{{ result.overview?.current_role || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="学历背景" :span="2">{{ result.overview?.education || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="核心技术栈" :span="2">
                    <el-tag v-for="t in result.overview?.core_tech_stack || []" :key="t" style="margin-right:6px;margin-bottom:4px">{{ t }}</el-tag>
                    <span v-if="!result.overview?.core_tech_stack?.length">-</span>
                  </el-descriptions-item>
                </el-descriptions>
              </section>

              <section class="result-section">
                <h3 class="section-title"><LineIcon name="check" :size="16" /> 优势亮点</h3>
                <div v-if="result.strengths?.length" class="card-list">
                  <div v-for="(item, idx) in result.strengths" :key="idx" class="info-card strength">
                    <div class="card-header">
                      <span class="card-index">{{ idx + 1 }}</span>
                      <span class="card-point">{{ item.point }}</span>
                    </div>
                    <div class="card-detail"><span class="detail-label"><LineIcon name="note" :size="13" /> 简历证据：</span>{{ item.evidence }}</div>
                    <div class="card-detail"><span class="detail-label"><LineIcon name="chat" :size="13" /> 面试价值：</span>{{ item.impact }}</div>
                  </div>
                </div>
                <el-empty v-else description="暂无数据" :image-size="40" />
              </section>

              <section class="result-section">
                <h3 class="section-title"><LineIcon name="alert" :size="16" /> 不足之处</h3>
                <div v-if="result.weaknesses?.length" class="card-list">
                  <div v-for="(item, idx) in result.weaknesses" :key="idx" class="info-card weakness">
                    <div class="card-header">
                      <span class="card-index">{{ idx + 1 }}</span>
                      <span class="card-point">{{ item.point }}</span>
                    </div>
                    <div class="card-detail"><span class="detail-label"><LineIcon name="search" :size="13" /> 问题分析：</span>{{ item.reason }}</div>
                    <div class="card-detail"><span class="detail-label"><LineIcon name="lightbulb" :size="13" /> 改进建议：</span>{{ item.suggestion }}</div>
                  </div>
                </div>
                <el-empty v-else description="暂无数据" :image-size="40" />
              </section>

              <section class="result-section">
                <h3 class="section-title"><LineIcon name="target" :size="16" /> 岗位匹配推荐</h3>
                <div v-if="sortedJobMatches.length" class="job-match-list">
                  <div v-for="(job, idx) in sortedJobMatches" :key="idx" class="job-card">
                    <div class="job-header">
                      <span class="job-role">{{ job.role }}</span>
                      <el-progress :percentage="job.score || 0" :color="scoreColor(job.score)" :stroke-width="8" style="width:120px" />
                    </div>
                    <div class="job-reason"><span class="detail-label">推荐理由：</span>{{ job.reason }}</div>
                    <div v-if="job.gap_skills?.length" class="job-gaps">
                      <span class="detail-label">需要补充：</span>
                      <el-tag v-for="s in job.gap_skills" :key="s" type="warning" size="small" style="margin-right:6px">{{ s }}</el-tag>
                    </div>
                  </div>
                </div>
                <el-empty v-else description="暂无数据" :image-size="40" />
              </section>

              <section class="result-section">
                <h3 class="section-title"><LineIcon name="note" :size="16" /> 综合评价</h3>
                <div class="summary-card">{{ result.summary || '暂无' }}</div>
              </section>
            </div>

            <!-- 追问中：流式逐字渲染（内容暂存组件内，结束时才写入会话） -->
            <ChatMessage
              v-if="chatLoading"
              role="assistant"
              :content="streamingReply"
              :sources="[]"
              :is-loading="true"
            />
          </div>

          <!-- 输入区 -->
          <div class="chat-input-area">
            <el-input
              v-model="question"
              placeholder="输入追问，AI 将基于你的简历提供建议...（Enter 发送）"
              @keydown.enter.exact="handleAsk"
              :disabled="chatLoading"
            >
              <template #prepend>
                <el-upload
                  :auto-upload="false"
                  :show-file-list="false"
                  :on-change="handleFileSelect"
                  accept=".pdf,.docx,.doc,.txt,.md"
                >
                  <el-button :disabled="chatLoading"><LineIcon name="paperclip" :size="14" /> 新简历</el-button>
                </el-upload>
              </template>
              <template #append>
                <el-button type="primary" :disabled="!question.trim() || chatLoading" @click="handleAsk">
                  {{ chatLoading ? '思考中...' : '发送' }}
                </el-button>
              </template>
            </el-input>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { analyzeResume, RESUME_CHAT_STREAM_URL } from '@/api/resume'
import { useResumeStore } from '@/stores/resume'
import { streamSSE } from '@/utils/sse'
import ChatMessage from '@/components/chat/ChatMessage.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ConversationSidebar from '@/components/common/ConversationSidebar.vue'
import LineIcon from '@/components/common/LineIcon.vue'

const store = useResumeStore()

// 当前会话派生状态（只读）
const result = computed(() => store.activeConversation?.result || null)
const resumeText = computed(() => store.activeConversation?.resumeText || '')

// 岗位匹配推荐：匹配度降序，相同匹配度按岗位名字典序兜底
const sortedJobMatches = computed(() => {
  const jobs = result.value?.job_matches || []
  return [...jobs].sort((a, b) => {
    const diff = (Number(b.score) || 0) - (Number(a.score) || 0)
    if (diff !== 0) return diff
    return (a.role || '').localeCompare(b.role || '')
  })
})
const messages = computed(() => store.activeConversation?.messages || [])
const filename = computed(() => store.activeConversation?.filename || '')
const loading = computed(() => store.activeConversation?.loading || false)
const chatLoading = computed(() => store.activeConversation?.chatLoading || false)

// 追问输入框（会话级，瞬时输入不 persist）
const question = computed({
  get: () => store.activeConversation?.question || '',
  set: (val) => { if (store.activeConversation) store.activeConversation.question = val },
})

const msgContainer = ref(null)
// 追问流式内容暂存组件内，只在流结束时写一次 localStorage
const streamingReply = ref('')

function titleOf(conv) {
  return conv.filename || '未命名简历'
}

function summaryOf(conv) {
  const msgs = conv.messages || []
  for (let i = msgs.length - 1; i >= 0; i--) {
    const content = msgs[i].content || ''
    if (content.startsWith('上传了简历文件') || content.startsWith('### 分析报告')) continue
    return content.length > 20 ? content.slice(0, 20) + '...' : content
  }
  return conv.result ? '分析完成' : '新建会话'
}

async function handleFileSelect(uploadFile) {
  const file = uploadFile.raw
  if (!file) return

  // 当前会话为空（未分析且未在分析中）则复用，否则新建会话（软中断：不覆盖历史）
  const conv = store.activeConversation
  let convId
  if (conv && !conv.result && !conv.loading) {
    convId = conv.id
    store.updateConversation(convId, { filename: file.name })
  } else {
    convId = store.createConversation({ filename: file.name }).id
  }

  store.updateConversation(convId, { loading: true })
  try {
    const res = await analyzeResume(file)
    const data = res.data || {}
    store.updateConversation(convId, {
      resumeText: data._meta?.resume_text || '',
      result: data,
      messages: [
        { role: 'user', content: `上传了简历文件：${file.name}`, sources: [] },
        { role: 'assistant', content: '### 分析报告已生成，请查看下方详情 ↓', sources: [] },
      ],
      loading: false,
    })
  } catch (e) {
    const msg = e?.response?.data?.detail?.error || e?.response?.data?.message || '分析失败'
    ElMessage.error(msg)
    store.deleteConversation(convId)
  } finally {
    await nextTick()
    scrollToBottom()
  }
}

async function handleAsk() {
  const q = question.value.trim()
  const conv = store.activeConversation
  if (!q || !conv || conv.chatLoading) return
  if (!conv.result || !conv.resumeText) {
    ElMessage.warning('简历分析尚未完成，请稍候')
    return
  }

  const convId = conv.id
  const msgs = [...conv.messages, { role: 'user', content: q, sources: [] }]
  store.updateConversation(convId, { messages: msgs, question: '', chatLoading: true })
  streamingReply.value = ''
  await nextTick()
  scrollToBottom()

  const history = msgs
    .filter(m => m.role !== 'system' && !m.content.startsWith('上传了简历文件') && !m.content.startsWith('### 分析报告'))
    .slice(-8)
    .map(m => ({ role: m.role, content: m.content }))

  let reply = ''
  try {
    await streamSSE(
      RESUME_CHAT_STREAM_URL,
      {
        resume_text: conv.resumeText,
        analysis_result: conv.result,
        message: q,
        history: history.slice(0, -1),  // 不含当前这条
      },
      (evt) => {
        if (evt.type === 'token') {
          reply += evt.data || ''
          streamingReply.value = reply
          scrollToBottom()
        }
      },
    )
  } catch {
    // 保留已生成的内容；完全没拿到内容才给失败兜底
  }

  // 只在流结束后写一次 localStorage，避免逐 token 全量序列化
  store.updateConversation(convId, {
    messages: [...msgs, { role: 'assistant', content: reply || '请求失败，请检查后端服务。', sources: [] }],
    chatLoading: false,
  })
  streamingReply.value = ''
  await nextTick()
  scrollToBottom()
}

function scrollToBottom() {
  if (msgContainer.value) {
    msgContainer.value.scrollTop = msgContainer.value.scrollHeight
  }
}

function scoreColor(s) {
  if (s >= 80) return '#8aa88a'
  if (s >= 60) return '#c2a066'
  return '#c08888'
}
</script>

<style scoped>
.resume-analysis { height: 100%; display: flex; }

/* 右侧对话区 */
.resume-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

/* 上传状态 */
.upload-state {
  height: 100%; display: flex; align-items: center; justify-content: center; overflow-y: auto;
}

/* 分析中状态 */
.analyzing-state {
  height: 100%; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 20px;
  padding: 48px 32px;
}
.analyzing-tip { color: var(--text-secondary); font-size: 14px; }
.upload-card { text-align: center; max-width: 520px; padding: 48px 32px; }
.upload-icon { display: flex; justify-content: center; margin-bottom: 16px; color: var(--text-primary); }
.upload-card h2 { font-size: 24px; margin-bottom: 8px; color: var(--text-primary); }
.upload-card > p { color: var(--text-secondary); margin-bottom: 28px; line-height: 1.6; }
.upload-features { display: flex; justify-content: center; gap: 24px; margin-bottom: 32px; }
.feature { display: flex; flex-direction: column; align-items: center; gap: 4px; font-size: 13px; color: var(--text-secondary); }
.feature-icon { font-size: 22px; }
.upload-drop-zone { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 32px; color: var(--text-secondary); }
.upload-drop-icon { font-size: 40px; display: flex; }
.upload-drop-zone em { color: var(--primary); font-style: normal; }
.upload-hint { font-size: 12px; color: var(--text-secondary); }

/* 对话状态 */
.chat-state { height: 100%; display: flex; flex-direction: column; }
.chat-toolbar {
  display: flex; align-items: center; gap: 12px; padding: 8px 16px;
  border-bottom: 1px solid var(--border-color); background: var(--bg-white); flex-shrink: 0;
}
.toolbar-title { font-size: 14px; color: var(--text-secondary); }

.chat-messages { flex: 1; overflow-y: auto; padding: 12px 24px; }

/* 系统提示 */
.system-tip {
  margin: 12px 0; padding: 12px 16px; border-radius: 8px;
  background: var(--primary-light); font-size: 13px; color: var(--text-secondary); line-height: 2;
}
.tip-tag {
  display: inline-block; padding: 2px 8px; margin: 0 4px; border-radius: 4px;
  background: var(--bg-white); color: var(--primary); font-size: 12px; cursor: pointer;
}
.tip-tag:hover { background: var(--primary); color: var(--text-button-primary); }

/* 分析报告卡片 */
.report-card { margin: 16px 0; }

/* 输入区 */
.chat-input-area { padding: 12px 20px; border-top: 1px solid var(--border-color); background: var(--bg-white); }

/* 分析结果结构 */
.result-section { margin-bottom: 24px; }
.section-title { font-size: 16px; font-weight: 600; margin-bottom: 10px; color: var(--text-primary); display: flex; align-items: center; gap: 6px; }
.card-list { display: flex; flex-direction: column; gap: 10px; }
.info-card {
  padding: 14px 16px; border-radius: 8px; border-left: 4px solid var(--primary);
  background: var(--bg-white);
}
.info-card.weakness { border-left-color: #c2a066; }
.card-header { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 8px; }
.card-index {
  width: 20px; height: 20px; border-radius: 50%; background: var(--primary);
  color: var(--text-button-primary); font-size: 11px; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.info-card.weakness .card-index { background: #c2a066; }
.card-point { font-weight: 600; font-size: 14px; color: var(--text-primary); line-height: 1.4; }
.card-detail { font-size: 13px; color: var(--text-secondary); margin-top: 4px; line-height: 1.6; }
.detail-label { color: var(--text-primary); font-weight: 500; }

.job-match-list { display: flex; flex-direction: column; gap: 12px; }
.job-card { padding: 14px 16px; border-radius: 8px; background: var(--bg-white); border: 1px solid var(--border-color); }
.job-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.job-role { font-size: 15px; font-weight: 600; }
.job-reason { font-size: 13px; color: var(--text-secondary); line-height: 1.6; margin-bottom: 6px; }
.job-gaps { font-size: 13px; }

.summary-card {
  padding: 14px 16px; border-radius: 8px; background: var(--bg-white);
  line-height: 1.8; color: var(--text-primary); font-size: 14px;
}
</style>

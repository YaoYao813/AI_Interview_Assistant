<template>
  <div class="resume-analysis">
    <!-- 上传状态 -->
    <div v-if="!result && !loading" class="upload-state">
      <div class="upload-card">
        <div class="upload-icon">📄</div>
        <h2>简历智能分析</h2>
        <p>上传简历文件，AI 将从面试官视角深度分析你的简历</p>
        <div class="upload-features">
          <div class="feature"><span class="feature-icon">🔍</span><span>亮点挖掘</span></div>
          <div class="feature"><span class="feature-icon">⚠️</span><span>不足诊断</span></div>
          <div class="feature"><span class="feature-icon">🎯</span><span>岗位匹配</span></div>
          <div class="feature"><span class="feature-icon">💡</span><span>追问优化</span></div>
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
            <span class="upload-drop-icon">📁</span>
            <span>将简历拖到此处，或 <em>点击上传</em></span>
            <span class="upload-hint">支持 PDF、Word、TXT、Markdown，最大 20MB</span>
          </div>
        </el-upload>
      </div>
    </div>

    <!-- 分析中 -->
    <div v-else-if="loading" class="analyzing-state">
      <el-skeleton :rows="4" animated style="width: 60%; max-width: 520px" />
      <p class="analyzing-tip">🤖 AI 正在分析简历，预计需要 10~20 秒...</p>
    </div>

    <!-- 对话模式 -->
    <div v-else class="chat-state">
      <!-- 顶部工具栏 -->
      <div class="chat-toolbar">
        <el-button text @click="reset">← 重新上传</el-button>
        <span class="toolbar-title">📎 {{ filename }}</span>
      </div>

      <!-- 消息列表 -->
      <div class="chat-messages" ref="msgContainer">
        <!-- 系统欢迎语 -->
        <div v-if="result" class="system-tip">
          🤖 简历分析完成，你可以继续追问：
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
            <h3 class="section-title">📋 简历概况</h3>
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
            <h3 class="section-title">✅ 优势亮点</h3>
            <div v-if="result.strengths?.length" class="card-list">
              <div v-for="(item, idx) in result.strengths" :key="idx" class="info-card strength">
                <div class="card-header">
                  <span class="card-index">{{ idx + 1 }}</span>
                  <span class="card-point">{{ item.point }}</span>
                </div>
                <div class="card-detail"><span class="detail-label">📝 简历证据：</span>{{ item.evidence }}</div>
                <div class="card-detail"><span class="detail-label">💬 面试价值：</span>{{ item.impact }}</div>
              </div>
            </div>
            <el-empty v-else description="暂无数据" :image-size="40" />
          </section>

          <section class="result-section">
            <h3 class="section-title">⚠️ 不足之处</h3>
            <div v-if="result.weaknesses?.length" class="card-list">
              <div v-for="(item, idx) in result.weaknesses" :key="idx" class="info-card weakness">
                <div class="card-header">
                  <span class="card-index">{{ idx + 1 }}</span>
                  <span class="card-point">{{ item.point }}</span>
                </div>
                <div class="card-detail"><span class="detail-label">🔎 问题分析：</span>{{ item.reason }}</div>
                <div class="card-detail"><span class="detail-label">💡 改进建议：</span>{{ item.suggestion }}</div>
              </div>
            </div>
            <el-empty v-else description="暂无数据" :image-size="40" />
          </section>

          <section class="result-section">
            <h3 class="section-title">🎯 岗位匹配推荐</h3>
            <div v-if="result.job_matches?.length" class="job-match-list">
              <div v-for="(job, idx) in result.job_matches" :key="idx" class="job-card">
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
            <h3 class="section-title">📝 综合评价</h3>
            <div class="summary-card">{{ result.summary || '暂无' }}</div>
          </section>
        </div>

        <!-- 加载中（追问时） -->
        <ChatMessage
          v-if="chatLoading"
          role="assistant"
          content=""
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
              <el-button :disabled="chatLoading">📎 新简历</el-button>
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
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { analyzeResume, resumeChat } from '@/api/resume'
import ChatMessage from '@/components/chat/ChatMessage.vue'

const loading = ref(false)
const chatLoading = ref(false)
const filename = ref('')
const result = ref(null)
const resumeText = ref('')
const messages = ref([])
const question = ref('')
const msgContainer = ref(null)

async function handleFileSelect(uploadFile) {
  const file = uploadFile.raw
  if (!file) return

  filename.value = file.name
  messages.value = [{ role: 'user', content: `上传了简历文件：${file.name}`, sources: [] }]
  result.value = null
  loading.value = true

  try {
    const res = await analyzeResume(file)
    const data = res.data || {}
    resumeText.value = data._meta?.resume_text || ''
    result.value = data
    // 将分析报告作为 AI 消息展示
    messages.value.push({ role: 'assistant', content: '### 分析报告已生成，请查看下方详情 👇', sources: [] })
  } catch (e) {
    const msg = e?.response?.data?.detail?.error || e?.response?.data?.message || '分析失败'
    ElMessage.error(msg)
    reset()
  } finally {
    loading.value = false
    await nextTick()
    scrollToBottom()
  }
}

async function handleAsk() {
  const q = question.value.trim()
  if (!q || chatLoading.value) return
  if (!result.value || !resumeText.value) {
    ElMessage.warning('简历分析尚未完成，请稍候')
    return
  }

  messages.value.push({ role: 'user', content: q, sources: [] })
  question.value = ''
  chatLoading.value = true
  await nextTick()
  scrollToBottom()

  try {
    const history = messages.value
      .filter(m => m.role !== 'system' && !m.content.startsWith('上传了简历文件') && !m.content.startsWith('### 分析报告'))
      .slice(-8)
      .map(m => ({ role: m.role, content: m.content }))

    const res = await resumeChat({
      resume_text: resumeText.value,
      analysis_result: result.value,
      message: q,
      history: history.slice(0, -1),  // 不含当前这条
    })
    const reply = res.data?.reply || '抱歉，AI 服务暂时不可用。'
    messages.value.push({ role: 'assistant', content: reply, sources: [] })
  } catch {
    messages.value.push({ role: 'assistant', content: '请求失败，请检查后端服务。', sources: [] })
  } finally {
    chatLoading.value = false
    await nextTick()
    scrollToBottom()
  }
}

function reset() {
  result.value = null
  resumeText.value = ''
  messages.value = []
  filename.value = ''
  loading.value = false
  chatLoading.value = false
  question.value = ''
}

function scrollToBottom() {
  if (msgContainer.value) {
    msgContainer.value.scrollTop = msgContainer.value.scrollHeight
  }
}

function scoreColor(s) {
  if (s >= 80) return '#67c23a'
  if (s >= 60) return '#e6a23c'
  return '#f56c6c'
}
</script>

<style scoped>
.resume-analysis { height: 100%; overflow-y: auto; }

/* ===== 上传状态 ===== */
.upload-state {
  height: 100%; display: flex; align-items: center; justify-content: center;
}

/* ===== 分析中状态 ===== */
.analyzing-state {
  height: 100%; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 20px;
  padding: 48px 32px;
}
.analyzing-tip { color: var(--text-secondary); font-size: 14px; }
.upload-card { text-align: center; max-width: 520px; padding: 48px 32px; }
.upload-icon { font-size: 56px; margin-bottom: 16px; }
.upload-card h2 { font-size: 24px; margin-bottom: 8px; color: var(--text-primary); }
.upload-card > p { color: var(--text-secondary); margin-bottom: 28px; line-height: 1.6; }
.upload-features { display: flex; justify-content: center; gap: 24px; margin-bottom: 32px; }
.feature { display: flex; flex-direction: column; align-items: center; gap: 4px; font-size: 13px; color: var(--text-secondary); }
.feature-icon { font-size: 22px; }
.upload-drop-zone { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 32px; color: var(--text-secondary); }
.upload-drop-icon { font-size: 40px; }
.upload-drop-zone em { color: var(--primary); font-style: normal; }
.upload-hint { font-size: 12px; color: var(--text-secondary); }

/* ===== 对话状态 ===== */
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
.tip-tag:hover { background: var(--primary); color: #fff; }

/* 分析报告卡片 */
.report-card { margin: 16px 0; }

/* ===== 输入区 ===== */
.chat-input-area { padding: 12px 20px; border-top: 1px solid var(--border-color); background: var(--bg-white); }

/* ===== 分析结果结构（复用旧版样式） ===== */
.result-section { margin-bottom: 24px; }
.section-title { font-size: 16px; font-weight: 600; margin-bottom: 10px; color: var(--text-primary); }
.card-list { display: flex; flex-direction: column; gap: 10px; }
.info-card {
  padding: 14px 16px; border-radius: 8px; border-left: 4px solid var(--primary);
  background: var(--bg-white);
}
.info-card.weakness { border-left-color: #e6a23c; }
.card-header { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 8px; }
.card-index {
  width: 20px; height: 20px; border-radius: 50%; background: var(--primary);
  color: #fff; font-size: 11px; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.info-card.weakness .card-index { background: #e6a23c; }
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

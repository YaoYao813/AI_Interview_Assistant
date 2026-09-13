<template>
  <div class="mock-interview">
    <!-- 左侧历史面试列表 -->
    <ConversationSidebar
      :conversations="store.sortedConversations"
      :active-id="store.activeId"
      :title-of="titleOf"
      :summary-of="summaryOf"
      workspace-icon="mic"
      workspace-name="模拟面试"
      empty-icon="mic"
      empty-title="暂无面试记录"
      empty-desc="开始一场模拟面试或点击上方新建"
      @create="store.createConversation()"
      @switch="store.switchConversation"
      @delete="store.deleteConversation"
    />

    <!-- 右侧面试区 -->
    <div class="interview-main">
      <!-- 无活跃会话 -->
      <EmptyState
        v-if="!store.activeConversation"
        icon="mic"
        title="选择或创建一场面试"
        description="模拟真实面试流程，检验学习成果"
      />

      <template v-else>
        <!-- 1. 开始表单 -->
        <div v-if="!sessionId" class="start-state">
          <el-card class="start-card" shadow="never">
            <div class="start-header">
              <LineIcon class="start-icon" name="mic" :size="22" />
              <h3>模拟面试</h3>
            </div>
            <p class="start-desc">AI 面试官将基于你的简历和岗位，模拟真实面试流程</p>

            <el-form label-position="top">
              <el-form-item label="目标岗位" required>
                <el-input v-model="role" placeholder="例如：Java后端开发" />
              </el-form-item>
              <el-form-item label="重点考察方向（可选，逗号分隔）">
                <el-input v-model="topicsText" placeholder="例如：JVM, 并发编程, MySQL" />
              </el-form-item>
              <el-form-item label="难度">
                <el-select v-model="difficulty" style="width: 200px">
                  <el-option label="简单" value="easy" />
                  <el-option label="中等" value="medium" />
                  <el-option label="困难" value="hard" />
                </el-select>
              </el-form-item>
              <el-form-item label="简历文件（可选，AI 将 70%-80% 基于简历出题）">
                <el-upload
                  drag
                  :auto-upload="false"
                  :show-file-list="true"
                  :limit="1"
                  :on-change="handleResumeSelect"
                  :on-remove="handleResumeRemove"
                  accept=".pdf,.docx,.doc,.md,.txt"
                  style="width: 100%"
                >
                  <div class="upload-drop-zone">
                    <span class="upload-drop-icon"><LineIcon name="folder" :size="32" :stroke-width="1.3" /></span>
                    <span>将简历拖到此处，或 <em>点击上传</em></span>
                    <span class="upload-hint">支持 PDF、Word、TXT、Markdown</span>
                  </div>
                </el-upload>
              </el-form-item>
              <el-button
                type="primary"
                size="large"
                :loading="starting"
                @click="handleStart"
                style="width: 100%"
              >
                {{ starting ? 'AI 面试官准备中...' : '开始面试' }}
              </el-button>
            </el-form>
          </el-card>
        </div>

        <!-- 2. 答题中 / 评价中 -->
        <div v-else-if="!finished" class="interview-state">
          <!-- 进度条 -->
          <div class="progress-bar">
            <span class="progress-text">第 {{ currentIndex + 1 }} / {{ total }} 题</span>
            <el-progress
              :percentage="Math.round((currentIndex / total) * 100)"
              :show-text="false"
            />
          </div>

          <!-- 当前题目 -->
          <el-card class="question-card" shadow="never">
            <div class="question-header">
              <LineIcon class="question-icon" name="help" :size="18" />
              <span class="question-label">面试官提问</span>
            </div>
            <p class="question-text">{{ currentQuestion }}</p>
          </el-card>

          <!-- 答题区（评价前） -->
          <el-card v-if="!evaluation" class="answer-card" shadow="never">
            <el-input
              v-model="answer"
              type="textarea"
              :rows="8"
              placeholder="输入你的回答...（建议结构化作答：先结论，再展开）"
            />
            <el-button
              type="primary"
              size="large"
              :loading="evaluating"
              :disabled="!answer.trim()"
              @click="handleSubmit"
              style="margin-top: 12px; width: 100%"
            >
              {{ evaluating ? '面试官评价中...' : '提交回答' }}
            </el-button>
          </el-card>

          <!-- 评价结果（提交后） -->
          <el-card v-else class="evaluation-card" shadow="never">
            <div class="eval-score">
              <span class="score-num">{{ evaluation.score }}</span>
              <span class="score-label">分</span>
            </div>
            <div class="eval-section">
              <h4><LineIcon name="chat" :size="14" /> 面试官反馈</h4>
              <p class="eval-feedback">{{ evaluation.feedback }}</p>
            </div>
            <div class="eval-section">
              <h4><LineIcon name="note" :size="14" /> 参考答案</h4>
              <p class="eval-model-answer">{{ evaluation.model_answer }}</p>
            </div>
            <el-button type="primary" size="large" @click="handleNext" style="width: 100%">
              下一题 →
            </el-button>
          </el-card>
        </div>

        <!-- 3. 结束总结 -->
        <div v-else class="finished-state">
          <el-card shadow="never">
            <div class="finished-header">
              <LineIcon class="finished-icon" name="trophy" :size="24" />
              <h3>面试结束</h3>
            </div>
            <p class="finished-tip">共 {{ total }} 题，平均分 {{ averageScore.toFixed(1) }}</p>

            <div class="round-list">
              <div v-for="(r, idx) in rounds" :key="idx" class="round-card">
                <div class="round-header">
                  <span class="round-index">第 {{ idx + 1 }} 题</span>
                  <span class="round-score" :style="{ color: scoreColor(r.score) }">{{ r.score }} 分</span>
                </div>
                <p class="round-question">{{ r.question }}</p>
                <p class="round-answer">你的回答：{{ r.answer }}</p>
              </div>
            </div>

            <el-button type="primary" size="large" @click="reset" style="width: 100%; margin-top: 16px">
              再来一次
            </el-button>
          </el-card>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { startInterview, evaluateAnswer } from '@/api/interview'
import { useInterviewStore } from '@/stores/interview'
import ConversationSidebar from '@/components/common/ConversationSidebar.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LineIcon from '@/components/common/LineIcon.vue'

const store = useInterviewStore()

// 会话级只读派生
const sessionId = computed(() => store.activeConversation?.sessionId || null)
const total = computed(() => store.activeConversation?.total || 0)
const currentIndex = computed(() => store.activeConversation?.currentIndex || 0)
const currentQuestion = computed(() => store.activeConversation?.currentQuestion || '')
const evaluation = computed(() => store.activeConversation?.evaluation || null)
const rounds = computed(() => store.activeConversation?.rounds || [])
const finished = computed(() => store.activeConversation?.finished || false)
const starting = computed(() => store.activeConversation?.starting || false)
const evaluating = computed(() => store.activeConversation?.evaluating || false)

// 会话级可写（瞬时输入，不 persist）
const role = computed({
  get: () => store.activeConversation?.role || '',
  set: (val) => { if (store.activeConversation) store.activeConversation.role = val },
})
const topicsText = computed({
  get: () => store.activeConversation?.topicsText || '',
  set: (val) => { if (store.activeConversation) store.activeConversation.topicsText = val },
})
const difficulty = computed({
  get: () => store.activeConversation?.difficulty || 'medium',
  set: (val) => { if (store.activeConversation) store.activeConversation.difficulty = val },
})
const answer = computed({
  get: () => store.activeConversation?.answer || '',
  set: (val) => { if (store.activeConversation) store.activeConversation.answer = val },
})

const averageScore = computed(() => {
  const rs = rounds.value
  if (!rs.length) return 0
  const sum = rs.reduce((s, r) => s + Number(r.score || 0), 0)
  return sum / rs.length
})

// 简历文件（File 对象，无法序列化，切换会话时清空）
const resumeFile = ref(null)
watch(() => store.activeId, () => { resumeFile.value = null })

function titleOf(conv) {
  return conv.role || '未命名面试'
}

function summaryOf(conv) {
  if (conv.finished) return '已完成'
  if (conv.sessionId) return `第 ${conv.currentIndex + 1}/${conv.total} 题`
  return '未开始'
}

function handleResumeSelect(uploadFile) {
  resumeFile.value = uploadFile.raw || null
}

function handleResumeRemove() {
  resumeFile.value = null
}

async function handleStart() {
  const conv = store.activeConversation
  if (!conv) return
  const r = role.value.trim()
  if (!r) {
    ElMessage.warning('请输入目标岗位')
    return
  }

  const formData = new FormData()
  formData.append('role', r)
  formData.append('topics', topicsText.value.trim())
  formData.append('difficulty', difficulty.value)
  if (resumeFile.value) {
    formData.append('file', resumeFile.value)
  }

  const convId = conv.id
  store.updateConversation(convId, { starting: true })
  try {
    const res = await startInterview(formData)
    const data = res.data || {}
    store.updateConversation(convId, {
      sessionId: data.session_id,
      total: data.total,
      currentIndex: data.current_index,
      currentQuestion: data.current_question,
      starting: false,
    })
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '开始面试失败')
    store.updateConversation(convId, { starting: false })
  }
}

async function handleSubmit() {
  const conv = store.activeConversation
  if (!conv) return
  const a = answer.value.trim()
  if (!a || conv.evaluating) return

  const convId = conv.id
  store.updateConversation(convId, { evaluating: true })
  try {
    const res = await evaluateAnswer(conv.sessionId, a)
    const data = res.data || {}
    store.updateConversation(convId, {
      rounds: [...conv.rounds, {
        question: conv.currentQuestion,
        answer: a,
        score: data.score,
        feedback: data.feedback,
        model_answer: data.model_answer,
      }],
      evaluation: data,
      currentIndex: data.current_index,
      finished: data.is_finished,
      answer: '',
      evaluating: false,
    })
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '评价失败')
    store.updateConversation(convId, { evaluating: false })
  }
}

function handleNext() {
  const conv = store.activeConversation
  if (!conv || !conv.evaluation) return
  store.updateConversation(conv.id, {
    currentQuestion: conv.evaluation.next_question || '',
    answer: '',
    evaluation: null,
  })
}

function reset() {
  store.createConversation()
}

function scoreColor(s) {
  const n = Number(s)
  if (n >= 8) return '#8aa88a'
  if (n >= 6) return '#c2a066'
  return '#c08888'
}
</script>

<style scoped>
.mock-interview { height: 100%; display: flex; }
.interview-main { flex: 1; overflow-y: auto; padding: 24px; }

/* 开始表单 */
.start-state { max-width: 600px; margin: 0 auto; }
.start-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.start-icon { font-size: 22px; }
.start-header h3 { margin: 0; font-size: 18px; }
.start-desc { color: var(--text-secondary); font-size: 13px; margin: 0 0 16px; }

.upload-drop-zone { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 24px; color: var(--text-secondary); }
.upload-drop-icon { display: flex; }
.upload-drop-zone em { color: var(--primary); font-style: normal; }
.upload-hint { font-size: 12px; }

/* 答题状态 */
.interview-state { max-width: 800px; margin: 0 auto; }
.progress-bar { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.progress-text { font-size: 13px; color: var(--text-secondary); white-space: nowrap; }
.progress-bar .el-progress { flex: 1; }
.question-card { margin-bottom: 16px; }
.question-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.question-icon { font-size: 18px; }
.question-label { font-size: 13px; color: var(--text-secondary); }
.question-text { font-size: 16px; color: var(--text-primary); line-height: 1.7; margin: 0; }

.answer-card { margin-bottom: 16px; }

/* 评价结果 */
.evaluation-card { margin-bottom: 16px; }
.eval-score { display: flex; align-items: baseline; gap: 6px; margin-bottom: 16px; }
.score-num { font-size: 36px; font-weight: 700; color: var(--primary); }
.score-label { font-size: 14px; color: var(--text-secondary); }
.eval-section { margin-bottom: 16px; }
.eval-section h4 { margin: 0 0 8px; font-size: 14px; display: flex; align-items: center; gap: 6px; }
.eval-feedback, .eval-model-answer {
  font-size: 13px; color: var(--text-secondary); line-height: 1.8; margin: 0;
  white-space: pre-wrap;
}

/* 结束总结 */
.finished-state { max-width: 700px; margin: 0 auto; }
.finished-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.finished-icon { font-size: 24px; }
.finished-header h3 { margin: 0; font-size: 20px; }
.finished-tip { color: var(--text-secondary); font-size: 14px; margin: 0 0 16px; }
.round-list { display: flex; flex-direction: column; gap: 12px; }
.round-card {
  padding: 14px 16px; border-radius: 8px;
  background: var(--bg-white); border: 1px solid var(--border-color);
}
.round-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.round-index { font-size: 13px; color: var(--text-secondary); }
.round-score { font-size: 15px; font-weight: 700; }
.round-question { font-size: 14px; color: var(--text-primary); margin: 0 0 6px; }
.round-answer { font-size: 13px; color: var(--text-secondary); margin: 0; line-height: 1.6; }
</style>

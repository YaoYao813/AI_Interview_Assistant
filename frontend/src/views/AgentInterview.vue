<template>
  <div class="agent-interview">
    <div class="agent-main">
      <!-- 头部 -->
      <div class="agent-header">
        <LineIcon class="agent-icon" name="sparkles" :size="22" />
        <div>
          <h2>动态追问面试</h2>
          <p>AI 会根据你的回答决定「追问」还是「翻页」——评价和追问都由模型实时决定</p>
        </div>
      </div>

      <!-- 1. 开始表单 -->
      <el-card v-if="stage === 'start'" class="panel" shadow="never">
        <el-form label-position="top">
          <el-form-item label="目标岗位" required>
            <el-input v-model="role" placeholder="例如：Java 后端开发实习生" />
          </el-form-item>
          <el-form-item label="岗位 JD / 岗位名称（可选）">
            <el-input
              v-model="jd"
              type="textarea"
              :rows="4"
              placeholder="粘贴 JD 或写岗位要求，模型会据此调整考察重点"
            />
          </el-form-item>
          <el-form-item label="难度">
            <el-select v-model="difficulty" style="width: 200px">
              <el-option label="简单" value="easy" />
              <el-option label="中等" value="medium" />
              <el-option label="困难" value="hard" />
            </el-select>
          </el-form-item>
          <el-form-item label="简历文件（可选）">
            <el-upload
              drag
              :auto-upload="false"
              :limit="1"
              :on-change="handleResumeSelect"
              :on-remove="handleResumeRemove"
              accept=".pdf,.docx,.doc,.md,.txt"
              style="width: 100%"
            >
              <div class="upload-zone">
                <LineIcon name="folder" :size="30" :stroke-width="1.3" />
                <span>拖入简历，或 <em>点击上传</em></span>
                <span class="hint">支持 PDF / Word / TXT / Markdown</span>
              </div>
            </el-upload>
          </el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="starting"
            style="width: 100%"
            @click="handleStart"
          >
            {{ starting ? 'AI 面试官准备中...' : '开始面试' }}
          </el-button>
        </el-form>
      </el-card>

      <!-- 2. 面试中 -->
      <template v-else-if="stage === 'answering'">
        <div class="status-bar">
          <el-tag size="small" effect="plain">{{ phaseLabel }}</el-tag>
          <span>已问 {{ totalAsked }} 题</span>
          <span v-if="followupsUsed">本阶段已追问 {{ followupsUsed }} 次</span>
          <span v-if="streaming" class="streaming-tip">面试官评价中…</span>
        </div>

        <!-- 上一轮评价 -->
        <el-card v-if="displayEval" class="panel eval-card" shadow="never">
          <div class="score-row">
            <span class="score-num">{{ displayEval.score ?? '—' }}</span>
            <span class="score-label">分</span>
          </div>
          <div class="section">
            <h4>面试官反馈</h4>
            <p class="body-text">{{ displayEval.feedback || '…' }}</p>
          </div>
          <el-collapse v-if="displayEval.model_answer" class="model-answer">
            <el-collapse-item title="参考答案" name="model">
              <p class="body-text">{{ displayEval.model_answer }}</p>
            </el-collapse-item>
          </el-collapse>
        </el-card>

        <!-- 当前题目 -->
        <el-card class="panel question-card" shadow="never">
          <div class="question-head">
            <LineIcon name="help" :size="18" />
            <span>面试官提问</span>
          </div>
          <p class="question-text">{{ currentQuestion }}</p>
        </el-card>

        <!-- 作答 -->
        <el-card class="panel" shadow="never">
          <el-input
            v-model="answer"
            type="textarea"
            :rows="8"
            placeholder="输入你的回答…（建议先结论后展开）"
            :disabled="streaming"
          />
          <div class="actions">
            <el-button
              type="primary"
              size="large"
              :loading="streaming"
              :disabled="!answer.trim() || streaming"
              @click="handleSubmit"
            >
              {{ streaming ? '评价中...' : '提交回答' }}
            </el-button>
            <el-button v-if="streaming" size="large" @click="stopStreaming">停止生成</el-button>
          </div>
        </el-card>
      </template>

      <!-- 3. 结束报告 -->
      <el-card v-else class="panel" shadow="never">
        <div class="finished-head">
          <LineIcon name="trophy" :size="24" />
          <h3>面试结束</h3>
        </div>
        <p class="finished-tip">
          共问 {{ report?.total_asked ?? totalAsked }} 题，已评分 {{ report?.answered ?? 0 }} 题
          <template v-if="report?.average_score != null">，平均分 {{ report.average_score }}</template>
        </p>
        <p v-if="report?.match_summary" class="body-text summary">{{ report.match_summary }}</p>

        <div class="qa-list">
          <div v-for="(item, idx) in report?.qa || []" :key="idx" class="qa-card">
            <div class="qa-head">
              <span>第 {{ idx + 1 }} 题</span>
              <span class="qa-score">{{ item.score ?? '—' }} 分</span>
            </div>
            <p class="qa-q">{{ item.question }}</p>
            <p class="qa-a">你的回答：{{ item.answer || '（未作答）' }}</p>
            <p v-if="item.feedback" class="qa-f">反馈：{{ item.feedback }}</p>
          </div>
        </div>

        <el-button type="primary" size="large" style="width: 100%; margin-top: 16px" @click="reset">
          再来一场
        </el-button>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { startAgentInterview, getAgentReport, AGENT_ANSWER_STREAM_URL } from '@/api/interviewAgent'
import { streamSSE } from '@/utils/sse'
import LineIcon from '@/components/common/LineIcon.vue'

const PHASE_LABEL = { intro: '自我介绍', fundamentals: '八股基础', project: '项目拷问', done: '已结束' }

const stage = ref('start')            // start | answering | finished
const starting = ref(false)
const streaming = ref(false)

const role = ref('')
const jd = ref('')
const difficulty = ref('medium')
const resumeFile = ref(null)

const sessionId = ref('')
const phase = ref('intro')
const currentQuestion = ref('')
const totalAsked = ref(0)
const followupsUsed = ref(0)
const answer = ref('')

const streamEval = ref(null)          // 流式累积中
const lastEval = ref(null)            // 上一轮已完成评价
const report = ref(null)

let controller = null

const phaseLabel = computed(() => PHASE_LABEL[phase.value] || phase.value)
const displayEval = computed(() => streamEval.value || lastEval.value || null)

function handleResumeSelect(uploadFile) {
  resumeFile.value = uploadFile.raw || null
}

function handleResumeRemove() {
  resumeFile.value = null
}

async function handleStart() {
  if (!role.value.trim()) {
    ElMessage.warning('请输入目标岗位')
    return
  }
  starting.value = true
  try {
    const formData = new FormData()
    formData.append('role', role.value.trim())
    formData.append('jd', jd.value.trim())
    formData.append('difficulty', difficulty.value)
    if (resumeFile.value) formData.append('file', resumeFile.value)

    const res = await startAgentInterview(formData)
    const data = res.data || {}
    sessionId.value = data.session_id
    phase.value = data.phase
    currentQuestion.value = data.question
    totalAsked.value = 1
    followupsUsed.value = 0
    lastEval.value = null
    answer.value = ''
    stage.value = 'answering'
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '开始面试失败')
  } finally {
    starting.value = false
  }
}

function stopStreaming() {
  if (controller) controller.abort()
}

async function handleSubmit() {
  const a = answer.value.trim()
  if (!a || streaming.value) return

  streaming.value = true
  lastEval.value = null
  streamEval.value = { score: null, feedback: '', model_answer: '' }
  controller = new AbortController()

  let terminal = null
  let failure = null
  let stopped = false

  try {
    await streamSSE(
      AGENT_ANSWER_STREAM_URL,
      { session_id: sessionId.value, answer: a },
      (evt) => {
        const cur = streamEval.value
        if (evt.type === 'score') {
          streamEval.value = { ...cur, score: evt.data }
        } else if (evt.type === 'feedback') {
          streamEval.value = { ...cur, feedback: cur.feedback + (evt.data || '') }
        } else if (evt.type === 'model_answer') {
          streamEval.value = { ...cur, model_answer: cur.model_answer + (evt.data || '') }
        } else if (evt.type === 'question' || evt.type === 'done') {
          terminal = evt
        } else if (evt.type === 'error') {
          failure = evt.data || '评价失败'
        }
      },
      { signal: controller.signal },
    )
  } catch (e) {
    if (e?.name === 'AbortError') {
      stopped = true
    } else if (e?.status === 404) {
      // 会话过期 / 已结束：后端在建流前就拒绝，流根本没建立
      ElMessage.warning(e.message)
      stage.value = 'finished'
      await loadReport()
    } else {
      failure = e?.message || '评价失败'
    }
  } finally {
    streaming.value = false
    controller = null
  }

  if (stopped) {
    streamEval.value = null
    ElMessage.warning('已停止生成；服务端可能已完成本轮，下一题以实际为准')
    return
  }
  if (failure) {
    streamEval.value = null
    ElMessage.error(failure)
    return
  }
  if (!terminal) {
    streamEval.value = null
    ElMessage.error('评价未完成，请重试')
    return
  }

  const d = terminal.data || {}
  lastEval.value = d.evaluation || null
  streamEval.value = null
  phase.value = d.phase || phase.value
  followupsUsed.value = d.followups_used ?? followupsUsed.value
  totalAsked.value = d.total_asked ?? totalAsked.value

  if (terminal.type === 'done' || d.is_finished) {
    stage.value = 'finished'
    await loadReport()
  } else {
    currentQuestion.value = d.question || ''
    answer.value = ''
  }
}

async function loadReport() {
  try {
    const res = await getAgentReport(sessionId.value)
    report.value = res.data || null
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '获取报告失败')
  }
}

function reset() {
  stage.value = 'start'
  sessionId.value = ''
  phase.value = 'intro'
  currentQuestion.value = ''
  totalAsked.value = 0
  followupsUsed.value = 0
  answer.value = ''
  streamEval.value = null
  lastEval.value = null
  report.value = null
}
</script>

<style scoped>
.agent-interview { height: 100%; overflow-y: auto; padding: 24px; }
.agent-main { max-width: 820px; margin: 0 auto; }

.agent-header { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 20px; }
.agent-icon { margin-top: 4px; }
.agent-header h2 { margin: 0 0 4px; font-size: 20px; }
.agent-header p { margin: 0; font-size: 13px; color: var(--text-secondary); }

.panel { margin-bottom: 16px; }
.upload-zone {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 22px; color: var(--text-secondary);
}
.upload-zone em { color: var(--primary); font-style: normal; }
.upload-zone .hint { font-size: 12px; }

.status-bar {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  font-size: 13px; color: var(--text-secondary); margin-bottom: 12px;
}
.streaming-tip { color: var(--primary); }

.score-row { display: flex; align-items: baseline; gap: 6px; margin-bottom: 12px; }
.score-num { font-size: 34px; font-weight: 700; color: var(--primary); }
.score-label { font-size: 14px; color: var(--text-secondary); }
.section h4 { margin: 0 0 8px; font-size: 14px; }
.body-text {
  font-size: 13px; line-height: 1.8; margin: 0;
  color: var(--text-secondary); white-space: pre-wrap;
}
.model-answer { margin-top: 8px; }

.question-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 13px; color: var(--text-secondary); }
.question-text { font-size: 16px; line-height: 1.7; margin: 0; }

.actions { display: flex; gap: 12px; margin-top: 12px; }
.actions .el-button:first-child { flex: 1; }

.finished-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.finished-head h3 { margin: 0; font-size: 20px; }
.finished-tip { font-size: 14px; color: var(--text-secondary); margin: 0 0 8px; }
.summary { margin-bottom: 16px; }

.qa-list { display: flex; flex-direction: column; gap: 12px; }
.qa-card {
  padding: 14px 16px; border-radius: 8px;
  background: var(--bg-white); border: 1px solid var(--border-color);
}
.qa-head { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 13px; color: var(--text-secondary); }
.qa-score { font-weight: 700; color: var(--text-primary); }
.qa-q { font-size: 14px; margin: 0 0 6px; color: var(--text-primary); }
.qa-a, .qa-f { font-size: 13px; margin: 0; line-height: 1.7; color: var(--text-secondary); }
</style>

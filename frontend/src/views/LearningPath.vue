<template>
  <div class="learning-path">
    <!-- 左侧历史路线列表 -->
    <ConversationSidebar
      :conversations="store.sortedConversations"
      :active-id="store.activeId"
      :title-of="titleOf"
      :summary-of="summaryOf"
      workspace-icon="map"
      workspace-name="学习路线"
      empty-icon="map"
      empty-title="暂无学习路线"
      empty-desc="生成一条学习路线或点击上方新建"
      @create="store.createConversation()"
      @switch="store.switchConversation"
      @delete="store.deleteConversation"
    />

    <!-- 右侧生成区 -->
    <div class="learning-main">
      <!-- 无活跃会话 -->
      <EmptyState
        v-if="!store.activeConversation"
        icon="map"
        title="选择或创建一个对话"
        description="输入目标岗位，AI 将生成个性化学习路线"
      />

      <template v-else>
        <!-- 输入区 -->
        <el-card v-if="!result && !loading" class="input-card" shadow="never">
          <div class="input-header">
            <LineIcon class="input-icon" name="map" :size="22" />
            <h3>个性化学习路线</h3>
          </div>
          <p class="input-desc">输入目标岗位，AI 将分析技能差距并生成结构化学习路线</p>

          <el-input
            v-model="targetRole"
            placeholder="目标岗位，例如：Java后端开发"
            size="large"
            @keydown.enter.exact="handleGenerate"
          />
          <el-input
            v-model="resumeText"
            type="textarea"
            :rows="5"
            placeholder="粘贴简历内容（可选，有助于个性化分析技能差距）"
            style="margin-top: 12px"
          />
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            @click="handleGenerate"
            style="margin-top: 16px; width: 100%"
          >
            {{ loading ? 'AI 分析中...' : '生成学习路线' }}
          </el-button>
        </el-card>

        <!-- 加载中 -->
        <div v-else-if="loading" class="loading-state">
          <el-skeleton :rows="6" animated />
        </div>

        <!-- 结果区 -->
        <el-card v-else shadow="never">
          <template #header>
            <div class="result-header">
              <span><LineIcon name="target" :size="15" /> 目标岗位：{{ result.target_role }}</span>
              <el-button text type="primary" @click="reset">重新生成</el-button>
            </div>
          </template>

          <div class="step-list">
            <div v-for="(step, idx) in result.steps" :key="idx" class="step-card">
              <div class="step-header">
                <span class="step-index">{{ idx + 1 }}</span>
                <span class="step-topic">{{ step.topic }}</span>
              </div>
              <p class="step-description">{{ step.description }}</p>
              <div class="step-resources">
                <span class="resource-label"><LineIcon name="book" :size="13" /> 学习资源：</span>
                <el-tag
                  v-for="(r, ri) in step.resources"
                  :key="ri"
                  size="small"
                  style="margin-right: 6px; margin-bottom: 4px"
                >{{ r }}</el-tag>
              </div>
            </div>
          </div>
        </el-card>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { generateRoadmap } from '@/api/learning'
import { useLearningStore } from '@/stores/learning'
import ConversationSidebar from '@/components/common/ConversationSidebar.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LineIcon from '@/components/common/LineIcon.vue'

const store = useLearningStore()

// 会话级只读派生
const result = computed(() => store.activeConversation?.result || null)
const loading = computed(() => store.activeConversation?.loading || false)

// 会话级可写（瞬时输入，不 persist）
const targetRole = computed({
  get: () => store.activeConversation?.targetRole || '',
  set: (val) => { if (store.activeConversation) store.activeConversation.targetRole = val },
})
const resumeText = computed({
  get: () => store.activeConversation?.resumeText || '',
  set: (val) => { if (store.activeConversation) store.activeConversation.resumeText = val },
})

function titleOf(conv) {
  return conv.targetRole || '未命名路线'
}

function summaryOf(conv) {
  return conv.result ? '生成完成' : '待生成'
}

async function handleGenerate() {
  const conv = store.activeConversation
  if (!conv) return
  const role = targetRole.value.trim()
  if (!role) {
    ElMessage.warning('请输入目标岗位')
    return
  }

  // 当前会话为空则复用，否则新建会话（每次生成新建，不覆盖历史）
  let convId
  if (!conv.result && !conv.loading) {
    convId = conv.id
  } else {
    convId = store.createConversation({ targetRole: conv.targetRole, resumeText: conv.resumeText }).id
  }

  store.updateConversation(convId, { loading: true })
  try {
    const res = await generateRoadmap(role, resumeText.value)
    store.updateConversation(convId, { result: res.data || {}, loading: false })
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '生成失败，请稍后重试')
    store.updateConversation(convId, { loading: false })
  }
}

function reset() {
  store.createConversation()
}
</script>

<style scoped>
.learning-path { height: 100%; display: flex; }
.learning-main { flex: 1; overflow-y: auto; padding: 24px; }
.learning-main > .input-card,
.learning-main > .loading-state,
.learning-main > .el-card { max-width: 800px; margin: 0 auto; }

.input-card { margin-bottom: 20px; }
.input-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.input-icon { font-size: 22px; }
.input-header h3 { margin: 0; font-size: 18px; }
.input-desc { color: var(--text-secondary); font-size: 13px; margin: 0 0 16px; }
.loading-state { margin-top: 20px; }
.result-header { display: flex; align-items: center; justify-content: space-between; }
.step-list { display: flex; flex-direction: column; gap: 12px; }
.step-card {
  padding: 16px;
  border-radius: 8px;
  background: var(--bg-white);
  border: 1px solid var(--border-color);
}
.step-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.step-index {
  width: 22px; height: 22px; border-radius: 50%;
  background: var(--primary); color: var(--text-button-primary); font-size: 12px;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.step-topic { font-weight: 600; font-size: 15px; color: var(--text-primary); }
.step-description {
  font-size: 13px; color: var(--text-secondary);
  line-height: 1.7; margin: 0 0 8px;
}
.step-resources { font-size: 13px; }
.resource-label { color: var(--text-primary); font-weight: 500; }
</style>

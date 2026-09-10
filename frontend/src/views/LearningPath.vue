<template>
  <div class="learning-path">
    <!-- 输入区 -->
    <el-card class="input-card" shadow="never">
      <div class="input-header">
        <span class="input-icon">🗺️</span>
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
    <div v-if="loading" class="loading-state">
      <el-skeleton :rows="6" animated />
    </div>

    <!-- 结果区 -->
    <el-card v-else-if="result" shadow="never">
      <template #header>
        <div class="result-header">
          <span>🎯 目标岗位：{{ result.target_role }}</span>
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
            <span class="resource-label">📚 学习资源：</span>
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

    <!-- 初始空状态 -->
    <el-empty v-else description="输入岗位后生成你的学习路线" />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { generateRoadmap } from '@/api/learning'

const targetRole = ref('')
const resumeText = ref('')
const loading = ref(false)
const result = ref(null)

async function handleGenerate() {
  const role = targetRole.value.trim()
  if (!role) {
    ElMessage.warning('请输入目标岗位')
    return
  }
  loading.value = true
  try {
    const res = await generateRoadmap(role, resumeText.value)
    result.value = res.data || {}
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '生成失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

function reset() {
  result.value = null
}
</script>

<style scoped>
.learning-path {
  height: 100%;
  overflow-y: auto;
  padding: 24px;
  max-width: 800px;
  margin: 0 auto;
}
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
  background: var(--primary); color: #fff; font-size: 12px;
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

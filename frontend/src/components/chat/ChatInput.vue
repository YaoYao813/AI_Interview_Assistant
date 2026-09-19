<template>
  <div class="chat-input-area">
    <div class="chat-options">
      <el-switch v-model="streamMode" size="small" active-text="流式输出" />
      <span class="option-label">Top K</span>
      <el-input-number v-model="topK" :min="1" :max="20" size="small" style="width: 80px" />
      <span class="option-label">阈值</span>
      <el-slider v-model="threshold" :min="0" :max="1" :step="0.05" style="width: 100px" />
      <span class="threshold-value">{{ threshold }}</span>
    </div>
    <div class="chat-input-row">
      <el-input
        v-model="question"
        type="textarea"
        :rows="4"
        placeholder="输入你的问题... (Enter 发送，Shift+Enter 换行)"
        @keydown.enter.exact="handleSend"
        resize="none"
      />
      <el-button v-if="loading" @click="handleStop">停止生成</el-button>
      <el-button type="primary" :disabled="!question.trim()" @click="handleSend">
        发送 →
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const emit = defineEmits(['send', 'stop'])

defineProps({
  loading: { type: Boolean, default: false },
})

const question = ref('')
const streamMode = ref(true)
const topK = ref(3)
const threshold = ref(0.3)

function handleSend() {
  const q = question.value.trim()
  if (!q) return
  emit('send', { question: q, stream: streamMode.value, top_k: topK.value, threshold: threshold.value })
  question.value = ''
}

function handleStop() {
  emit('stop')
}
</script>

<style scoped>
.chat-input-area {
  border-top: 1px solid var(--border-color); padding: 16px 20px; background: var(--bg-white);
}
.chat-options {
  display: flex; align-items: center; gap: 12px; margin-bottom: 10px;
  font-size: 13px; color: var(--text-secondary);
}
.option-label { margin-left: 8px; }
.threshold-value { min-width: 28px; text-align: center; }
.chat-input-row { display: flex; gap: 10px; align-items: flex-end; }
.chat-input-row .el-textarea { flex: 1; }
</style>

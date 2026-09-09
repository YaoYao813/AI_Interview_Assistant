<template>
  <div class="source-card">
    <div class="source-header" @click="expanded = !expanded">
      <span class="source-label">📎 引用来源 ({{ sources.length }})</span>
      <span class="source-toggle">{{ expanded ? '收起' : '展开' }}</span>
    </div>
    <div v-show="expanded" class="source-list">
      <div v-for="s in sources" :key="s.index" class="source-item">
        <span class="source-index">[{{ s.index }}]</span>
        <span class="source-doc">{{ s.document }}</span>
        <el-tag size="small" type="info">{{ (s.similarity * 100).toFixed(0) }}%</el-tag>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  sources: { type: Array, default: () => [] },
})

const expanded = ref(true)
</script>

<style scoped>
.source-card {
  margin-top: 12px; border: 1px solid var(--border-color); border-radius: var(--radius);
  background: #fafbfc; overflow: hidden;
}
.source-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 12px; cursor: pointer; font-size: 13px; color: var(--text-secondary);
  user-select: none;
}
.source-header:hover { background: #f0f2f5; }
.source-toggle { font-size: 12px; color: var(--primary); }
.source-list { padding: 0 12px 8px; }
.source-item {
  display: flex; align-items: center; gap: 8px; padding: 4px 0;
  font-size: 13px; color: var(--text-regular);
}
.source-index { color: var(--primary); font-weight: 500; min-width: 28px; }
.source-doc { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>

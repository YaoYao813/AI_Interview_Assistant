<template>
  <header class="app-header">
    <h1 class="header-title">{{ title }}</h1>
    <div class="header-right">
      <el-tag v-if="appStore.isAdmin" type="warning" size="small" effect="plain">管理员</el-tag>
      <span class="user-name">Yao</span>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'

const route = useRoute()
const appStore = useAppStore()

const titleMap = {
  '/': '仪表盘',
  '/knowledge': '知识库问答',
  '/resume': '简历分析',
  '/interview': '模拟面试',
  '/learning': '学习路线',
  '/admin/knowledge': '知识库管理',
}
const title = computed(() => {
  const base = '/' + route.path.split('/')[1]
  if (route.path.startsWith('/admin/')) return titleMap['/admin/knowledge'] || route.path
  return titleMap[base] || 'AI Interview Assistant'
})
</script>

<style scoped>
.app-header {
  height: 56px; background: var(--bg-white); display: flex; align-items: center;
  justify-content: space-between; padding: 0 24px;
  box-shadow: var(--shadow-sm); z-index: 10; position: relative;
}
.header-title { font-size: 18px; font-weight: 600; color: var(--text-primary); }
.header-right { display: flex; align-items: center; gap: 12px; }
.user-name { font-size: 14px; color: var(--text-secondary); }
</style>

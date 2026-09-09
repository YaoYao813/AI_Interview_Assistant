<template>
  <div class="placeholder-page">
    <div class="placeholder-content">
      <span class="placeholder-icon">🗺️</span>
      <h2>学习路线</h2>
      <p>个性化学习规划，明确目标岗位的技能要求</p>
      <el-tag type="info">即将上线</el-tag>
    </div>
  </div>
</template>

<script setup>
import { ElTag } from 'element-plus'
</script>

<style scoped>
.placeholder-page { display: flex; align-items: center; justify-content: center; height: 100%; }
.placeholder-content { text-align: center; }
.placeholder-icon { font-size: 64px; display: block; margin-bottom: 16px; }
.placeholder-content h2 { font-size: 22px; margin-bottom: 8px; }
.placeholder-content p { color: var(--text-secondary); margin-bottom: 16px; }
</style>

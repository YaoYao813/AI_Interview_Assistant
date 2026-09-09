<template>
  <div class="dashboard">
    <div class="welcome">
      <h2>欢迎回来，Yao 👋</h2>
      <p class="welcome-sub">今天准备练习哪些面试知识点？</p>
    </div>

    <div class="module-grid">
      <div
        v-for="m in modules"
        :key="m.path"
        class="module-card"
        @click="$router.push(m.path)"
      >
        <div class="module-icon">{{ m.icon }}</div>
        <div class="module-info">
          <h3>{{ m.title }}</h3>
          <p>{{ m.desc }}</p>
        </div>
        <span class="module-arrow">→</span>
      </div>
    </div>

    <div class="quick-start">
      <h3>🚀 快速开始</h3>
      <div class="steps">
        <div class="step">
          <span class="step-num">1</span>
          <span>上传面试资料到<strong>知识库</strong></span>
        </div>
        <div class="step-arrow">↓</div>
        <div class="step">
          <span class="step-num">2</span>
          <span>在<strong>知识问答</strong>中向 AI 提问</span>
        </div>
        <div class="step-arrow">↓</div>
        <div class="step">
          <span class="step-num">3</span>
          <span>尝试<strong>模拟面试</strong>检验学习成果</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()

const allModules = [
  { path: '/knowledge', icon: '💬', title: '知识库问答', desc: 'AI 驱动的智能技术问答，基于你上传的学习资料精准回答' },
  { path: '/resume', icon: '📄', title: '简历分析', desc: '深度解析简历内容，提供针对性优化建议' },
  { path: '/interview', icon: '🎤', title: '模拟面试', desc: '实战演练，模拟真实面试场景和真题' },
  { path: '/learning', icon: '🗺️', title: '学习路线', desc: '个性化学习规划，明确目标岗位的技术栈' },
  { path: '/admin/knowledge', icon: '⚙️', title: '知识库管理', desc: '上传和管理面试学习资料', adminOnly: true },
]

const modules = computed(() =>
  allModules.filter(m => !m.adminOnly || appStore.isAdmin)
)
</script>

<style scoped>
.dashboard { max-width: 900px; margin: 0 auto; padding: 32px 24px; }
.welcome { margin-bottom: 32px; }
.welcome h2 { font-size: 24px; font-weight: 600; }
.welcome-sub { color: var(--text-secondary); margin-top: 6px; font-size: 15px; }

.module-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; margin-bottom: 40px; }
.module-card {
  display: flex; align-items: center; gap: 14px; padding: 20px;
  background: var(--bg-white); border: 1px solid var(--border-color); border-radius: var(--radius);
  cursor: pointer; transition: all 0.2s;
}
.module-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); border-color: var(--primary); }
.module-icon { font-size: 32px; flex-shrink: 0; }
.module-info { flex: 1; min-width: 0; }
.module-info h3 { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
.module-info p { font-size: 13px; color: var(--text-secondary); line-height: 1.5; }
.module-arrow { font-size: 18px; color: var(--text-secondary); flex-shrink: 0; }

.quick-start {
  background: var(--bg-white); border: 1px solid var(--border-color);
  border-radius: var(--radius); padding: 24px;
}
.quick-start h3 { font-size: 16px; margin-bottom: 20px; }
.steps { display: flex; align-items: center; justify-content: center; gap: 16px; }
.step { display: flex; align-items: center; gap: 10px; font-size: 14px; color: var(--text-regular); }
.step-num {
  width: 28px; height: 28px; border-radius: 50%; background: var(--primary);
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 600; flex-shrink: 0;
}
.step-arrow { color: var(--text-secondary); font-size: 18px; }
</style>

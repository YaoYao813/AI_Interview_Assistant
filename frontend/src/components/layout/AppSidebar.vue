<template>
  <aside class="nav-rail">
    <div class="rail-logo" title="AI Interview" @click="$router.push('/')">
      <LineIcon name="target" :size="22" />
    </div>

    <nav class="rail-nav">
      <router-link
        v-for="item in visibleMenu"
        :key="item.path"
        :to="item.path"
        class="rail-item"
        :class="{ active: isActive(item.path) }"
        :title="item.label"
      >
        <LineIcon class="rail-icon" :name="item.icon" :size="19" />
      </router-link>
    </nav>

    <div class="rail-footer">
      <span v-if="appStore.isAdmin" class="rail-badge">管理员</span>
      <button
        class="rail-avatar"
        :title="appStore.isAdmin ? '管理员 — 点击切换为普通用户' : '普通用户 — 点击切换为管理员'"
        @click="toggleRole"
      >
        Y
      </button>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import LineIcon from '@/components/common/LineIcon.vue'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()

const allMenu = [
  { path: '/', icon: 'dashboard', label: '仪表盘', roles: ['user', 'admin'] },
  { path: '/knowledge', icon: 'chat', label: '知识问答', roles: ['user', 'admin'] },
  { path: '/resume', icon: 'file', label: '简历分析', roles: ['user', 'admin'] },
  { path: '/interview', icon: 'mic', label: '模拟面试', roles: ['user', 'admin'] },
  { path: '/learning', icon: 'map', label: '学习路线', roles: ['user', 'admin'] },
  { path: '/admin/knowledge', icon: 'settings', label: '知识库管理', roles: ['admin'] },
]

const visibleMenu = computed(() =>
  allMenu.filter(item => item.roles.includes(appStore.userRole))
)

function isActive(path) {
  return path === '/' ? route.path === '/' : route.path.startsWith(path)
}

function toggleRole() {
  const next = appStore.isAdmin ? 'user' : 'admin'
  appStore.setUserRole(next)
  // 守卫只在导航时触发，降级时若正停在 /admin/ 页面上不会自动重跑，需手动踢回首页
  if (next === 'user' && route.path.startsWith('/admin/')) router.push('/')
}
</script>

<style scoped>
.nav-rail {
  width: 60px; height: 100%; background: var(--bg-nav-level1);
  border-right: 1px solid var(--border-line);
  display: flex; flex-direction: column; align-items: center;
  flex-shrink: 0; padding: 12px 0;
}
.rail-logo {
  font-size: 24px; cursor: pointer; user-select: none; margin-bottom: 16px;
  line-height: 1;
}
.rail-nav {
  flex: 1; width: 100%; display: flex; flex-direction: column;
  align-items: center; gap: 6px;
}
.rail-item {
  width: 40px; height: 40px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  text-decoration: none; color: var(--text-secondary);
  transition: background 0.15s, color 0.15s;
}
.rail-item:hover { background: var(--bg-hover); color: var(--text-primary); }
.rail-item.active { background: var(--bg-hover); color: var(--text-primary); }
.rail-icon { font-size: 18px; line-height: 1; }
.rail-footer {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding-top: 8px;
}
.rail-badge { font-size: 10px; color: var(--text-secondary); letter-spacing: 0.5px; }
.rail-avatar {
  width: 32px; height: 32px; border-radius: 50%; background: var(--bg-hover);
  border: none; padding: 0; font-family: inherit; cursor: pointer;
  color: var(--text-primary); font-size: 13px; font-weight: 600;
  display: flex; align-items: center; justify-content: center; user-select: none;
}
</style>

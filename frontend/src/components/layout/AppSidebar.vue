<template>
  <aside class="sidebar" :class="{ collapsed }">
    <div class="sidebar-logo" @click="$router.push('/')">
      <span class="logo-icon">🎯</span>
      <span v-show="!collapsed" class="logo-text">AI Interview</span>
    </div>

    <div class="sidebar-nav">
      <router-link v-for="item in visibleMenu" :key="item.path" :to="item.path" class="nav-item">
        <span class="nav-icon">{{ item.icon }}</span>
        <span v-show="!collapsed" class="nav-label">{{ item.label }}</span>
      </router-link>
    </div>

    <div class="sidebar-footer">
      <div class="collapse-btn" @click="appStore.toggleSidebar()">
        {{ collapsed ? '▶' : '◀' }}
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
const collapsed = computed(() => appStore.sidebarCollapsed)

const allMenu = [
  { path: '/', icon: '📊', label: '仪表盘', roles: ['user', 'admin'] },
  { path: '/knowledge', icon: '💬', label: '知识问答', roles: ['user', 'admin'] },
  { path: '/resume', icon: '📄', label: '简历分析', roles: ['user', 'admin'] },
  { path: '/interview', icon: '🎤', label: '模拟面试', roles: ['user', 'admin'] },
  { path: '/learning', icon: '🗺️', label: '学习路线', roles: ['user', 'admin'] },
  { path: '/admin/knowledge', icon: '⚙️', label: '知识库管理', roles: ['admin'] },
]

const visibleMenu = computed(() =>
  allMenu.filter(item => item.roles.includes(appStore.userRole))
)
</script>

<style scoped>
.sidebar {
  width: 220px; height: 100%; background: var(--sidebar-bg);
  display: flex; flex-direction: column; transition: width 0.2s;
  overflow: hidden;
}
.sidebar.collapsed { width: 64px; }
.sidebar-logo {
  display: flex; align-items: center; gap: 8px; padding: 16px 20px;
  cursor: pointer; user-select: none;
}
.sidebar.collapsed .sidebar-logo { padding: 16px; justify-content: center; }
.logo-icon { font-size: 24px; }
.logo-text { font-size: 16px; font-weight: 600; color: #fff; white-space: nowrap; }
.sidebar-nav { flex: 1; padding: 8px 0; }
.nav-item {
  display: flex; align-items: center; gap: 12px; padding: 12px 20px;
  color: #a0a4b8; text-decoration: none; font-size: 14px;
  transition: all 0.15s; border-left: 3px solid transparent;
}
.sidebar.collapsed .nav-item { padding: 12px; justify-content: center; }
.nav-item:hover { background: var(--sidebar-hover); color: #d0d4e8; }
.nav-item.router-link-active { background: var(--sidebar-active); color: #fff; border-left-color: var(--primary); }
.nav-icon { font-size: 18px; flex-shrink: 0; }
.nav-label { white-space: nowrap; }
.sidebar-footer { padding: 12px; border-top: 1px solid rgba(255,255,255,0.06); }
.collapse-btn {
  text-align: center; cursor: pointer; color: #6b6f85; font-size: 12px;
  padding: 6px; border-radius: 4px; transition: color 0.2s;
}
.collapse-btn:hover { color: #a0a4b8; }
</style>

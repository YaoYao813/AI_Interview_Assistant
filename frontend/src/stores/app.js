import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

const ROLE_KEY = 'ai_interview_role'
const ROLES = ['user', 'admin']

function loadRole() {
  const saved = localStorage.getItem(ROLE_KEY)
  return ROLES.includes(saved) ? saved : 'user'
}

export const useAppStore = defineStore('app', () => {
  // ===== 状态 =====
  const sidebarCollapsed = ref(false)
  // 演示用的角色开关，只驱动路由守卫与菜单过滤，不具备安全意义：
  // 后端没有任何鉴权，接口对匿名请求同样开放，生产环境必须由服务端独立校验。
  const userRole = ref(loadRole())

  // ===== 计算属性 =====
  const isAdmin = computed(() => userRole.value === 'admin')

  // ===== 方法 =====
  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function setUserRole(role) {
    if (!ROLES.includes(role)) return
    userRole.value = role
    localStorage.setItem(ROLE_KEY, role)
  }

  return { sidebarCollapsed, userRole, isAdmin, toggleSidebar, setUserRole }
})

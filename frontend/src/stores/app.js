import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', () => {
  // ===== 状态 =====
  const sidebarCollapsed = ref(false)
  const userRole = ref('admin') // TODO: 后续从后端 auth 接口获取

  // ===== 计算属性 =====
  const isAdmin = computed(() => userRole.value === 'admin')

  // ===== 方法 =====
  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function setUserRole(role) {
    userRole.value = role
  }

  return { sidebarCollapsed, userRole, isAdmin, toggleSidebar, setUserRole }
})

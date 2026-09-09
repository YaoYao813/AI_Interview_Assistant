import { createRouter, createWebHistory } from 'vue-router'
import { useAppStore } from '@/stores/app'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('../views/Dashboard.vue'),
  },
  {
    path: '/knowledge',
    name: 'KnowledgeChat',
    component: () => import('../views/KnowledgeChat.vue'),
  },
  {
    path: '/resume',
    name: 'ResumeAnalysis',
    component: () => import('../views/ResumeAnalysis.vue'),
  },
  {
    path: '/interview',
    name: 'MockInterview',
    component: () => import('../views/MockInterview.vue'),
  },
  {
    path: '/learning',
    name: 'LearningPath',
    component: () => import('../views/LearningPath.vue'),
  },
  {
    path: '/admin/knowledge',
    name: 'KnowledgeAdmin',
    component: () => import('../views/admin/KnowledgeAdmin.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：Admin 权限检查
router.beforeEach((to, from, next) => {
  if (to.path.startsWith('/admin/')) {
    const appStore = useAppStore()
    if (!appStore.isAdmin) {
      return next('/')
    }
  }
  next()
})

export default router

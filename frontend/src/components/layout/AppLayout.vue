<template>
  <div class="app-layout">
    <!-- 一级导航栏（最左窄栏） -->
    <AppSidebar />

    <!-- 主区域：二级侧栏 + 主内容，由各业务视图内部渲染 -->
    <div class="main-area">
      <router-view v-slot="{ Component }">
        <keep-alive>
          <component :is="Component" />
        </keep-alive>
      </router-view>
    </div>
  </div>
</template>

<script setup>
import AppSidebar from './AppSidebar.vue'
</script>

<style scoped>
.app-layout {
  display: flex; height: 100vh; overflow: hidden;
  background: var(--bg-main-content);
}
.main-area { flex: 1; overflow: hidden; }
</style>

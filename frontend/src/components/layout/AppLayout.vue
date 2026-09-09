<template>
  <div class="app-layout">
    <AppSidebar />
    <div class="main-area">
      <AppHeader />
      <div class="main-content">
        <router-view />
      </div>
    </div>
  </div>
</template>

<script setup>
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'
</script>

<style scoped>
.app-layout { display: flex; height: 100vh; overflow: hidden; }
.main-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.main-content { flex: 1; overflow-y: auto; }
</style>

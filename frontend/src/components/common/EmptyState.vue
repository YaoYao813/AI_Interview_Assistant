<template>
  <div class="empty-state">
    <div class="empty-icon"><LineIcon :name="icon" :size="44" :stroke-width="1.3" /></div>
    <p class="empty-title">{{ title }}</p>
    <p class="empty-desc" v-if="description">{{ description }}</p>
    <slot />
  </div>
</template>

<script setup>
import LineIcon from './LineIcon.vue'

defineProps({
  icon: { type: String, default: 'inbox' },
  title: { type: String, default: '暂无数据' },
  description: { type: String, default: '' },
})
</script>

<style scoped>
.empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 60px 20px; color: var(--text-secondary);
}
.empty-icon { margin-bottom: 16px; display: flex; }
.empty-title { font-size: 16px; font-weight: 500; color: var(--text-regular); margin-bottom: 8px; }
.empty-desc { font-size: 14px; max-width: 300px; text-align: center; }
</style>

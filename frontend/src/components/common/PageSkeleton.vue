<template>
  <div class="page-skeleton">
    <el-skeleton :rows="rows" animated />
  </div>
</template>

<script setup>
defineProps({
  rows: { type: Number, default: 6 },
})
</script>

<style scoped>
.page-skeleton { padding: 24px; max-width: 800px; margin: 0 auto; }
</style>

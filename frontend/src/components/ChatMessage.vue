<template>
  <div class="chat-message" :class="role">
    <div class="content"><slot /></div>
  </div>
</template>

<script setup>
defineProps({
  role: { type: String, default: 'user' },
})
</script>

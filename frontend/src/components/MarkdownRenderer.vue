<template>
  <div class="markdown-renderer" v-html="rendered"></div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  content: { type: String, default: '' },
})

const rendered = computed(() => {
  // TODO: replace with a proper markdown parser (e.g. marked)
  return props.content
})
</script>

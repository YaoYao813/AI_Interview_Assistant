<template>
  <div class="file-upload">
    <input type="file" @change="handleChange" />
  </div>
</template>

<script setup>
const emit = defineEmits(['upload'])

function handleChange(e) {
  const file = e.target.files?.[0]
  if (file) {
    const fd = new FormData()
    fd.append('file', file)
    emit('upload', fd)
  }
}
</script>

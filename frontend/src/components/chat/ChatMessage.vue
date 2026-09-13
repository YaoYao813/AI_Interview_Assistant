<template>
  <div class="chat-message" :class="role">
    <div class="message-avatar">
      <LineIcon :name="role === 'user' ? 'user' : 'bot'" :size="18" />
    </div>
    <div class="message-body">
      <div class="message-text" v-html="renderedContent" />
      <div v-if="isLoading" class="typing-indicator">
        <span /><span /><span />
      </div>
      <SourceCard v-if="sources.length" :sources="sources" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import SourceCard from './SourceCard.vue'
import LineIcon from '@/components/common/LineIcon.vue'

const props = defineProps({
  role: { type: String, required: true }, // 'user' | 'assistant'
  content: { type: String, default: '' },
  sources: { type: Array, default: () => [] },
  isLoading: { type: Boolean, default: false },
})

const renderedContent = computed(() => {
  if (!props.content) return ''
  return marked(props.content)
})
</script>

<style scoped>
.chat-message {
  display: flex; gap: 12px; padding: 16px 0;
}
.chat-message.user { flex-direction: row-reverse; }
.message-avatar {
  width: 36px; height: 36px; border-radius: 50%; background: var(--bg-hover);
  display: flex; align-items: center; justify-content: center; font-size: 18px;
  flex-shrink: 0;
}
.chat-message.user .message-avatar { background: var(--bg-hover); }
.message-body { max-width: 75%; }
.chat-message.user .message-body { text-align: right; }
.message-text {
  padding: 12px 16px; border-radius: 12px; font-size: 14px; line-height: 1.7;
  background: var(--bg-input); color: var(--text-primary);
}
.chat-message.user .message-text { background: var(--primary); color: var(--text-button-primary); }

/* Markdown 内部样式 */
.message-text :deep(h1), .message-text :deep(h2), .message-text :deep(h3) { margin: 8px 0 4px; }
.message-text :deep(p) { margin: 4px 0; }
.message-text :deep(code) { background: rgba(255,255,255,0.08); padding: 1px 4px; border-radius: 3px; font-size: 13px; }
.message-text :deep(pre) { background: #282c34; color: #abb2bf; padding: 12px; border-radius: 6px; overflow-x: auto; margin: 8px 0; }
.message-text :deep(pre code) { background: none; padding: 0; }
.chat-message.user .message-text :deep(code) { background: rgba(0,0,0,0.1); }
.chat-message.user .message-text :deep(pre) { background: rgba(0,0,0,0.3); }

/* 打字动画 */
.typing-indicator { display: flex; gap: 4px; padding: 8px 0; }
.typing-indicator span {
  width: 6px; height: 6px; border-radius: 50%; background: var(--text-secondary);
  animation: bounce 1.4s infinite ease-in-out both;
}
.typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}
</style>

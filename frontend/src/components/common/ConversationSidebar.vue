<template>
  <aside class="conv-sidebar">
    <!-- 工作区 -->
    <div class="workspace">
      <LineIcon class="workspace-icon" :name="workspaceIcon" :size="18" />
      <span class="workspace-name">{{ workspaceName }}</span>
    </div>

    <!-- 新建对话 -->
    <div class="sidebar-actions">
      <button class="new-btn" @click="$emit('create')">＋ 新对话</button>
    </div>

    <!-- 搜索 -->
    <div class="sidebar-search">
      <input v-model="keyword" class="search-input" type="text" placeholder="搜索历史记录..." />
    </div>

    <!-- 历史列表 -->
    <div class="conversation-list">
      <div
        v-for="conv in filteredConversations"
        :key="conv.id"
        class="conv-item"
        :class="{ active: conv.id === activeId }"
        @click="$emit('switch', conv.id)"
      >
        <span class="conv-title">{{ titleOf(conv) }}</span>
        <span class="conv-summary">{{ summaryOf(conv) }}</span>
        <span class="conv-date">{{ formatDate(conv.updatedAt) }}</span>
        <el-popconfirm
          title="删除此对话？"
          @confirm="$emit('delete', conv.id)"
          @click.stop
        >
          <template #reference>
            <LineIcon class="conv-delete" name="trash" :size="13" @click.stop />
          </template>
        </el-popconfirm>
      </div>
      <EmptyState
        v-if="filteredConversations.length === 0"
        :icon="keyword ? 'search' : emptyIcon"
        :title="keyword ? '没有匹配的对话' : emptyTitle"
        :description="keyword ? '' : emptyDesc"
      />
    </div>

    <div v-if="$slots.footer" class="sidebar-footer">
      <slot name="footer" />
    </div>
  </aside>
</template>

<script setup>
import { computed, ref } from 'vue'
import EmptyState from './EmptyState.vue'
import LineIcon from './LineIcon.vue'

const props = defineProps({
  conversations: { type: Array, default: () => [] },
  activeId: { type: String, default: null },
  titleOf: { type: Function, default: () => '未命名' },
  summaryOf: { type: Function, default: () => '' },
  workspaceIcon: { type: String, default: 'chat' },
  workspaceName: { type: String, default: '工作区' },
  emptyIcon: { type: String, default: 'inbox' },
  emptyTitle: { type: String, default: '暂无历史' },
  emptyDesc: { type: String, default: '' },
})

defineEmits(['create', 'switch', 'delete'])

const keyword = ref('')

const filteredConversations = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return props.conversations
  return props.conversations.filter((conv) => {
    const title = String(props.titleOf(conv) || '').toLowerCase()
    const summary = String(props.summaryOf(conv) || '').toLowerCase()
    return title.includes(kw) || summary.includes(kw)
  })
})

function formatDate(ts) {
  const d = new Date(ts)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
</script>

<style scoped>
.conv-sidebar {
  width: 260px; background: var(--bg-sidebar-level2);
  border-right: 1px solid var(--border-line);
  display: flex; flex-direction: column; flex-shrink: 0;
}

/* 工作区 */
.workspace {
  display: flex; align-items: center; gap: 8px;
  padding: 16px 16px 12px; flex-shrink: 0;
}
.workspace-icon { font-size: 18px; }
.workspace-name { font-size: 14px; font-weight: 600; color: var(--text-primary); }

/* 操作区 */
.sidebar-actions { padding: 0 12px 8px; flex-shrink: 0; }
.new-btn {
  width: 100%; height: 38px; border: none; border-radius: var(--radius);
  background: var(--bg-button-primary); color: var(--text-button-primary);
  font-size: 14px; font-weight: 500; cursor: pointer; transition: background 0.15s;
}
.new-btn:hover { background: #e5e5e5; }
.new-btn:active { background: #d4d4d8; }

/* 搜索 */
.sidebar-search { padding: 0 12px 8px; flex-shrink: 0; }
.search-input {
  width: 100%; height: 34px; padding: 0 12px; border-radius: var(--radius);
  background: var(--bg-input); border: 1px solid transparent;
  color: var(--text-primary); font-size: 13px; outline: none;
  transition: border-color 0.15s;
}
.search-input::placeholder { color: var(--text-secondary); }
.search-input:focus { border-color: var(--border-line); }

/* 历史列表 */
.conversation-list { flex: 1; overflow-y: auto; padding: 4px 8px; }
.conv-item {
  display: grid; grid-template-columns: 1fr 24px; grid-template-rows: auto auto auto;
  padding: 10px 10px; border-radius: var(--radius); cursor: pointer;
  transition: background 0.15s; margin-bottom: 2px;
}
.conv-item:hover { background: var(--bg-hover); }
.conv-item.active { background: var(--bg-hover); }
.conv-title {
  font-size: 14px; font-weight: 500; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  grid-column: 1; grid-row: 1;
}
.conv-summary {
  font-size: 12px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; grid-column: 1; grid-row: 2; margin-top: 2px;
}
.conv-date { font-size: 12px; color: var(--text-secondary); grid-column: 1; grid-row: 3; margin-top: 2px; }
.conv-delete {
  font-size: 12px; cursor: pointer; opacity: 0; transition: opacity 0.15s;
  grid-column: 2; grid-row: 1 / 4; align-self: center; text-align: center;
}
.conv-item:hover .conv-delete { opacity: 0.6; }
.conv-item:hover .conv-delete:hover { opacity: 1; }

/* 页脚 */
.sidebar-footer {
  padding: 10px 16px; font-size: 12px; color: var(--text-secondary);
  border-top: 1px solid var(--border-line); flex-shrink: 0;
}
</style>

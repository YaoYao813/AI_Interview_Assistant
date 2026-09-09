<template>
  <div class="knowledge-admin">
    <!-- 统计卡片 -->
    <div class="stats-row">
      <div class="stat-card">
        <span class="stat-num">{{ stats.document_count }}</span>
        <span class="stat-label">文档总数</span>
      </div>
      <div class="stat-card">
        <span class="stat-num">{{ stats.chunk_count }}</span>
        <span class="stat-label">文本块数</span>
      </div>
      <div class="stat-card">
        <span class="stat-num">ChromaDB</span>
        <span class="stat-label">存储引擎</span>
      </div>
    </div>

    <!-- 上传区 + 文件表格 -->
    <div class="content-row">
      <!-- 上传区 -->
      <div class="upload-section">
        <h3>上传文档</h3>
        <el-upload
          ref="uploadRef"
          class="upload-area"
          drag
          :auto-upload="false"
          :on-change="handleFileChange"
          :limit="1"
          accept=".pdf,.docx,.doc,.md,.txt"
        >
          <div class="upload-placeholder">
            <span class="upload-icon">📁</span>
            <p>拖拽文件到此处或<em>点击上传</em></p>
            <p class="upload-hint">支持 PDF / DOCX / MD / TXT，最大 20MB</p>
          </div>
        </el-upload>
        <div v-if="selectedFile" class="file-info">
          <span>{{ selectedFile.name }}</span>
          <span class="file-size">({{ formatSize(selectedFile.size) }})</span>
        </div>
        <el-button
          type="primary"
          :disabled="!selectedFile || uploading"
          :loading="uploading"
          @click="handleUpload"
          style="width: 100%; margin-top: 12px;"
        >
          {{ uploading ? '上传中...' : '开始上传' }}
        </el-button>
      </div>

      <!-- 文档表格 -->
      <div class="table-section">
        <h3>已上传文档</h3>
        <el-table :data="documents" style="width: 100%" v-loading="tableLoading" empty-text="暂无文档">
          <el-table-column prop="filename" label="文件名" min-width="180">
            <template #default="{ row }">
              <span class="doc-name">{{ row.filename }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="chunk_count" label="文本块" width="90" align="center" />
          <el-table-column prop="created_at" label="上传时间" width="170" align="center">
            <template #default="{ row }">
              {{ row.created_at || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ row }">
              <el-popconfirm
                title="确认删除该文档？"
                @confirm="handleDelete(row.document_id)"
              >
                <template #reference>
                  <el-button type="danger" size="small" text>删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { uploadDocument, getDocumentList, deleteDocument, getKnowledgeStatistics } from '@/api/knowledge'

const uploadRef = ref(null)
const documents = ref([])
const stats = ref({ document_count: 0, chunk_count: 0 })
const selectedFile = ref(null)
const uploading = ref(false)
const tableLoading = ref(false)

onMounted(() => { refreshAll() })

async function refreshAll() {
  await Promise.all([loadDocuments(), loadStats()])
}

async function loadDocuments() {
  tableLoading.value = true
  try {
    const res = await getDocumentList()
    documents.value = res.data?.documents || []
  } catch { documents.value = [] }
  finally { tableLoading.value = false }
}

async function loadStats() {
  try {
    const res = await getKnowledgeStatistics()
    stats.value = res.data || { document_count: 0, chunk_count: 0 }
  } catch { /* ignore */ }
}

function handleFileChange(file) {
  selectedFile.value = file.raw
}

async function handleUpload() {
  if (!selectedFile.value) return
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', selectedFile.value)
    await uploadDocument(fd)
    ElMessage.success('上传成功')
    uploadRef.value.clearFiles()
    selectedFile.value = null
    await refreshAll()
  } catch (e) {
    const msg = e?.response?.data?.detail?.error || e?.response?.data?.message || '上传失败'
    ElMessage.error(msg)
  } finally {
    uploading.value = false
  }
}

async function handleDelete(id) {
  try {
    await deleteDocument(id)
    ElMessage.success('已删除')
    await refreshAll()
  } catch (e) {
    const msg = e?.response?.data?.message || '删除失败'
    ElMessage.error(msg)
  }
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + 'B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB'
  return (bytes / 1024 / 1024).toFixed(1) + 'MB'
}
</script>

<style scoped>
.knowledge-admin { max-width: 1100px; margin: 0 auto; padding: 24px; }

.stats-row { display: flex; gap: 16px; margin-bottom: 24px; }
.stat-card {
  flex: 1; padding: 20px; background: var(--bg-white);
  border: 1px solid var(--border-color); border-radius: var(--radius);
  display: flex; flex-direction: column; align-items: center; gap: 4px;
}
.stat-num { font-size: 28px; font-weight: 700; color: var(--primary); }
.stat-label { font-size: 13px; color: var(--text-secondary); }

.content-row { display: grid; grid-template-columns: 320px 1fr; gap: 24px; }
.upload-section h3, .table-section h3 { font-size: 16px; font-weight: 600; margin-bottom: 14px; }

.upload-area :deep(.el-upload-dragger) { padding: 32px 20px; }
.upload-placeholder { text-align: center; color: var(--text-secondary); }
.upload-icon { font-size: 40px; display: block; margin-bottom: 10px; }
.upload-placeholder p { font-size: 14px; margin: 4px 0; }
.upload-placeholder em { color: var(--primary); font-style: normal; }
.upload-hint { font-size: 12px; color: var(--text-secondary); }

.file-info {
  margin-top: 10px; padding: 10px 12px; background: var(--primary-light);
  border-radius: 6px; font-size: 13px; display: flex; justify-content: space-between;
}
.file-size { color: var(--text-secondary); }

.table-section { min-width: 0; }
.doc-name {
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block;
}
</style>

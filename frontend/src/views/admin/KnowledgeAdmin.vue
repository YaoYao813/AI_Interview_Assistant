<template>
  <div class="knowledge-admin">
    <div class="admin-inner">
      <!-- ==================== 主页面 ==================== -->
      <template v-if="!detailOpen">
        <div class="page-head">
          <h2>知识库管理</h2>
          <p>上传文档到向量库，供知识问答检索使用</p>
        </div>

        <div class="content-row">
          <!-- 上传区 -->
          <section class="upload-section">
            <h3>上传文档</h3>
            <!-- 拖拽由本组件在捕获阶段接管：el-upload 自身的 drop 会 stopPropagation，
                 且其内置目录遍历会丢失相对路径 -->
            <div
              class="drop-wrap"
              :class="{ 'is-drag': dragActive }"
              @dragover.capture.prevent.stop="dragActive = true"
              @dragleave.capture="onDragLeave"
              @drop.capture.prevent.stop="handleDrop"
            >
              <el-upload
                ref="uploadRef"
                class="upload-area"
                drag
                multiple
                :auto-upload="false"
                :show-file-list="false"
                :on-change="handleFileChange"
                accept=".pdf,.docx,.doc,.md,.txt"
              >
                <div class="upload-placeholder">
                  <span class="upload-icon"><LineIcon name="folder" :size="40" :stroke-width="1.3" /></span>
                  <p>拖拽文件或整个文件夹到此处，或<em>点击上传</em></p>
                  <p class="upload-hint">支持 PDF / DOCX / MD / TXT，单个最大 20MB</p>
                </div>
              </el-upload>
            </div>

            <div class="pick-row">
              <el-button :disabled="uploading" @click="pickDirectory">
                <LineIcon name="folder" :size="14" style="margin-right: 6px" />选择文件夹
              </el-button>
              <span class="pick-hint">自动递归收集子目录内支持的文档</span>
            </div>
            <input
              ref="dirInputRef"
              class="dir-input"
              type="file"
              webkitdirectory
              multiple
              @change="handleDirSelect"
            />

            <!-- 待上传队列 -->
            <template v-if="queue.length">
              <div class="queue-head">
                <span class="queue-count">待上传 {{ pendingCount }} 个</span>
                <el-button text size="small" :disabled="uploading" @click="clearQueue">清空列表</el-button>
              </div>
              <div class="queue-list">
                <div
                  v-for="item in queue"
                  :key="item.uid"
                  class="queue-item"
                  :class="item.status"
                >
                  <LineIcon class="q-icon" :name="item.status === 'fail' ? 'alert' : 'file'" :size="15" />
                  <div class="q-body">
                    <span class="q-name" :title="item.name">{{ item.name }}</span>
                    <span class="q-meta">{{ formatSize(item.size) }} · {{ statusText(item) }}</span>
                  </div>
                  <button
                    v-if="item.status === 'fail'"
                    class="q-retry"
                    :disabled="uploading"
                    @click="retryItem(item)"
                  >重试</button>
                  <LineIcon
                    v-if="item.status !== 'uploading'"
                    class="q-remove"
                    name="trash"
                    :size="14"
                    @click="removeItem(item)"
                  />
                </div>
              </div>
              <el-button
                type="primary"
                :disabled="uploading || !pendingCount"
                :loading="uploading"
                @click="handleUpload"
                style="width: 100%; margin-top: 12px;"
              >
                {{ uploading ? `上传中 ${progress.done}/${progress.total}...` : `开始上传（${pendingCount}）` }}
              </el-button>
            </template>
          </section>

          <!-- 已上传文档：汇总入口卡片 -->
          <section class="summary-section">
            <h3>已上传文档</h3>

            <div v-if="loadError" class="load-error">
              <LineIcon class="load-error-icon" name="alert" :size="20" />
              <div class="load-error-body">
                <span class="load-error-title">数据加载失败</span>
                <span class="load-error-desc">{{ loadError }}</span>
              </div>
              <el-button size="small" :loading="tableLoading" @click="refreshAll">重试</el-button>
            </div>

            <template v-else>
              <div class="summary-card" @click="openDetail">
                <LineIcon class="summary-icon" name="book" :size="26" />
                <div class="summary-body">
                  <span class="summary-num">{{ stats.document_count }}</span>
                  <span class="summary-unit">篇文档已入库</span>
                  <span class="summary-time">最近更新：{{ lastUpdatedText }}</span>
                </div>
                <span class="summary-link">
                  查看全部<LineIcon name="arrow-right" :size="14" />
                </span>
              </div>
              <p class="summary-tip">共 {{ stats.chunk_count }} 个文本块 · 存储引擎 ChromaDB</p>
            </template>
          </section>
        </div>
      </template>

      <!-- ==================== 文档详情页 ==================== -->
      <template v-else>
        <div class="detail-head">
          <el-button text class="back-btn" @click="closeDetail">
            <LineIcon name="arrow-left" :size="15" style="margin-right: 4px" />返回
          </el-button>
          <h2>文档详情</h2>
          <span class="detail-sub">存储引擎 ChromaDB</span>
        </div>

        <div v-if="loadError" class="load-error">
          <LineIcon class="load-error-icon" name="alert" :size="20" />
          <div class="load-error-body">
            <span class="load-error-title">数据加载失败</span>
            <span class="load-error-desc">{{ loadError }}</span>
          </div>
          <el-button size="small" :loading="tableLoading" @click="refreshAll">重试</el-button>
        </div>

        <!-- 加载失败时数字一律显示「—」而不是 0：0 和「库里真的是空的」长得一模一样 -->
        <div class="stats-row">
          <div class="stat-card">
            <span class="stat-num">{{ loadError ? '—' : stats.document_count }}</span>
            <span class="stat-label">文档总数</span>
          </div>
          <div class="stat-card">
            <span class="stat-num">{{ loadError ? '—' : stats.chunk_count }}</span>
            <span class="stat-label">文本块数</span>
          </div>
          <div class="stat-card">
            <span class="stat-num">{{ loadError ? '—' : totalSizeText }}</span>
            <span class="stat-label">总文件大小</span>
            <span
              v-if="!loadError && stats.sized_document_count < stats.document_count"
              class="stat-sub"
            >
              已记录 {{ stats.sized_document_count }}/{{ stats.document_count }} 篇
            </span>
          </div>
          <div class="stat-card">
            <!-- 能出现在向量库里就等于已向量化，这个数恒等于文档总数 -->
            <span class="stat-num">{{ loadError ? '—' : stats.document_count }}</span>
            <span class="stat-label">已向量化</span>
          </div>
        </div>

        <div class="detail-toolbar">
          <LineIcon name="search" :size="14" />
          <input
            v-model="docKeyword"
            class="doc-search"
            type="text"
            placeholder="按文件名搜索"
            @input="onSearchInput"
          />
          <el-select
            v-model="formatFilter"
            placeholder="全部格式"
            clearable
            size="small"
            style="width: 120px"
            @change="onFilterChange"
          >
            <el-option v-for="f in formatOptions" :key="f" :label="f" :value="f" />
          </el-select>
        </div>

        <el-table
          :data="documents"
          style="width: 100%"
          v-loading="tableLoading"
          :empty-text="loadError ? '加载失败，请重试' : (docKeyword ? '没有匹配的文档' : '暂无文档')"
        >
          <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip />
          <el-table-column label="格式" width="80" align="center">
            <template #default="{ row }">{{ formatOf(row.filename) }}</template>
          </el-table-column>
          <el-table-column label="大小" width="100" align="center">
            <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
          </el-table-column>
          <el-table-column label="上传时间" width="150" align="center">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="向量状态" width="110" align="center">
            <template #default="{ row }">
              <span class="status-tag" :class="row.chunk_count ? 'done' : 'none'">
                {{ row.chunk_count ? '已向量化' : '未向量化' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ row }">
              <el-popconfirm title="确认删除该文档？" @confirm="handleDelete(row.document_id)">
                <template #reference>
                  <el-button type="danger" size="small" text>删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>

        <div v-if="!loadError && total > 0" class="pager">
          <el-pagination
            layout="total, sizes, prev, pager, next"
            :total="total"
            :current-page="page"
            :page-size="pageSize"
            :page-sizes="[10, 20, 50, 100]"
            @current-change="onPageChange"
            @size-change="onSizeChange"
          />
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, genFileId } from 'element-plus'
import { uploadDocument, getDocumentList, deleteDocument, getKnowledgeStatistics } from '@/api/knowledge'
import LineIcon from '@/components/common/LineIcon.vue'

const ALLOWED_EXT = ['.pdf', '.docx', '.doc', '.md', '.txt']

const uploadRef = ref(null)
const dirInputRef = ref(null)
const documents = ref([])
const stats = ref({ document_count: 0, chunk_count: 0 })
const queue = ref([])
const uploading = ref(false)
const progress = ref({ done: 0, total: 0 })
const tableLoading = ref(false)
// 非空表示列表/统计加载失败，值是失败原因。用来把「加载失败」和「库里就是空的」分开
const loadError = ref(null)
const detailOpen = ref(false)
const docKeyword = ref('')
const formatFilter = ref('')
const dragActive = ref(false)
// 分页由服务端负责：documents 只是当前页
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const pendingCount = computed(() => queue.value.filter(i => i.status !== 'success').length)

// 选项用支持的格式全集，不按当前页的数据推导——否则翻页时选项会跳变
const formatOptions = ALLOWED_EXT.map(e => e.slice(1).toUpperCase())

// 大小来自后端 metadata；⑬ 之前上传的老文档没有这个字段，显示「—」
const totalSizeText = computed(
  () => (stats.value.sized_document_count ? formatSize(stats.value.total_size || 0) : '—')
)
// 文档按上传时间倒序，最新的一篇必在第 1 页；closeDetail 会重置到第 1 页
const lastUpdatedText = computed(() => {
  const list = documents.value.map(d => d.created_at).filter(Boolean).sort()
  return list.length ? formatTime(list[list.length - 1]) : '暂无记录'
})

onMounted(() => { refreshAll() })

// 两个请求的成败统一收口在这里，不在各自的 catch 里写 loadError：
// 它们并发，先成功的那次会把后失败的原因覆盖掉，错误就时有时无。
// 失败时保留原有数据不清空——请求失败不等于库里没数据，
// 清空会把一次网络抖动演成「文档全丢了」，而页面还会照着 0 渲染。
async function refreshAll() {
  tableLoading.value = true
  try {
    const [listRes, statsRes] = await Promise.all([
      // 过滤与分页都在服务端：分页前过滤，total 才是「匹配到的总数」，
      // 否则搜索只会搜当前这一页
      getDocumentList({
        limit: pageSize.value,
        offset: (page.value - 1) * pageSize.value,
        keyword: docKeyword.value.trim(),
        format: formatFilter.value,
      }),
      getKnowledgeStatistics(),
    ])
    documents.value = listRes.data?.documents || []
    total.value = listRes.data?.total || 0
    stats.value = statsRes.data || { document_count: 0, chunk_count: 0 }
    loadError.value = null
  } catch (e) {
    loadError.value = e?.response?.data?.message || '无法连接后端服务'
  } finally {
    tableLoading.value = false
  }
}

function openDetail() {
  detailOpen.value = true
  refreshAll()
}

function closeDetail() {
  detailOpen.value = false
  docKeyword.value = ''
  formatFilter.value = ''
  // 回到第 1 页：主页面的「最近更新」依赖第 1 页的数据
  page.value = 1
  refreshAll()
}

/* ===== 分页与筛选（均走服务端） ===== */

function onPageChange(p) {
  page.value = p
  refreshAll()
}

function onSizeChange(size) {
  if (size === pageSize.value) return
  pageSize.value = size
  page.value = 1
  refreshAll()
}

// 输入防抖：逐字符请求会把后端打成筛子
let searchTimer = null
function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    refreshAll()
  }, 300)
}

function onFilterChange() {
  page.value = 1
  refreshAll()
}

/* ===== 队列管理 ===== */

function extOf(name) {
  const i = name.lastIndexOf('.')
  return i === -1 ? '' : name.slice(i).toLowerCase()
}

function isAllowed(name) {
  return ALLOWED_EXT.includes(extOf(name))
}

// 把 [{ raw, path }] 追加进队列，按扩展名过滤、按「相对路径 + 大小」去重
function addFiles(list, silent = false) {
  const seen = new Set(queue.value.map(i => `${i.name}|${i.size}`))
  let added = 0
  let dup = 0
  let bad = 0

  for (const { raw, path } of list) {
    const name = path || raw.webkitRelativePath || raw.name
    if (!isAllowed(name)) { bad++; continue }
    const key = `${name}|${raw.size}`
    if (seen.has(key)) { dup++; continue }
    seen.add(key)
    queue.value.push({
      uid: genFileId(),
      name,
      size: raw.size,
      raw,
      status: 'ready',
      error: '',
    })
    added++
  }

  if (silent) return
  if (dup) ElMessage.warning(`已跳过 ${dup} 个重复文件`)
  if (bad) ElMessage.warning(`已跳过 ${bad} 个不支持的文件`)
  if (added) ElMessage.success(`已添加 ${added} 个文件`)
  else if (!dup && !bad) ElMessage.warning('未发现支持的文档')
}

// el-upload 每选中一个文件触发一次，静默入队避免刷屏；不支持/文件夹占位项直接忽略
function handleFileChange(uploadFile) {
  const raw = uploadFile?.raw
  if (!raw || !isAllowed(raw.name)) return
  addFiles([{ raw, path: raw.webkitRelativePath || raw.name }], true)
}

function pickDirectory() {
  dirInputRef.value?.click()
}

function handleDirSelect(e) {
  addFiles(Array.from(e.target.files || []).map(f => ({ raw: f, path: f.webkitRelativePath || f.name })))
  e.target.value = ''
}

// 递归读取拖入的 FileSystemEntry，path 逐层拼接以保留相对路径
function readEntry(entry, path, out) {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file(
        (f) => { out.push({ raw: f, path }); resolve() },
        () => resolve()
      )
      return
    }
    if (!entry.isDirectory) { resolve(); return }
    const reader = entry.createReader()
    const readBatch = () => {
      reader.readEntries(
        async (ents) => {
          if (!ents.length) { resolve(); return }
          for (const en of ents) await readEntry(en, `${path}/${en.name}`, out)
          readBatch()
        },
        () => resolve()
      )
    }
    readBatch()
  })
}

function onDragLeave(e) {
  if (!(e.currentTarget instanceof Element) || !e.currentTarget.contains(e.relatedTarget)) {
    dragActive.value = false
  }
}

async function handleDrop(e) {
  dragActive.value = false
  const dt = e.dataTransfer
  if (!dt) return

  // dataTransfer.items 在 await 后失效，先同步取出所有条目
  const entries = []
  for (const it of Array.from(dt.items || [])) {
    if (it.kind !== 'file') continue
    const en = it.webkitGetAsEntry?.()
    if (en) entries.push(en)
  }

  // 浏览器不支持条目 API 时退回平面文件列表
  if (!entries.length) {
    addFiles(Array.from(dt.files || []).map(f => ({ raw: f, path: f.name })))
    return
  }

  const out = []
  for (const en of entries) await readEntry(en, en.name, out)
  addFiles(out)
}

function removeItem(item) {
  const i = queue.value.indexOf(item)
  if (i !== -1) queue.value.splice(i, 1)
}

function clearQueue() {
  queue.value.splice(0, queue.value.length)
  uploadRef.value?.clearFiles()
}

/* ===== 上传 ===== */

async function uploadOne(item) {
  item.status = 'uploading'
  item.error = ''
  try {
    const fd = new FormData()
    fd.append('file', item.raw, item.name)
    const res = await uploadDocument(fd)
    item.status = 'success'
    return true
  } catch (e) {
    item.status = 'fail'
    item.error = e?.response?.data?.detail?.error || e?.response?.data?.message || '上传失败'
    return false
  }
}

// 逐个上传：每个文件独立成败与超时；全部成功清空队列，部分失败仅保留失败项
async function handleUpload() {
  const pending = queue.value.filter(i => i.status !== 'success')
  if (!pending.length) return

  uploading.value = true
  progress.value = { done: 0, total: pending.length }
  const failed = []

  for (const item of pending) {
    if (!(await uploadOne(item))) failed.push(item)
    progress.value.done++
  }

  uploading.value = false
  await refreshAll()

  if (!failed.length) {
    clearQueue()
    ElMessage.success(`成功上传 ${pending.length} 个文件`)
    return
  }

  queue.value.splice(0, queue.value.length, ...failed)
  const okCount = pending.length - failed.length
  if (okCount) ElMessage.warning(`成功 ${okCount} 个，失败 ${failed.length} 个`)
  else ElMessage.error(`上传失败：${failed[0].error}`)
}

async function retryItem(item) {
  if (uploading.value) return
  uploading.value = true
  progress.value = { done: 0, total: 1 }
  const ok = await uploadOne(item)
  uploading.value = false

  if (!ok) {
    ElMessage.error(item.error)
    return
  }
  removeItem(item)
  await refreshAll()
  ElMessage.success(`已上传 ${item.name}`)
  if (!queue.value.length) clearQueue()
}

async function handleDelete(id) {
  try {
    await deleteDocument(id)
    ElMessage.success('已删除')
    // 删掉本页最后一条时回退一页，否则停在空页
    if (documents.value.length === 1 && page.value > 1) page.value--
    await refreshAll()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '删除失败')
  }
}

/* ===== 展示格式化 ===== */

function formatSize(bytes) {
  if (typeof bytes !== 'number') return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatOf(filename) {
  const ext = extOf(String(filename || ''))
  return ext ? ext.slice(1).toUpperCase() : '—'
}

function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function statusText(item) {
  if (item.status === 'uploading') return '上传中'
  if (item.status === 'success') return '已完成'
  if (item.status === 'fail') return item.error || '上传失败'
  return '待上传'
}
</script>

<style scoped>
.knowledge-admin { height: 100%; overflow-y: auto; }
.admin-inner { max-width: 1100px; margin: 0 auto; padding: 24px; }

.page-head { margin-bottom: 20px; }
.page-head h2 { margin: 0 0 4px; font-size: 20px; font-weight: 600; color: var(--text-primary); }
.page-head p { margin: 0; font-size: 13px; color: var(--text-secondary); }

.content-row { display: grid; grid-template-columns: 360px 1fr; gap: 24px; align-items: start; }
.upload-section h3, .summary-section h3 { font-size: 16px; font-weight: 600; margin-bottom: 14px; }

/* 上传区 */
.upload-area :deep(.el-upload-dragger) { padding: 28px 16px; }
.drop-wrap.is-drag :deep(.el-upload-dragger) {
  border-color: var(--text-secondary); background: var(--bg-hover);
}
.upload-placeholder { text-align: center; color: var(--text-secondary); }
.upload-icon { display: flex; justify-content: center; margin-bottom: 10px; }
.upload-placeholder p { font-size: 14px; margin: 4px 0; }
.upload-placeholder em { color: var(--primary); font-style: normal; }
.upload-hint { font-size: 12px; color: var(--text-secondary); }

.pick-row { margin-top: 10px; display: flex; align-items: center; gap: 10px; }
.pick-hint { font-size: 12px; color: var(--text-secondary); }
.dir-input { display: none; }

/* 待上传队列 */
.queue-head {
  margin-top: 14px; display: flex; align-items: center; justify-content: space-between;
}
.queue-count { font-size: 13px; color: var(--text-secondary); }
.queue-list { max-height: 220px; overflow-y: auto; margin-top: 6px; }
.queue-item {
  display: flex; align-items: center; gap: 8px; padding: 8px 10px;
  border-radius: var(--radius); background: var(--bg-input); margin-bottom: 6px;
}
.queue-item.fail { background: rgba(192, 136, 136, 0.12); }
.q-icon { color: var(--text-secondary); }
.queue-item.fail .q-icon { color: #c08888; }
.q-body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.q-name {
  font-size: 13px; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.q-meta {
  font-size: 12px; color: var(--text-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.queue-item.fail .q-meta { color: #c08888; }
.q-retry {
  flex-shrink: 0; padding: 2px 8px; font-size: 12px; cursor: pointer;
  background: transparent; color: var(--text-primary);
  border: 1px solid var(--border-line); border-radius: var(--radius);
  transition: background 0.15s;
}
.q-retry:hover { background: var(--bg-hover); }
.q-retry:disabled { opacity: 0.5; cursor: not-allowed; }
.q-remove {
  flex-shrink: 0; cursor: pointer; color: var(--text-secondary);
  opacity: 0; transition: opacity 0.15s;
}
.queue-item:hover .q-remove { opacity: 0.7; }
.q-remove:hover { opacity: 1; }

/* 加载失败态（主页面与详情页共用） */
.load-error {
  display: flex; align-items: center; gap: 12px; padding: 16px 18px;
  margin-bottom: 20px;
  background: rgba(192, 136, 136, 0.08);
  border: 1px solid rgba(192, 136, 136, 0.35);
  border-radius: var(--radius);
}
.load-error-icon { color: #c08888; flex-shrink: 0; }
.load-error-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.load-error-title { font-size: 14px; color: var(--text-primary); }
.load-error-desc {
  font-size: 12px; color: var(--text-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* 汇总入口卡片 */
.summary-card {
  display: flex; align-items: center; gap: 16px; padding: 20px;
  background: var(--bg-white); border: 1px solid var(--border-line);
  border-radius: var(--radius); cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.summary-card:hover { background: var(--bg-hover); border-color: var(--border-color); }
.summary-icon { color: var(--text-primary); flex-shrink: 0; }
.summary-body { flex: 1; display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px; }
.summary-num { font-size: 28px; font-weight: 700; color: var(--primary); line-height: 1; }
.summary-unit { font-size: 13px; color: var(--text-secondary); }
.summary-time { width: 100%; font-size: 12px; color: var(--text-secondary); }
.summary-link {
  display: inline-flex; align-items: center; gap: 4px; flex-shrink: 0;
  font-size: 13px; color: var(--text-secondary);
}
.summary-card:hover .summary-link { color: var(--text-primary); }
.summary-tip { margin: 10px 0 0; font-size: 12px; color: var(--text-secondary); }

/* 详情页 */
.detail-head { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.detail-head h2 { margin: 0; font-size: 20px; font-weight: 600; color: var(--text-primary); }
.detail-sub { font-size: 12px; color: var(--text-secondary); }
.back-btn { padding-left: 0; }

.stats-row { display: flex; gap: 16px; margin-bottom: 20px; }
.stat-card {
  flex: 1; padding: 18px; background: var(--bg-white);
  border: 1px solid var(--border-line); border-radius: var(--radius);
  display: flex; flex-direction: column; align-items: center; gap: 4px;
}
.stat-num { font-size: 26px; font-weight: 700; color: var(--primary); }
.stat-label { font-size: 13px; color: var(--text-secondary); }
.stat-sub { font-size: 11px; color: var(--text-secondary); }

.detail-toolbar {
  display: flex; align-items: center; gap: 8px; margin-bottom: 14px;
  padding: 0 12px; height: 36px; max-width: 440px; border-radius: var(--radius);
  background: var(--bg-input); border: 1px solid transparent;
  color: var(--text-secondary); transition: border-color 0.15s;
}
.detail-toolbar:focus-within { border-color: var(--border-line); }
.doc-search {
  flex: 1; background: transparent; border: none; outline: none;
  color: var(--text-primary); font-size: 13px;
}
.doc-search::placeholder { color: var(--text-secondary); }

.status-tag {
  display: inline-block; padding: 1px 8px; border-radius: 10px;
  font-size: 12px; border: 1px solid transparent;
}

.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
.status-tag.done { color: #8aa88a; border-color: rgba(138, 168, 138, 0.4); }
.status-tag.none { color: var(--text-secondary); border-color: var(--border-line); }
</style>

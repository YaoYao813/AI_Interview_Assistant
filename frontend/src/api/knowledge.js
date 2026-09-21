import request, { API_BASE, TIMEOUT } from './request'

// ===== 知识库管理 =====

export function uploadDocument(formData) {
  return request.post('/knowledge/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: TIMEOUT.UPLOAD,
  })
}

export function getDocumentList() {
  return request.get('/knowledge/documents')
}

export function deleteDocument(id) {
  return request.delete(`/knowledge/documents/${id}`)
}

export function getKnowledgeStatistics() {
  return request.get('/knowledge/statistics')
}

// ===== RAG 问答 =====

// 流式问答：直连 fetch，不走 axios，故单独暴露地址
export const RAG_CHAT_STREAM_URL = `${API_BASE}/rag/chat/stream`

export function chatQuery(data, config = {}) {
  // 调用方传的是 { signal }（用于中断），档位放在前面，调用方仍可覆盖
  return request.post('/rag/chat', data, { timeout: TIMEOUT.LLM, ...config })
}

import request, { TIMEOUT } from './request'

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

export function getDocumentDetail(id) {
  return request.get(`/knowledge/documents/${id}`)
}

export function deleteDocument(id) {
  return request.delete(`/knowledge/documents/${id}`)
}

export function getKnowledgeStatistics() {
  return request.get('/knowledge/statistics')
}

// ===== RAG 问答 =====

export function chatQuery(data, config = {}) {
  // 调用方传的是 { signal }（用于中断），档位放在前面，调用方仍可覆盖
  return request.post('/rag/chat', data, { timeout: TIMEOUT.LLM, ...config })
}

import request from './request'

// ===== 知识库管理 =====

export function uploadDocument(formData) {
  return request.post('/knowledge/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
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

export function chatQuery(data, config) {
  return request.post('/rag/chat', data, config)
}

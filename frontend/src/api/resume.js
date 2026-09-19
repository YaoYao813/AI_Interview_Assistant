import request, { API_BASE } from './request'

// 流式追问：直连 fetch，不走 axios，故单独暴露地址
export const RESUME_CHAT_STREAM_URL = `${API_BASE}/resume/chat/stream`

export function analyzeResume(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/resume/analyse', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
}

export function resumeChat({ resume_text, analysis_result, message, history }) {
  return request.post('/resume/chat', {
    resume_text,
    analysis_result,
    message,
    history,
  })
}

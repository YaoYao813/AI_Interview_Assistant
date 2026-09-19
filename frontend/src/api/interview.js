import request, { API_BASE } from './request'

// 流式评价：直连 fetch，不走 axios，故单独暴露地址
export const EVALUATE_STREAM_URL = `${API_BASE}/interview/evaluate/stream`

export function startInterview(data) {
  return request.post('/interview/start', data)
}

export function evaluateAnswer(sessionId, answer) {
  return request.post('/interview/evaluate', {
    session_id: sessionId,
    answer,
  })
}

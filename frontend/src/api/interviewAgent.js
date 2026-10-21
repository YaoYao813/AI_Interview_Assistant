import request, { API_BASE, TIMEOUT } from './request'

// 作答轮走 SSE：直连 fetch，不走 axios，故单独暴露地址
export const AGENT_ANSWER_STREAM_URL = `${API_BASE}/interview/agent/answer/stream`

export function startAgentInterview(data) {
  // 首轮要做「简历 vs 岗位」一次性分析，耗时可观，用最宽档
  return request.post('/interview/agent/start', data, { timeout: TIMEOUT.LLM_LONG })
}

export function getAgentReport(sessionId) {
  return request.post('/interview/agent/report', { session_id: sessionId }, { timeout: TIMEOUT.LLM })
}

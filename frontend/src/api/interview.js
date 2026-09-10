import request from './request'

export function startInterview(data) {
  return request.post('/interview/start', data)
}

export function evaluateAnswer(sessionId, answer) {
  return request.post('/interview/evaluate', {
    session_id: sessionId,
    answer,
  })
}

import request from './request'

export function startInterview(data) {
  return request.post('/interview/start', data)
}

export function evaluateAnswer(sessionId, question, answer) {
  return request.post('/interview/evaluate', null, {
    params: { session_id: sessionId, question, answer },
  })
}

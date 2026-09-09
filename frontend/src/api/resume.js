import request from './request'

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

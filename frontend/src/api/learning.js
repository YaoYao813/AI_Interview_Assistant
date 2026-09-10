import request from './request'

export function generateRoadmap(targetRole, resumeText = '') {
  return request.post('/roadmap/generate', {
      target_role: targetRole,
      resume_text: resumeText,
  })
}

import request from './request'

export function generateRoadmap(targetRole, resumeText = '') {
  return request.post('/roadmap/generate', null, {
    params: { target_role: targetRole, resume_text: resumeText },
  })
}

import request, { TIMEOUT } from './request'

export function generateRoadmap(targetRole, resumeText = '') {
  return request.post(
    '/roadmap/generate',
    {
      target_role: targetRole,
      resume_text: resumeText,
    },
    { timeout: TIMEOUT.LLM_LONG },
  )
}

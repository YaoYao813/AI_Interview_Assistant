import { createConversationStore } from './conversation'

export const useResumeStore = createConversationStore('resume', 'ai_resume_conversations', {
  filename: '',
  result: null,
  resumeText: '',
  messages: [],
  loading: false,
  chatLoading: false,
  question: '',
})

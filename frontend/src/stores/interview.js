import { createConversationStore } from './conversation'

export const useInterviewStore = createConversationStore('interview', 'ai_interview_conversations', {
  role: '',
  topicsText: '',
  difficulty: 'medium',
  sessionId: null,
  total: 0,
  currentIndex: 0,
  currentQuestion: '',
  rounds: [],
  evaluation: null,
  finished: false,
  starting: false,
  evaluating: false,
  answer: '',
})

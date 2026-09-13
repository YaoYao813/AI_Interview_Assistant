import { createConversationStore } from './conversation'

export const useLearningStore = createConversationStore('learning', 'ai_learning_conversations', {
  targetRole: '',
  resumeText: '',
  result: null,
  loading: false,
})

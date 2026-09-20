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
  // 非空表示会话已失效（Redis TTL 到期或面试已结束），值是后端给出的原因文案。
  // 与 finished 分开：finished 是正常走完，这个是中途被打断，不能混为一谈。
  interrupted: null,
})

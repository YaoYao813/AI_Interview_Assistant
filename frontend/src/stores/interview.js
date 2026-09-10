import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

const STORAGE_KEY = 'ai_interview_session'

function loadSnapshot() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

const snap = loadSnapshot()

export const useInterviewStore = defineStore('interview', () => {
  // ===== 会话进度（持久化）=====
  const sessionId = ref(snap?.sessionId || null)
  const total = ref(snap?.total || 0)
  const currentIndex = ref(snap?.currentIndex || 0)
  const currentQuestion = ref(snap?.currentQuestion || '')
  const evaluation = ref(snap?.evaluation || null)
  const rounds = ref(snap?.rounds || [])
  const finished = ref(snap?.finished || false)

  // ===== 瞬时状态（不持久化）=====
  const answer = ref('')
  const evaluating = ref(false)

  const averageScore = computed(() => {
    if (!rounds.value.length) return 0
    const sum = rounds.value.reduce((s, r) => s + Number(r.score || 0), 0)
    return sum / rounds.value.length
  })

  function persist() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      sessionId: sessionId.value,
      total: total.value,
      currentIndex: currentIndex.value,
      currentQuestion: currentQuestion.value,
      evaluation: evaluation.value,
      rounds: rounds.value,
      finished: finished.value,
    }))
  }

  function startSession(data) {
    sessionId.value = data.session_id
    total.value = data.total
    currentIndex.value = data.current_index
    currentQuestion.value = data.current_question
    evaluation.value = null
    rounds.value = []
    finished.value = false
    answer.value = ''
    persist()
  }

  function recordEvaluation(data, answerText) {
    rounds.value.push({
      question: currentQuestion.value,
      answer: answerText,
      score: data.score,
      feedback: data.feedback,
      model_answer: data.model_answer,
    })
    evaluation.value = data
    currentIndex.value = data.current_index
    if (data.is_finished) finished.value = true
    persist()
  }

  function goNext() {
    currentQuestion.value = evaluation.value?.next_question || ''
    answer.value = ''
    evaluation.value = null
    persist()
  }

  function reset() {
    sessionId.value = null
    total.value = 0
    currentIndex.value = 0
    currentQuestion.value = ''
    evaluation.value = null
    rounds.value = []
    finished.value = false
    answer.value = ''
    localStorage.removeItem(STORAGE_KEY)
  }

  return {
    sessionId, total, currentIndex, currentQuestion, evaluation, rounds,
    finished, answer, evaluating, averageScore,
    startSession, recordEvaluation, goNext, reset,
  }
})

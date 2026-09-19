import axios from 'axios'

// 所有接口的公共前缀；流式接口（fetch 直连，不走 axios）也复用它
export const API_BASE = '/api/v1'

// 按后端耗时特征分档，调用点引用档位名而非裸数字。
// 分档依据是「模型要吐多少 token」：DEFAULT 是纯 Chroma 读的耗时量级，
// LLM 是单轮回答，LLM_LONG 要求输出大块结构化 JSON（简历全文解析、出题、学习路线），
// UPLOAD 不经过 LLM、被 embedding 吞吐量支配，是本项目最慢的同步路径。
// 超时不是"等得起"的问题：调太松会把真故障拖成用户的漫长等待，调太紧会误杀
// 已经完成的请求，让用户重试时二次入库或二次计费。所以每一档都要有理由。
export const TIMEOUT = {
  DEFAULT: 30000,
  LLM: 120000,
  LLM_LONG: 180000,
  UPLOAD: 300000,
}

const request = axios.create({
  baseURL: API_BASE,
  timeout: TIMEOUT.DEFAULT,
})

request.interceptors.request.use(
  (config) => config,
  (error) => Promise.reject(error),
)

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const msg = error.response?.data?.message || error.message
    console.error(`[API Error] ${msg}`)
    return Promise.reject(error)
  },
)

export default request

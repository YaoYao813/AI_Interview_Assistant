import axios from 'axios'

// 所有接口的公共前缀；流式接口（fetch 直连，不走 axios）也复用它
export const API_BASE = '/api/v1'

const request = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
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

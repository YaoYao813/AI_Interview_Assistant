/**
 * 读取服务端 SSE 流并逐个事件回调。
 *
 * 后端事件格式：`data: {"type": "...", "data": ...}\n\n`
 * 一个网络分片可能包含多条事件、也可能把一条事件切成两半，
 * 因此这里按 `\n\n` 缓冲切分，剩余不完整部分留到下一轮。
 *
 * @param {string} url      请求地址（走 vite 代理的相对路径）
 * @param {object} payload  POST 的 JSON 体
 * @param {(evt: object) => void} onEvent  每个事件的回调
 * @param {{ signal?: AbortSignal, idleTimeoutMs?: number }} [options]
 */

/**
 * 连续多久收不到**任何**数据就判定为卡死。
 *
 * 必须是空闲超时而不是总超时：正常输出 5 分钟的长回答不该被拦腰杀掉，
 * 要抓的是「后端进程活着但再也不吐数据」——这时 `reader.read()` 会永久
 * pending，前端 loading 一直转，用户除了点「停止生成」没有别的出路。
 *
 * 取值要比 LLM 的首 token 延迟宽裕：流式响应会立刻回响应头，
 * 但第一个数据块可能等首 token 才来。
 */
export const IDLE_TIMEOUT_MS = 60000

export async function streamSSE(url, payload, onEvent, options = {}) {
  const idleMs = options.idleTimeoutMs ?? IDLE_TIMEOUT_MS

  // 空闲计时不能直接用 AbortSignal.timeout()——它不可重置，
  // 只能手写 setTimeout 并在每帧 clearTimeout。为了既能被空闲超时中断、
  // 又能被调用方的 signal（用户点停止 / 新问题顶替）中断，两者合并成一个。
  const idleController = new AbortController()
  const signal = options.signal
    ? AbortSignal.any([options.signal, idleController.signal])
    : idleController.signal

  let timer = null
  let idleTimedOut = false

  const arm = () => {
    clearTimeout(timer)
    timer = setTimeout(() => {
      idleTimedOut = true
      idleController.abort()
    }, idleMs)
  }

  try {
    // fetch 之前就上表：后端接了连接却迟迟不回响应头，同样属于卡死
    arm()

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })
    if (!response.ok) {
      // 后端业务异常返回 {success, code, message, detail}，把 message 和 status 带出来。
      // 只抛 "HTTP 404" 的话，调用方没法区分「会话过期」和「服务挂了」，
      // 也就没法给用户一条真正的恢复路径。
      const err = new Error(`HTTP ${response.status}`)
      err.status = response.status
      try {
        const body = await response.json()
        if (body?.message) err.message = body.message
      } catch { /* 响应体不是 JSON，保留 "HTTP xxx" */ }
      throw err
    }
    if (!response.body) {
      throw new Error('响应没有可读的流')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      // 每收到一帧就重置：只要后端还在吐数据，等多久都不算超时
      arm()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let sep
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const rawEvent = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        for (const line of rawEvent.split('\n')) {
          if (!line.startsWith('data: ')) continue
          let evt
          try {
            evt = JSON.parse(line.slice(6))
          } catch {
            continue
          }
          onEvent(evt)
        }
      }
    }
  } catch (e) {
    if (idleTimedOut) {
      // 换成自己的错误对象：空闲超时触发的 abort 同样是 AbortError，
      // 直接往上抛会被调用方当成「用户主动停止」，那样永远发现不了卡死。
      const err = new Error(`连接空闲超过 ${Math.round(idleMs / 1000)} 秒，已中断`)
      err.idleTimeout = true
      throw err
    }
    throw e
  } finally {
    clearTimeout(timer)
  }
}

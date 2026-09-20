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
 * @param {{ signal?: AbortSignal }} [options]
 */
export async function streamSSE(url, payload, onEvent, options = {}) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: options.signal,
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
}

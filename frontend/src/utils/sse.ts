// POST + SSE 流式读取（原生 EventSource 不支持 POST，必须 fetch + ReadableStream）
export interface SSEFrame {
  event?: string
  data: unknown
}

export async function streamSSE(
  url: string,
  body: object,
  token: string,
  onFrame: (frame: SSEFrame) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const data = await res.json()
      if (data.message) msg = data.message
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  if (!res.body) throw new Error('响应体为空')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // sse-starlette 用 CRLF 分帧（\r\n\r\n），先归一化为 \n 再按 \n\n 切分
    const frames = buffer.replace(/\r\n/g, '\n').split('\n\n')
    buffer = frames.pop() ?? ''
    for (const raw of frames) {
      const lines = raw.replace(/\r/g, '').split('\n')
      let event: string | undefined
      let data = ''
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      try {
        onFrame({ event, data: JSON.parse(data) })
      } catch {
        onFrame({ event, data })
      }
    }
  }
}

import type { ProgressEvent } from '../types/api'

async function responseFor(url: string, options: RequestInit) {
    let response: Response
    try {
        response = await fetch(url, options)
    } catch (error) {
        if (options.signal?.aborted) throw error
        throw new Error('无法连接服务，请确认服务已启动后重试。')
    }
    if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        const detail = Array.isArray(body.detail)
            ? body.detail
                  .map(
                      (item: { loc?: (string | number)[]; msg?: string }) =>
                          `${item.loc?.slice(1).join('.') || '输入'}：${item.msg || '格式不正确'}`,
                  )
                  .join('；')
            : body.detail
        throw new Error(
            typeof detail === 'string' ? detail : `请求失败（HTTP ${response.status}），请重试。`,
        )
    }
    return response
}

export async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers(options.headers)
    if (options.body) headers.set('Content-Type', 'application/json')
    const response = await responseFor(url, { ...options, headers })
    if (response.status === 204) return undefined as T
    return response.json()
}
export const post = <T>(url: string, body: unknown = {}, signal?: AbortSignal) =>
    request<T>(url, { method: 'POST', body: JSON.stringify(body), signal })

/** NDJSON is transport framing; a partial frame is never a completed result. */
export async function streamOperation<T>(
    url: string,
    body: unknown,
    onProgress: (event: ProgressEvent) => void,
    signal?: AbortSignal,
): Promise<T> {
    const response = await responseFor(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson' },
        body: JSON.stringify(body),
        signal,
    })
    if (!response.body) throw new Error('浏览器未能接收执行进度，请刷新后重试。')
    const reader = response.body.getReader(),
        decoder = new TextDecoder()
    let buffer = ''
    function consume(line: string): { result: T } | undefined {
        if (!line.trim()) return
        let event
        try {
            event = JSON.parse(line)
        } catch {
            throw new Error('执行进度数据不完整，请重试。')
        }
        if (event.type === 'progress') onProgress(event)
        else if (event.type === 'error') throw new Error(event.message || '操作未能完成，请重试。')
        else if (event.type === 'result') {
            if (!event.result || typeof event.result !== 'object')
                throw new Error('响应结果格式不正确，请重试。')
            return { result: event.result as T }
        }
    }
    try {
        while (true) {
            const { value, done } = await reader.read()
            buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() || ''
            for (const line of lines) {
                const completed = consume(line)
                if (completed) return completed.result
            }
            if (done) break
        }
        if (buffer.trim()) {
            const completed = consume(buffer)
            if (completed) return completed.result
        }
        throw new Error('连接已中断，尚未收到完整结果，请重试。')
    } finally {
        await reader.cancel().catch(() => {})
        reader.releaseLock()
    }
}

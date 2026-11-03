import { afterEach, describe, expect, it, vi } from 'vitest'
import { request, streamOperation } from '../src/api/client'

afterEach(() => vi.unstubAllGlobals())
function respond(chunks: Uint8Array[], status = 200) {
    vi.stubGlobal(
        'fetch',
        vi.fn(
            async () =>
                new Response(
                    new ReadableStream({
                        start(controller) {
                            chunks.forEach((chunk) => controller.enqueue(chunk))
                            controller.close()
                        },
                    }),
                    { status },
                ),
        ),
    )
}
const bytes = (text: string) => new TextEncoder().encode(text)
describe('NDJSON streaming transport', () => {
    it('decodes split UTF-8, multiple frames and a final frame without a newline', async () => {
        const progress = vi.fn(),
            data = bytes(
                '{"type":"progress","message":"正在搜索","elapsed_ms":2}\n{"type":"result","result":{"products":[]}}',
            )
        respond(Array.from(data, (value) => new Uint8Array([value])))
        expect(await streamOperation('/stream', {}, progress)).toEqual({ products: [] })
        expect(progress).toHaveBeenCalledWith({
            type: 'progress',
            message: '正在搜索',
            elapsed_ms: 2,
        })
    })
    it('never accepts partial or truncated tool/result JSON', async () => {
        respond([
            bytes(
                '{"type":"progress","message":"收到参数片段","elapsed_ms":1}\n{"type":"result","result":',
            ),
        ])
        await expect(streamOperation('/stream', {}, vi.fn())).rejects.toThrow('不完整')
    })
    it('reports EOF before a completed result', async () => {
        respond([bytes('{"type":"progress","message":"生成中","elapsed_ms":1}\n')])
        await expect(streamOperation('/stream', {}, vi.fn())).rejects.toThrow('尚未收到完整结果')
    })
    it('preserves backend errors rather than reporting success', async () => {
        respond([bytes('{"type":"error","message":"供应商 HTTP 503"}\n')])
        await expect(streamOperation('/stream', {}, vi.fn())).rejects.toThrow('供应商 HTTP 503')
    })
    it('passes cancellation to fetch and propagates abort', async () => {
        const controller = new AbortController()
        controller.abort()
        const fetch = vi.fn(async (_url, init) => {
            expect(init.signal).toBe(controller.signal)
            throw new DOMException('Aborted', 'AbortError')
        })
        vi.stubGlobal('fetch', fetch)
        await expect(
            streamOperation('/stream', {}, vi.fn(), controller.signal),
        ).rejects.toMatchObject({ name: 'AbortError' })
    })
    it('shows field names and validation details for HTTP 422', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () =>
                Response.json(
                    { detail: [{ loc: ['body', 'interval_seconds'], msg: '不能小于 30 秒' }] },
                    { status: 422 },
                ),
            ),
        )
        await expect(request('/watch')).rejects.toThrow('interval_seconds：不能小于 30 秒')
    })
    it('supports empty successful DELETE responses', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => new Response(null, { status: 204 })),
        )
        await expect(request('/watch', { method: 'DELETE' })).resolves.toBeUndefined()
    })
})

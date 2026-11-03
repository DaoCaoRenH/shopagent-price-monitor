import { effectScope } from 'vue'
import { expect, it, vi } from 'vitest'
import { getSearchHistory, getSearchRecord } from '../src/api/products'
import { useSearchHistory } from '../src/composables/useSearchHistory'
import type { SearchRecord } from '../src/types/api'
vi.mock('../src/api/products', () => ({ getSearchHistory: vi.fn(), getSearchRecord: vi.fn() }))
function deferred<T>() {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((r) => {
        resolve = r
    })
    return { promise, resolve }
}
const record = (id: string) =>
    ({ id, description: id, products: [], events: [] }) as unknown as SearchRecord
it('the latest selected search record wins even if the older request ignores cancellation', async () => {
    const first = deferred<SearchRecord>(),
        second = deferred<SearchRecord>()
    vi.mocked(getSearchRecord)
        .mockReturnValueOnce(first.promise)
        .mockReturnValueOnce(second.promise)
    const scope = effectScope(),
        history = scope.run(useSearchHistory)!
    const a = history.select('A'),
        b = history.select('B')
    second.resolve(record('B'))
    await b
    first.resolve(record('A'))
    await a
    expect(history.state.detail?.id).toBe('B')
    expect(history.state.selected).toBe('B')
    scope.stop()
})
it('a new empty filter clears an earlier detail response', async () => {
    const detail = deferred<SearchRecord>()
    vi.mocked(getSearchRecord).mockReturnValueOnce(detail.promise)
    vi.mocked(getSearchHistory).mockResolvedValue({ records: [], total: 0, next_cursor: null })
    const scope = effectScope(),
        history = scope.run(useSearchHistory)!
    const pending = history.select('A')
    history.state.query = 'unmatched'
    await history.load()
    detail.resolve(record('A'))
    await pending
    expect(history.state.detail).toBeNull()
    expect(history.state.records).toEqual([])
    scope.stop()
})

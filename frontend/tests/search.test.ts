import { beforeEach, expect, it, vi } from 'vitest'
import { searchProducts } from '../src/api/products'
import { useSearch } from '../src/composables/useSearch'
import type { SearchResult } from '../src/types/api'
vi.mock('../src/api/products', () => ({ searchProducts: vi.fn() }))
function deferred<T>() {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((r) => {
        resolve = r
    })
    return { promise, resolve }
}
beforeEach(() => vi.clearAllMocks())
it('keeps returned candidates bound to the submitted request even when the draft changes', async () => {
    const result: SearchResult = {
        engine: 'partial',
        message: '筛选未完成，已保留候选',
        products: [],
        selection_complete: false,
    }
    vi.mocked(searchProducts).mockResolvedValue(result)
    const search = useSearch()
    search.state.description = '原始需求'
    await search.search()
    search.state.description = '另一款商品'
    expect(search.state.submittedDescription).toBe('原始需求')
    expect(search.state.result?.engine).toBe('partial')
})
it('a canceled response cannot overwrite a later completed search', async () => {
    const slow = deferred<SearchResult>(),
        fast = { engine: 'catalog', message: 'second', products: [] } as SearchResult
    vi.mocked(searchProducts).mockReturnValueOnce(slow.promise).mockResolvedValueOnce(fast)
    const search = useSearch()
    search.state.description = 'first'
    const first = search.search()
    search.cancel()
    search.state.description = 'second'
    await search.search()
    slow.resolve({ ...fast, message: 'stale' })
    await first
    expect(search.state.result?.message).toBe('second')
    expect(search.state.running).toBe(false)
})

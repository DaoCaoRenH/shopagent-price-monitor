import { effectScope, nextTick, ref } from 'vue'
import { expect, it, vi } from 'vitest'
import { useWatchDetail } from '../src/composables/useWatchDetail'
import { getPriceHistory } from '../src/api/watches'
import type { PriceHistory } from '../src/types/api'
import { historyFixture } from './fixtures'
vi.mock('../src/api/watches', () => ({ getPriceHistory: vi.fn() }))
vi.mock('../src/composables/useDashboard', async () => {
    const { reactive, ref } = await import('vue')
    const dashboard = { state: reactive({ selected: '' }), revision: ref(0), refresh: vi.fn() }
    return { useDashboard: () => dashboard }
})
function deferred<T>() {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((r) => {
        resolve = r
    })
    return { promise, resolve }
}
it('switching watches cannot display the earlier slow price history', async () => {
    const a = deferred<PriceHistory>(),
        b = deferred<PriceHistory>()
    vi.mocked(getPriceHistory).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)
    const scope = effectScope(),
        id = ref('A'),
        detail = scope.run(() => useWatchDetail(id))!
    id.value = 'B'
    await nextTick()
    b.resolve(historyFixture('B'))
    await Promise.resolve()
    a.resolve(historyFixture('A'))
    await Promise.resolve()
    expect(detail.state.history?.watch.id).toBe('B')
    scope.stop()
})

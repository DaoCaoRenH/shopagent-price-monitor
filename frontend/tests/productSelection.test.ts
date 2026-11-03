import { effectScope, nextTick } from 'vue'
import { beforeEach, expect, it, vi } from 'vitest'
import { getProduct, quoteProduct } from '../src/api/products'
import { createWatch } from '../src/api/watches'
import { createProductSelection } from '../src/composables/useProductSelection'
import type { ProductDetail } from '../src/types/api'
vi.mock('../src/api/products', () => ({ getProduct: vi.fn(), quoteProduct: vi.fn() }))
vi.mock('../src/api/watches', () => ({ createWatch: vi.fn() }))
vi.mock('../src/composables/useDashboard', () => ({
    useDashboard: () => ({ state: {}, refresh: vi.fn() }),
}))
vi.mock('../src/composables/useNotifications', () => ({ notify: vi.fn() }))
function deferred<T>() {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((r) => {
        resolve = r
    })
    return { promise, resolve }
}
function product(asin: string, group: string, values: string[]): ProductDetail {
    return {
        asin,
        title: asin,
        shop: '',
        category: '',
        price: 10,
        description: '',
        attributes: [],
        option_group_count: 1,
        option_groups: { [group]: values.map((value) => ({ value, available: true })) },
    }
}
beforeEach(() => vi.clearAllMocks())
it('keeps B active if the earlier product A responds after B', async () => {
    const a = deferred<ProductDetail>(),
        b = deferred<ProductDetail>()
    vi.mocked(getProduct).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)
    const scope = effectScope(),
        selection = scope.run(createProductSelection)!
    const first = selection.open('A', 'request A'),
        second = selection.open('B', 'request B')
    b.resolve(product('B', '尺寸', ['L']))
    await second
    a.resolve(product('A', '颜色', ['黑色']))
    await first
    expect(selection.state.product?.asin).toBe('B')
    expect(selection.state.selections).toEqual({ 尺寸: 'L' })
    expect(selection.state.description).toBe('request B')
    scope.stop()
})
it('ignores an old quote after changing selections and blocks creation until the new quote completes', async () => {
    vi.mocked(getProduct).mockResolvedValue(product('A', '颜色', ['黑色', '白色']))
    const first = deferred<{ price: string }>(),
        second = deferred<{ price: string }>()
    vi.mocked(quoteProduct).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const scope = effectScope(),
        selection = scope.run(createProductSelection)!
    await selection.open('A', '保温杯')
    selection.configure()
    selection.state.selections = { 颜色: '黑色' }
    selection.state.selections = { 颜色: '白色' }
    first.resolve({ price: '9.00' })
    await nextTick()
    await Promise.resolve()
    expect(selection.canCreate.value).toBe(false)
    expect(selection.state.price).toBeNull()
    await selection.create()
    expect(createWatch).not.toHaveBeenCalled()
    second.resolve({ price: '12.00' })
    await nextTick()
    await Promise.resolve()
    expect(selection.canCreate.value).toBe(true)
    expect(selection.state.price).toBe('12.00')
    scope.stop()
})
it('invalidates the quote and selections when switching products', async () => {
    vi.mocked(getProduct)
        .mockResolvedValueOnce(product('A', '颜色', ['黑色']))
        .mockResolvedValueOnce(product('B', '尺寸', ['M', 'L']))
    vi.mocked(quoteProduct).mockResolvedValue({ price: '9.00' })
    const scope = effectScope(),
        selection = scope.run(createProductSelection)!
    await selection.open('A', 'A')
    selection.configure()
    await Promise.resolve()
    expect(selection.state.price).toBe('9.00')
    await selection.open('B', 'B')
    selection.configure()
    expect(selection.state.selections).toEqual({})
    expect(selection.canCreate.value).toBe(false)
    expect(selection.state.price).toBeNull()
    scope.stop()
})
it('closing the dialog invalidates an outstanding product response', async () => {
    const response = deferred<ProductDetail>()
    vi.mocked(getProduct).mockReturnValue(response.promise)
    const scope = effectScope(),
        selection = scope.run(createProductSelection)!
    const pending = selection.open('A', 'request')
    selection.close()
    response.resolve(product('A', '颜色', ['黑色']))
    await pending
    expect(selection.state.open).toBe(false)
    expect(selection.state.product).toBeNull()
    scope.stop()
})

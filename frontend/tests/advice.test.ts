import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import { generateAdvice, getAdvicePreview } from '../src/api/watches'
import { useAdvice } from '../src/composables/useAdvice'
import { useDashboard } from '../src/composables/useDashboard'
import { historyFixture } from './fixtures'
import type { Advice, DashboardStatus, Watch } from '../src/types/api'
vi.mock('../src/api/watches', () => ({ generateAdvice: vi.fn(), getAdvicePreview: vi.fn() }))

const scopes: ReturnType<typeof effectScope>[] = []
function response(watch: Watch, budget: string = '', urgency = 'flexible'): Advice {
    return {
        title: watch.id,
        engine: 'rules',
        decision: 'keep_watching',
        message: '规则建议',
        next_step: '继续采样',
        scope: '已采集记录',
        generated_at: new Date().toISOString(),
        valid_until: new Date(Date.now() + 3600000).toISOString(),
        model_revision: 'r1',
        based_on: { ...watch },
        preferences: { budget: budget || null, urgency },
        reasons: [],
        metrics: {
            current_price: '10.00',
            low_price: '10.00',
            gap_to_low_percent: 0,
            sample_count: 1,
            recent_count: 1,
            recent_direction: 'insufficient',
            new_low: false,
            quote_stale: false,
            simulation: false,
            first_observed_at: new Date().toISOString(),
            latest_observed_at: new Date().toISOString(),
        },
    }
}
function setup(id: string) {
    const watch = ref(historyFixture(id).watch),
        scope = effectScope()
    scopes.push(scope)
    vi.mocked(getAdvicePreview).mockImplementation(async (_id, budget, urgency) =>
        response(watch.value, budget, urgency),
    )
    vi.mocked(generateAdvice).mockImplementation(async (_id, budget, urgency) => ({
        ...response(watch.value, budget, urgency),
        engine: 'model',
    }))
    const advice = scope.run(() => useAdvice(watch))!
    return { watch, advice }
}
beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-03T00:00:00Z'))
    vi.clearAllMocks()
    const dashboard = useDashboard()
    dashboard.state.status = { model_revision: 'r1', model_enabled: true } as DashboardStatus
    dashboard.now.value = Date.now()
})
afterEach(() => {
    scopes.splice(0).forEach((scope) => scope.stop())
    vi.clearAllTimers()
    vi.useRealTimers()
})
it('opens with a rule preview in manual mode and never requests the model during refresh', async () => {
    const { watch, advice } = setup('manual-default')
    await vi.advanceTimersByTimeAsync(350)
    expect(advice.entry.value.mode).toBe('manual')
    expect(advice.displayed.value?.title).toBe('manual-default')
    watch.value = { ...watch.value }
    await vi.advanceTimersByTimeAsync(61000)
    expect(getAdvicePreview).toHaveBeenCalledTimes(1)
    expect(generateAdvice).not.toHaveBeenCalled()
})
it('auto mode deduplicates each evidence revision, enforces one minute and stops in manual mode', async () => {
    const { watch, advice } = setup('auto-rate')
    await vi.advanceTimersByTimeAsync(350)
    advice.entry.value.mode = 'auto'
    await vi.advanceTimersByTimeAsync(10)
    expect(generateAdvice).toHaveBeenCalledTimes(1)
    watch.value = { ...watch.value, history_revision: 2 }
    await vi.advanceTimersByTimeAsync(1000)
    expect(generateAdvice).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(60000)
    expect(generateAdvice).toHaveBeenCalledTimes(2)
    advice.entry.value.mode = 'manual'
    watch.value = { ...watch.value, history_revision: 3 }
    await vi.advanceTimersByTimeAsync(61000)
    expect(generateAdvice).toHaveBeenCalledTimes(2)
    expect(advice.preview.value?.based_on.history_revision).toBe(3)
})
it('does not loop after an automatic failure and still allows an explicit retry', async () => {
    const { advice } = setup('auto-failure')
    vi.mocked(generateAdvice).mockRejectedValue(new Error('connection failed'))
    await vi.advanceTimersByTimeAsync(350)
    advice.entry.value.mode = 'auto'
    await vi.advanceTimersByTimeAsync(10)
    expect(advice.entry.value.error).toBe('connection failed')
    await vi.advanceTimersByTimeAsync(120000)
    expect(generateAdvice).toHaveBeenCalledTimes(1)
    await advice.generate()
    expect(generateAdvice).toHaveBeenCalledTimes(2)
    expect(advice.entry.value.pending).toBe(false)
})
it('ignores a slow preview from a previous monitor even if abort is ignored', async () => {
    const { watch, advice } = setup('preview-a')
    let resolve!: (value: Advice) => void
    const firstWatch = { ...watch.value }
    vi.mocked(getAdvicePreview).mockReturnValueOnce(
        new Promise<Advice>((r) => {
            resolve = r
        }),
    )
    await vi.advanceTimersByTimeAsync(350)
    watch.value = historyFixture('preview-b').watch
    await vi.advanceTimersByTimeAsync(350)
    resolve(response(firstWatch))
    await nextTick()
    expect(advice.preview.value?.title).toBe('preview-b')
})
it('rejects zero or fractional-cent budgets without sending preview or model requests', async () => {
    const { advice } = setup('invalid-budget')
    advice.entry.value.preferences.budget = '0'
    await vi.advanceTimersByTimeAsync(350)
    await advice.generate()
    expect(advice.budgetValid.value).toBe(false)
    advice.entry.value.preferences.budget = '12.345'
    await vi.advanceTimersByTimeAsync(350)
    expect(getAdvicePreview).not.toHaveBeenCalled()
    expect(generateAdvice).not.toHaveBeenCalled()
    advice.entry.value.preferences.budget = '12.34'
    await vi.advanceTimersByTimeAsync(350)
    expect(advice.displayed.value?.preferences.budget).toBe('12.34')
})

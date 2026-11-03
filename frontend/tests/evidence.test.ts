import { describe, expect, it } from 'vitest'
import { adviceIsStale } from '../src/composables/useAdvice'
import { priceChart } from '../src/lib/priceChart'
import { acceptProgress } from '../src/composables/useSearch'
import type { Advice, Watch, Observation, ProgressEvent } from '../src/types/api'
const watch = { history_revision: 1, last_error: null, active: true, interval_seconds: 30 } as Watch
const advice = {
    title: '继续观察',
    message: '规则建议',
    engine: 'rules',
    next_step: '继续采样',
    scope: '已采集记录',
    generated_at: '2026-01-01T00:00:00Z',
    reasons: [],
    metrics: {
        first_observed_at: '2026-01-01T00:00:00Z',
        latest_observed_at: '2026-01-01T00:00:00Z',
        current_price: '10.00',
        low_price: '10.00',
        gap_to_low_percent: 0,
        sample_count: 1,
        recent_count: 1,
        recent_direction: 'insufficient',
        new_low: false,
        quote_stale: false,
        simulation: false,
    },
    model_revision: 'r1',
    based_on: { ...watch },
    preferences: { budget: null, urgency: 'flexible' },
    valid_until: '2026-01-01T01:00:00Z',
    decision: 'keep_watching',
} as Advice
const prefs = { budget: '', urgency: 'flexible' as const },
    before = Date.parse('2026-01-01T00:00:00Z')
describe('advice follows its evidence', () => {
    it('remains current only while history, model, preferences and time match', () => {
        expect(adviceIsStale(advice, watch, prefs, 'r1', before)).toBe(false)
        expect(adviceIsStale(advice, { ...watch, history_revision: 2 }, prefs, 'r1', before)).toBe(
            true,
        )
        expect(adviceIsStale(advice, watch, prefs, 'r2', before)).toBe(true)
        expect(adviceIsStale(advice, watch, { ...prefs, budget: '5' }, 'r1', before)).toBe(true)
        expect(adviceIsStale(advice, watch, prefs, 'r1', before + 7200000)).toBe(true)
    })
    it('does not expire the actionable refresh-quote warning just because time passes', () => {
        expect(
            adviceIsStale(
                { ...advice, decision: 'refresh_quote' },
                watch,
                prefs,
                'r1',
                before + 7200000,
            ),
        ).toBe(false)
        expect(adviceIsStale(advice, { ...watch, last_error: '断线' }, prefs, 'r1', before)).toBe(
            true,
        )
    })
})
it('plots time gaps proportionally and retains the all-history low outside the visible samples', () => {
    const observations = [0, 1, 10].map(
        (minute, id) =>
            ({
                id,
                amount_minor: 10000,
                observed_at: new Date(before + minute * 60000).toISOString(),
            }) as Observation,
    )
    const chart = priceChart(observations, 8000)!
    expect(chart.points[1]!.x - chart.points[0]!.x).toBeCloseTo(
        (chart.points[2]!.x - chart.points[0]!.x) / 10,
    )
    expect(chart.lowY).toBeGreaterThan(chart.points[0]!.y)
    expect(chart.lowY).toBeLessThan(chart.height - 28)
})
it('folds updates for one execution step and ends running steps on fallback', () => {
    const events: ProgressEvent[] = [],
        event = {
            type: 'progress',
            message: 'search',
            elapsed_ms: 0,
            step_id: '1',
            status: 'running',
        } as ProgressEvent
    acceptProgress(events, event)
    acceptProgress(events, { ...event, message: 'search done', status: 'completed' })
    expect(events).toHaveLength(1)
    acceptProgress(events, { ...event, step_id: '2' })
    acceptProgress(events, { ...event, step_id: '3', stage: 'fallback', status: 'notice' })
    expect(events[1]!.status).toBe('interrupted')
})

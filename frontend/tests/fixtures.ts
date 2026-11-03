import type { PriceHistory } from '../src/types/api'

export function historyFixture(id: string): PriceHistory {
    return {
        watch: {
            id,
            asin: id,
            title: id,
            selections: {},
            request: 'fixture',
            mode: 'snapshot',
            active: true,
            interval_seconds: 30,
            last_error: null,
            next_check_at: null,
            last_checked_at: null,
            current_observed_at: '2026-01-01T00:00:00Z',
            current_price: '10.00',
            current_minor: 1000,
            low_price: '10.00',
            low_minor: 1000,
            baseline_price: '10.00',
            change_percent: 0,
            sample_count: 1,
            history_revision: 1,
        },
        observations: [],
        total: 0,
        limit: 2000,
    }
}

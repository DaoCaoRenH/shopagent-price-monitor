import type { Observation } from '../types/api'

/** Geometry uses observed time and integer cents, including the complete-history low. */
export function priceChart(observations: Observation[], lowMinor: number, availableWidth = 680) {
    if (!observations.length) return null
    const width = Math.max(240, Math.round(availableWidth)),
        height = width < 400 ? 205 : 230,
        left = width < 400 ? 48 : 64,
        right = 12,
        top = 15,
        bottom = 28
    const amounts = observations.map((p) => p.amount_minor)
    const min = Math.min(...amounts, lowMinor),
        max = Math.max(...amounts)
    const extra = Math.max((max - min) * 0.22, max * 0.02, 1),
        lo = min - extra,
        hi = max + extra
    const times = observations.map((p) => new Date(p.observed_at).getTime()),
        start = Math.min(...times),
        end = Math.max(...times)
    const x = (time: number) =>
        start === end
            ? (left + width - right) / 2
            : left + ((time - start) / (end - start)) * (width - left - right)
    const y = (amount: number) => top + ((hi - amount) / (hi - lo)) * (height - top - bottom)
    const points = observations.map((observation, i) => ({
        x: x(times[i]!),
        y: y(observation.amount_minor),
        observation,
    }))
    return {
        width,
        height,
        left,
        right,
        lowY: y(lowMinor),
        start,
        end,
        points,
        line: points.map((p) => `${p.x},${p.y}`).join(' '),
        grid: [0, 0.5, 1].map((t) => {
            const value = hi - (hi - lo) * t
            return { y: y(value), label: (value / 100).toFixed(2) }
        }),
    }
}

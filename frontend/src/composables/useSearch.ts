import { computed, reactive } from 'vue'
import { searchProducts } from '../api/products'
import type { ProgressEvent, SearchResult } from '../types/api'
import { errorMessage } from '../lib/format'
import { LatestRequest } from '../lib/latestRequest'

const state = reactive({
    description: '',
    submittedDescription: '',
    result: null as SearchResult | null,
    visible: true,
    running: false,
    started: false,
    error: '',
    elapsed: 0,
    events: [] as ProgressEvent[],
    latest: null as ProgressEvent | null,
})
const request = new LatestRequest()
let timer: ReturnType<typeof setInterval> | undefined
let sequence = -1
export function acceptProgress(events: ProgressEvent[], event: ProgressEvent) {
    if (['fallback', 'retaining'].includes(event.stage || ''))
        events.forEach((step) => {
            if (step.status === 'running') step.status = 'interrupted'
        })
    const index = event.step_id ? events.findIndex((step) => step.step_id === event.step_id) : -1
    if (index < 0) events.push(event)
    else events[index] = event
}
function stopTimer() {
    if (timer) clearInterval(timer)
    timer = undefined
}
export function useSearch() {
    async function search() {
        if (state.running || !state.description.trim()) return
        const run = request.begin(),
            startedAt = performance.now()
        Object.assign(state, {
            running: true,
            started: true,
            error: '',
            result: null,
            events: [],
            latest: null,
            elapsed: 0,
            visible: true,
            submittedDescription: state.description.trim(),
        })
        sequence = -1
        stopTimer()
        timer = setInterval(() => {
            state.elapsed = performance.now() - startedAt
        }, 500)
        try {
            const result = await searchProducts(
                state.submittedDescription,
                (event) => {
                    if (
                        !request.current(run.revision) ||
                        (event.sequence != null && event.sequence <= sequence)
                    )
                        return
                    sequence = event.sequence ?? sequence + 1
                    acceptProgress(state.events, event)
                    state.latest = event
                },
                run.signal,
            )
            if (!request.current(run.revision)) return
            if (!Array.isArray(result.products)) throw new Error('搜索结果格式不正确，请重试。')
            state.result = result
        } catch (error) {
            if (request.current(run.revision)) state.error = errorMessage(error)
        } finally {
            if (request.current(run.revision)) {
                stopTimer()
                state.elapsed = performance.now() - startedAt
                state.running = false
                state.events.forEach((step) => {
                    if (step.status === 'running') step.status = 'interrupted'
                })
            }
        }
    }
    function cancel() {
        request.cancel()
        stopTimer()
        state.running = false
        state.error = '已停止接收本次搜索；已保存的结果可在搜索记录查看。'
        state.events.forEach((step) => {
            if (step.status === 'running') step.status = 'interrupted'
        })
    }
    return {
        state,
        search,
        cancel,
        round: computed(() => Math.max(0, ...state.events.map((e) => e.round || 0))),
        roundLimit: computed(() => Math.max(0, ...state.events.map((e) => e.round_limit || 0))),
        stats: computed(() => ({
            searches: state.events.filter(
                (e) => e.stage === 'searching' && e.status === 'completed',
            ).length,
            inspections: state.events.filter(
                (e) => e.stage === 'inspecting' && e.status === 'completed',
            ).length,
        })),
    }
}

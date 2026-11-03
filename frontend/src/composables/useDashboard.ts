import { computed, reactive, ref } from 'vue'
import * as api from '../api/watches'
import type { Alert, DashboardStatus, Presets, Watch } from '../types/api'
import { LatestRequest } from '../lib/latestRequest'
import { errorMessage } from '../lib/format'

const state = reactive({
    watches: [] as Watch[],
    alerts: [] as Alert[],
    status: null as DashboardStatus | null,
    presets: null as Presets | null,
    error: '',
    loading: true,
    selected: null as string | null,
})
const revision = ref(0),
    now = ref(Date.now()),
    request = new LatestRequest()
let presetsPromise: Promise<void> | undefined
export function useDashboard() {
    async function refresh() {
        const run = request.begin()
        try {
            const [status, watches, alerts] = await Promise.all([
                api.getStatus(run.signal),
                api.getWatches(run.signal),
                api.getAlerts(run.signal),
            ])
            if (!request.current(run.revision)) return
            state.status = status
            state.watches = watches.watches
            state.alerts = alerts.alerts
            state.error = ''
            if (!state.watches.some((watch) => watch.id === state.selected))
                state.selected = state.watches[0]?.id || null
            now.value = Date.now()
            revision.value += 1
        } catch (error) {
            if (request.current(run.revision)) state.error = errorMessage(error)
        } finally {
            if (request.current(run.revision)) state.loading = false
        }
    }
    async function loadPresets() {
        if (state.presets) return
        if (!presetsPromise)
            presetsPromise = api
                .getPresets()
                .then((value) => {
                    state.presets = value
                })
                .finally(() => {
                    presetsPromise = undefined
                })
        await presetsPromise
    }
    return {
        state,
        revision,
        now,
        refresh,
        loadPresets,
        selectedWatch: computed(() => state.watches.find((watch) => watch.id === state.selected)),
    }
}

import { computed, reactive, type Ref } from 'vue'
import { generateAdvice } from '../api/watches'
import { errorMessage } from '../lib/format'
import type { Advice, AdvicePreferences, Watch } from '../types/api'
import { useDashboard } from './useDashboard'

const entries = reactive(
    new Map<
        string,
        { preferences: AdvicePreferences; result: Advice | null; pending: boolean; error: string }
    >(),
)
export function adviceIsStale(
    advice: Advice,
    watch: Watch,
    prefs: AdvicePreferences,
    modelRevision: string | undefined,
    now: number,
) {
    const based = advice.based_on
    return (
        advice.model_revision !== modelRevision ||
        based.history_revision !== watch.history_revision ||
        based.last_error !== watch.last_error ||
        based.active !== watch.active ||
        based.interval_seconds !== watch.interval_seconds ||
        advice.preferences.urgency !== prefs.urgency ||
        (prefs.budget ? Number(prefs.budget) : null) !==
            (advice.preferences.budget == null ? null : Number(advice.preferences.budget)) ||
        (advice.decision !== 'refresh_quote' && now > new Date(advice.valid_until).getTime())
    )
}
export function useAdvice(watch: Ref<Watch>) {
    const dashboard = useDashboard()
    const entry = computed(() => {
        if (!entries.has(watch.value.id))
            entries.set(watch.value.id, {
                preferences: { budget: '', urgency: 'flexible' },
                result: null,
                pending: false,
                error: '',
            })
        return entries.get(watch.value.id)!
    })
    const stale = computed(
        () =>
            !!entry.value.result &&
            adviceIsStale(
                entry.value.result,
                watch.value,
                entry.value.preferences,
                dashboard.state.status?.model_revision,
                dashboard.now.value,
            ),
    )
    async function generate() {
        const current = entry.value
        if (current.pending) return
        current.pending = true
        current.error = ''
        const { budget, urgency } = current.preferences
        try {
            current.result = await generateAdvice(watch.value.id, budget, urgency)
        } catch (error) {
            current.error = errorMessage(error)
        } finally {
            current.pending = false
            dashboard.now.value = Date.now()
        }
    }
    return { entry, stale, generate }
}

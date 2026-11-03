import { computed, onScopeDispose, reactive, ref, watch as observe, type Ref } from 'vue'
import { generateAdvice, getAdvicePreview } from '../api/watches'
import { errorMessage } from '../lib/format'
import { LatestRequest } from '../lib/latestRequest'
import type { Advice, AdvicePreferences, Watch } from '../types/api'
import { useDashboard } from './useDashboard'

const entries = reactive(
    new Map<
        string,
        {
            preferences: AdvicePreferences
            result: Advice | null
            pending: boolean
            error: string
            startedAt: number
            mode: 'manual' | 'auto'
            autoAttemptKey: string
        }
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
                startedAt: 0,
                mode: savedMode(watch.value.id),
                autoAttemptKey: '',
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
    const preview = ref<Advice | null>(null),
        previewLoading = ref(false),
        previewError = ref(''),
        now = ref(Date.now()),
        request = new LatestRequest()
    let previewTimer: ReturnType<typeof setTimeout> | undefined
    let elapsedTimer: ReturnType<typeof setInterval> | undefined
    let autoTimer: ReturnType<typeof setTimeout> | undefined
    const budgetValid = computed(() => {
        const budget = String(entry.value.preferences.budget ?? '')
        return (
            !budget ||
            (/^\d+(\.\d{1,2})?$/.test(budget) &&
                Number(budget) > 0 &&
                Number(budget) <= 1_000_000_000)
        )
    })
    const previewStale = computed(
        () =>
            !preview.value ||
            adviceIsStale(
                preview.value,
                watch.value,
                entry.value.preferences,
                dashboard.state.status?.model_revision,
                dashboard.now.value,
            ),
    )
    const displayed = computed(() =>
        !budgetValid.value
            ? null
            : entry.value.result && !stale.value
              ? entry.value.result
              : !previewStale.value
                ? preview.value
                : null,
    )
    const modelEnabled = computed(() => dashboard.state.status?.model_enabled === true)
    const evidenceKey = computed(() =>
        JSON.stringify([
            watch.value.id,
            watch.value.history_revision,
            watch.value.last_error,
            watch.value.active,
            watch.value.interval_seconds,
            Number(entry.value.preferences.budget) || null,
            entry.value.preferences.urgency,
            dashboard.state.status?.model_revision,
        ]),
    )
    const autoEligible = () =>
        entry.value.mode === 'auto' &&
        modelEnabled.value &&
        budgetValid.value &&
        !entry.value.pending &&
        !previewLoading.value &&
        !previewStale.value &&
        preview.value?.metrics.quote_stale === false &&
        !watch.value.last_error &&
        (!entry.value.result || stale.value) &&
        entry.value.autoAttemptKey !== evidenceKey.value
    observe(
        () =>
            JSON.stringify([
                evidenceKey.value,
                entry.value.mode,
                modelEnabled.value,
                entry.value.pending,
                previewLoading.value,
                previewStale.value,
                preview.value?.metrics.quote_stale,
                stale.value,
                entry.value.autoAttemptKey,
            ]),
        () => {
            if (autoTimer) clearTimeout(autoTimer)
            autoTimer = undefined
            if (!autoEligible()) return
            const key = evidenceKey.value
            autoTimer = setTimeout(
                () => {
                    if (autoEligible() && evidenceKey.value === key) void generate()
                },
                Math.max(0, entry.value.startedAt + 60_000 - Date.now()),
            )
        },
        { immediate: true },
    )
    observe(
        () => entry.value.mode,
        (mode) => {
            try {
                localStorage.setItem(`shopagent-advice-mode:${watch.value.id}`, mode)
            } catch {
                /* Storage may be disabled. */
            }
        },
    )
    async function loadPreview() {
        if (!budgetValid.value) return
        const run = request.begin(),
            id = watch.value.id,
            { budget, urgency } = entry.value.preferences
        previewLoading.value = true
        previewError.value = ''
        try {
            const value = await getAdvicePreview(id, String(budget || ''), urgency, run.signal)
            if (request.current(run.revision)) preview.value = value
        } catch (error) {
            if (request.current(run.revision)) previewError.value = errorMessage(error)
        } finally {
            if (request.current(run.revision)) previewLoading.value = false
        }
    }
    observe(
        () =>
            JSON.stringify([
                watch.value.id,
                watch.value.history_revision,
                watch.value.last_error,
                watch.value.active,
                watch.value.interval_seconds,
                entry.value.preferences.budget,
                entry.value.preferences.urgency,
                dashboard.state.status?.model_revision,
            ]),
        () => {
            request.cancel()
            if (previewTimer) clearTimeout(previewTimer)
            previewLoading.value = false
            previewError.value = ''
            if (budgetValid.value) {
                previewLoading.value = true
                previewTimer = setTimeout(() => {
                    void loadPreview()
                }, 300)
            }
        },
        { immediate: true },
    )
    observe(dashboard.now, () => {
        if (preview.value && previewStale.value && !previewLoading.value && budgetValid.value)
            void loadPreview()
    })
    observe(
        () => entry.value.pending,
        (pending) => {
            if (elapsedTimer) clearInterval(elapsedTimer)
            elapsedTimer = undefined
            now.value = Date.now()
            if (pending)
                elapsedTimer = setInterval(() => {
                    now.value = Date.now()
                }, 500)
        },
        { immediate: true },
    )
    async function generate() {
        const current = entry.value
        if (current.pending || !budgetValid.value) return
        current.pending = true
        current.startedAt = Date.now()
        current.autoAttemptKey = evidenceKey.value
        now.value = current.startedAt
        current.error = ''
        const { budget, urgency } = current.preferences
        try {
            current.result = await generateAdvice(watch.value.id, String(budget || ''), urgency)
        } catch (error) {
            current.error = errorMessage(error)
        } finally {
            current.pending = false
            dashboard.now.value = Date.now()
        }
    }
    onScopeDispose(() => {
        request.cancel()
        if (previewTimer) clearTimeout(previewTimer)
        if (elapsedTimer) clearInterval(elapsedTimer)
        if (autoTimer) clearTimeout(autoTimer)
    })
    return {
        entry,
        stale,
        generate,
        preview,
        previewLoading,
        previewError,
        displayed,
        budgetValid,
        loadPreview,
        elapsedMs: computed(() => Math.max(0, now.value - entry.value.startedAt)),
        modelEnabled,
        autoHint: computed(() => {
            if (!modelEnabled.value) return '模型未启用，当前自动更新规则概览。'
            if (preview.value?.metrics.quote_stale || watch.value.last_error)
                return '报价过期或获取失败，更新有效报价后再自动分析。'
            if (entry.value.autoAttemptKey === evidenceKey.value && entry.value.error)
                return '本次自动分析未完成，可手动重试或等待新报价。'
            if (entry.value.result && !stale.value)
                return '已分析当前记录，新报价或购买偏好变化后再自动分析。'
            const remaining = Math.ceil(
                (entry.value.startedAt + 60_000 - dashboard.now.value) / 1000,
            )
            if (remaining > 0) return `有新记录待分析，将在约 ${remaining} 秒后触发。`
            return '仅当前详情页打开时自动分析；同一份记录只分析一次，最短间隔 1 分钟。'
        }),
    }
}

function savedMode(id: string): 'manual' | 'auto' {
    try {
        return localStorage.getItem(`shopagent-advice-mode:${id}`) === 'auto' ? 'auto' : 'manual'
    } catch {
        return 'manual'
    }
}

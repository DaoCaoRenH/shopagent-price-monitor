import { computed, onScopeDispose, reactive, ref } from 'vue'
import * as api from '../api/settings'
import { useDashboard } from './useDashboard'
import { errorMessage, elapsed } from '../lib/format'
import { LatestRequest } from '../lib/latestRequest'
import type { ModelInput, ModelSettings } from '../types/api'

const initial: ModelInput = {
    enabled: false,
    provider: 'openai-responses',
    model: 'deepseek-v4.1-flash',
    base_url: 'https://api.example.com/v1',
    api_key_required: true,
    api_key: '',
    clear_api_key: false,
    timeout_sec: 12,
    max_output_tokens: 768,
    temperature: 0,
    strict_tool_schema: false,
    reasoning_effort: 'none',
    max_context_tokens: 24576,
    stream: true,
    max_retries: 2,
    search_limits: { max_searches: 2, max_inspections: 3, max_model_rounds: 7 },
}
export function useModelSettings() {
    const draft = reactive<ModelInput>(structuredClone(initial)),
        current = ref<ModelSettings | null>(null)
    const state = reactive({
        loading: true,
        pending: '' as '' | 'save' | 'test',
        feedback: '',
        error: false,
        loadFailed: false,
    })
    const request = new LatestRequest()
    let baseline = ''
    const dirty = computed(() => JSON.stringify(draft) !== baseline)
    function apply(value: ModelSettings) {
        current.value = value
        // GET includes server metadata; it must never be sent back as form input.
        const input = Object.fromEntries(
            Object.keys(initial)
                .filter((key) => key in value)
                .map((key) => [key, Reflect.get(value, key)]),
        )
        Object.assign(draft, input, {
            search_limits: { ...value.search_limits },
            api_key: '',
            clear_api_key: false,
        })
        baseline = JSON.stringify(draft)
    }
    async function load() {
        state.loading = true
        state.loadFailed = false
        state.feedback = ''
        state.error = false
        const run = request.begin()
        try {
            const value = await api.getModelSettings()
            if (request.current(run.revision)) {
                apply(value)
                state.feedback = value.load_error || ''
                state.error = !!value.load_error
            }
        } catch (error) {
            if (request.current(run.revision)) {
                state.feedback = errorMessage(error)
                state.error = true
                state.loadFailed = true
            }
        } finally {
            if (request.current(run.revision)) state.loading = false
        }
    }
    async function submit(save: boolean) {
        if (state.pending || state.loading) return
        const run = request.begin()
        state.pending = save ? 'save' : 'test'
        state.error = false
        state.feedback = save ? '正在保存配置…' : '正在验证连接与工具调用…'
        const body: ModelInput = {
            ...draft,
            search_limits: { ...draft.search_limits },
            api_key: draft.api_key?.trim() || null,
            stream: draft.provider === 'openai-responses' && draft.stream,
        }
        try {
            if (save) {
                const value = await api.saveModelSettings(body)
                if (!request.current(run.revision)) return
                apply(value)
                state.feedback = '配置已保存，新请求立即生效。'
                await useDashboard().refresh()
            } else {
                const result = await api.testModelSettings(
                    body,
                    (event) => {
                        if (request.current(run.revision))
                            state.feedback = `${event.message}\n已用时 ${elapsed(event.elapsed_ms)}`
                    },
                    run.signal,
                )
                if (!request.current(run.revision)) return
                const detail = result.error
                state.feedback =
                    (result.message || (result.ok ? '连接成功' : '连接失败')) +
                    (result.ok
                        ? ` 耗时 ${result.latency_ms} ms，配置尚未保存。`
                        : detail
                          ? `\n错误类型：${detail.kind || '未知'} / ${detail.exception_type || ''}${detail.http_status ? ` · HTTP ${detail.http_status}` : ''}\n具体原因：${detail.detail || detail.summary}\n请求地址：${detail.endpoint || body.base_url}${detail.hint ? `\n${detail.hint}` : ''}`
                          : '')
                state.error = !result.ok
            }
        } catch (error) {
            if (request.current(run.revision)) {
                state.feedback = errorMessage(error)
                state.error = true
            }
        } finally {
            if (request.current(run.revision)) state.pending = ''
        }
    }
    onScopeDispose(() => {
        request.cancel()
        draft.api_key = ''
    })
    return { draft, current, state, dirty, load, submit }
}

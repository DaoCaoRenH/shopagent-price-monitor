import { onScopeDispose, reactive, watch, type Ref } from 'vue'
import * as api from '../api/watches'
import { LatestRequest } from '../lib/latestRequest'
import { errorMessage } from '../lib/format'
import type { PriceHistory } from '../types/api'
import { useDashboard } from './useDashboard'
import { notify } from './useNotifications'

export function useWatchDetail(id: Ref<string>) {
    const state = reactive({
        history: null as PriceHistory | null,
        loading: false,
        error: '',
        pending: '',
        actionError: '',
    })
    const request = new LatestRequest(),
        dashboard = useDashboard()
    async function load(reset = false) {
        const run = request.begin()
        state.loading = true
        state.error = ''
        if (reset) {
            state.history = null
            state.actionError = ''
        }
        try {
            const data = await api.getPriceHistory(id.value, run.signal)
            if (request.current(run.revision)) state.history = data
        } catch (error) {
            if (request.current(run.revision)) state.error = errorMessage(error)
        } finally {
            if (request.current(run.revision)) state.loading = false
        }
    }
    async function action(
        kind: 'refresh' | 'toggle' | 'delete' | 'restart' | 'simulate',
        price = '',
    ) {
        if (state.pending || !state.history) return
        const watch = state.history.watch,
            originalId = watch.id
        state.pending = kind
        state.actionError = ''
        try {
            let nextId: string | undefined
            if (kind === 'refresh') {
                const result = await api.refreshWatch(originalId)
                if (result.status === 'error') throw new Error(result.error || '检查未完成')
                notify(
                    result.status === 'skipped'
                        ? '已有检查正在进行'
                        : result.inserted
                          ? '新报价已记录'
                          : '已检查，尚无新的价格快照',
                )
            } else if (kind === 'toggle') {
                await api.updateWatch(originalId, !watch.active)
                notify(watch.active ? '监控已暂停' : '监控已恢复')
            } else if (kind === 'delete') {
                await api.deleteWatch(originalId)
                notify('监控及对应记录已删除')
            } else if (kind === 'restart') {
                nextId = (await api.restartReplay(originalId)).watch.id
                notify('新回放已开始，上一轮记录已保留并暂停')
            } else {
                const result = await api.simulatePrice(originalId, price)
                notify(result.alerts_created ? '模拟价格创下新低，已生成提醒' : '模拟报价已记录')
            }
            await dashboard.refresh()
            return { originalId, nextId, deleted: kind === 'delete' }
        } catch (error) {
            if (id.value === originalId) state.actionError = errorMessage(error)
            else notify(errorMessage(error))
        } finally {
            state.pending = ''
        }
    }
    watch(
        id,
        () => {
            dashboard.state.selected = id.value
            void load(true)
        },
        { immediate: true },
    )
    watch(dashboard.revision, () => {
        if (state.pending !== 'delete') void load()
    })
    onScopeDispose(() => request.cancel())
    return { state, load, action }
}

import { onScopeDispose, reactive } from 'vue'
import { getSearchHistory, getSearchRecord } from '../api/products'
import { LatestRequest } from '../lib/latestRequest'
import { errorMessage } from '../lib/format'
import type { SearchSummary, SearchRecord } from '../types/api'

export function useSearchHistory() {
    const state = reactive({
        query: '',
        records: [] as SearchSummary[],
        cursor: null as string | null,
        total: 0,
        selected: '',
        detail: null as SearchRecord | null,
        loading: false,
        detailLoading: false,
        error: '',
        detailError: '',
    })
    const listRequest = new LatestRequest(),
        detailRequest = new LatestRequest()
    async function select(id: string) {
        const run = detailRequest.begin()
        state.selected = id
        state.detail = null
        state.detailLoading = true
        state.detailError = ''
        try {
            const record = await getSearchRecord(id, run.signal)
            if (detailRequest.current(run.revision)) state.detail = record
        } catch (error) {
            if (detailRequest.current(run.revision)) state.detailError = errorMessage(error)
        } finally {
            if (detailRequest.current(run.revision)) state.detailLoading = false
        }
    }
    async function load(append = false, preferred?: string) {
        const run = listRequest.begin()
        state.loading = true
        state.error = ''
        if (!append) {
            detailRequest.cancel()
            state.detail = null
            state.detailLoading = false
            state.selected = preferred || ''
            state.detailError = ''
        }
        try {
            const result = await getSearchHistory(
                state.query.trim(),
                append ? state.cursor : null,
                run.signal,
            )
            if (!listRequest.current(run.revision)) return
            state.records = append ? [...state.records, ...result.records] : result.records
            state.cursor = result.next_cursor
            state.total = result.total
            if (!append) {
                const id = preferred || result.records[0]?.id
                if (id) void select(id)
            }
        } catch (error) {
            if (listRequest.current(run.revision)) state.error = errorMessage(error)
        } finally {
            if (listRequest.current(run.revision)) state.loading = false
        }
    }
    onScopeDispose(() => {
        listRequest.cancel()
        detailRequest.cancel()
    })
    return { state, load, select }
}

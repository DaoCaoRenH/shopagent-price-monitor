import { computed, reactive, watch } from 'vue'
import { getProduct, quoteProduct } from '../api/products'
import { createWatch } from '../api/watches'
import type { ProductDetail, PriceMode, SimulationConfig } from '../types/api'
import { LatestRequest } from '../lib/latestRequest'
import { errorMessage } from '../lib/format'
import { useDashboard } from './useDashboard'
import { notify } from './useNotifications'

export function createProductSelection() {
    const state = reactive({
        open: false,
        phase: 'detail' as 'detail' | 'configure',
        asin: '',
        description: '',
        product: null as ProductDetail | null,
        selections: {} as Record<string, string>,
        price: null as string | null,
        loading: false,
        quoting: false,
        creating: false,
        error: '',
        quoteError: '',
        mode: 'snapshot' as PriceMode,
        interval: 3600,
        simulation: {
            engine: 'event',
            scenario: null,
            seed: 42,
            tick_seconds: 30,
        } as SimulationConfig,
    })
    const productRequest = new LatestRequest(),
        quoteRequest = new LatestRequest()
    const complete = computed(
        () =>
            !!state.product &&
            Object.entries(state.product.option_groups).every(([group, values]) =>
                values.some((v) => v.available && v.value === state.selections[group]),
            ),
    )
    const canCreate = computed(
        () =>
            state.open &&
            state.phase === 'configure' &&
            complete.value &&
            state.price != null &&
            !state.quoting &&
            !state.creating &&
            !state.loading,
    )
    async function open(asin: string, description: string) {
        if (state.creating) return
        const run = productRequest.begin()
        quoteRequest.cancel()
        Object.assign(state, {
            open: true,
            phase: 'detail',
            asin,
            description,
            product: null,
            selections: {},
            price: null,
            loading: true,
            quoting: false,
            error: '',
            quoteError: '',
            mode: 'snapshot',
            interval: 3600,
            simulation: { engine: 'event', scenario: null, seed: 42, tick_seconds: 30 },
        })
        try {
            const product = await getProduct(asin, run.signal)
            if (!productRequest.current(run.revision)) return
            state.product = product
            state.selections = Object.fromEntries(
                Object.entries(product.option_groups).flatMap(([group, values]) => {
                    const available = values.filter((v) => v.available)
                    return available.length === 1 ? [[group, available[0]!.value]] : []
                }),
            )
        } catch (error) {
            if (productRequest.current(run.revision)) state.error = errorMessage(error)
        } finally {
            if (productRequest.current(run.revision)) state.loading = false
        }
    }
    async function quote() {
        const run = quoteRequest.begin()
        state.price = null
        state.quoteError = ''
        state.quoting = false
        if (!complete.value || state.phase !== 'configure' || !state.product) return
        state.quoting = true
        try {
            const result = await quoteProduct(
                state.product.asin,
                { ...state.selections },
                run.signal,
            )
            if (quoteRequest.current(run.revision)) state.price = result.price
        } catch (error) {
            if (quoteRequest.current(run.revision)) state.quoteError = errorMessage(error)
        } finally {
            if (quoteRequest.current(run.revision)) state.quoting = false
        }
    }
    function close() {
        if (state.creating) return
        productRequest.cancel()
        quoteRequest.cancel()
        state.open = false
        state.product = null
        state.price = null
        state.quoting = false
        state.loading = false
    }
    function configure() {
        state.phase = 'configure'
        state.error = ''
        void quote()
    }
    function back() {
        quoteRequest.cancel()
        state.phase = 'detail'
        state.quoting = false
        state.price = null
        state.error = ''
    }
    async function create() {
        if (!canCreate.value || !state.product) return
        state.creating = true
        state.error = ''
        try {
            const sim = {
                ...state.simulation,
                scenario: state.simulation.engine === 'replay' ? state.simulation.scenario : null,
            }
            if (
                state.mode === 'simulation' &&
                sim.engine === 'replay' &&
                state.interval > sim.tick_seconds
            )
                throw new Error('检查间隔不能大于场景回放的价格推进间隔。')
            const result = await createWatch({
                asin: state.product.asin,
                selections: { ...state.selections },
                request: state.description,
                mode: state.mode,
                interval_seconds: state.interval,
                ...(state.mode === 'simulation' ? { simulation: sim } : {}),
            })
            useDashboard().state.selected = result.watch.id
            state.creating = false
            close()
            notify(
                result.created
                    ? '已加入监控，首次价格已记录'
                    : '该商品规格已在监控中，保留原有历史',
            )
            await useDashboard().refresh()
        } catch (error) {
            state.error = errorMessage(error)
        } finally {
            state.creating = false
        }
    }
    watch(
        () => ({ ...state.selections }),
        () => {
            void quote()
        },
        { flush: 'sync' },
    )
    watch(
        () => state.mode,
        (mode) => {
            if (mode === 'simulation') state.interval = 30
        },
    )
    return { state, open, close, configure, back, quote, create, complete, canCreate }
}
const selection = createProductSelection()
export const useProductSelection = () => selection

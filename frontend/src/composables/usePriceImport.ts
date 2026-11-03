import { reactive } from 'vue'
import { importPrices } from '../api/watches'
import { useDashboard } from './useDashboard'
import { errorMessage } from '../lib/format'

export function usePriceImport() {
    const state = reactive({ json: '', pending: false, feedback: '', error: false }),
        dashboard = useDashboard()
    async function file(file: File) {
        if (file.size > 900000) {
            state.feedback = '文件过大，请分批导入，每批最多 1000 条报价。'
            state.error = true
            return
        }
        try {
            state.json = await file.text()
            state.feedback = `已读取 ${file.name}，检查后点击导入快照。`
            state.error = false
        } catch (error) {
            state.feedback = errorMessage(error)
            state.error = true
        }
    }
    function example() {
        const watch = dashboard.selectedWatch.value
        if (!watch) {
            state.feedback = '请先添加并选中一个监控商品。'
            state.error = true
            return
        }
        state.json = JSON.stringify(
            {
                observations: [
                    {
                        watch_id: watch.id,
                        price: watch.current_price,
                        observed_at: new Date().toISOString(),
                        currency: 'CNY',
                        mode: watch.mode,
                    },
                ],
            },
            null,
            2,
        )
        state.feedback = '已填入所选商品的当前价格示例，请修改为实际观测到的价格与时间。'
        state.error = false
    }
    async function submit() {
        if (state.pending) return
        state.pending = true
        state.error = false
        state.feedback = ''
        try {
            let body: unknown
            try {
                body = JSON.parse(state.json)
            } catch {
                throw new Error('JSON 格式不正确，请检查引号、逗号和括号。')
            }
            const result = await importPrices(body)
            state.feedback = `已新增 ${result.inserted} 条价格记录，生成 ${result.alerts_created} 条低价提醒，跳过 ${result.duplicates} 条重复记录。`
            await dashboard.refresh()
        } catch (error) {
            state.feedback = errorMessage(error)
            state.error = true
        } finally {
            state.pending = false
        }
    }
    return { state, file, example, submit }
}

import type { Money, Watch } from '../types/api'
export const amount = (value: Money) =>
    Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export function date(value: string | null | undefined, full = false) {
    return value
        ? new Date(value).toLocaleString('zh-CN', {
              month: '2-digit',
              day: '2-digit',
              hour: '2-digit',
              minute: '2-digit',
              ...(full ? { second: '2-digit' } : {}),
              hour12: false,
          })
        : '尚未检查'
}
export const elapsed = (ms: number) =>
    ms < 60000
        ? `${Math.floor(ms / 1000)} 秒`
        : `${Math.floor(ms / 60000)} 分 ${Math.floor(ms / 1000) % 60} 秒`
export const interval = (seconds: number) =>
    seconds < 60
        ? `${seconds} 秒`
        : seconds < 3600
          ? `${seconds / 60} 分钟`
          : `${seconds / 3600} 小时`
export const variant = (watch: Watch) =>
    Object.entries(watch.selections)
        .map(([k, v]) => `${k}：${v}`)
        .join(' · ') || '无可选规格'
export const engineLabel = (engine: string) =>
    (
        ({ model: 'Agent 筛选', catalog: '目录检索', partial: '已有候选 · 筛选未完成' }) as Record<
            string,
            string
        >
    )[engine] || '准备中'
export const sourceLabel = (source: string | undefined) =>
    (
        ({
            catalog: '目录基准',
            import: '导入快照',
            simulation: '手动/旧版模拟',
            event_simulation: '事件模拟',
            scenario_replay: '场景回放',
        }) as Record<string, string>
    )[source || ''] || '价格记录'
export const errorMessage = (error: unknown) =>
    error instanceof Error ? error.message : '操作未能完成，请稍后重试。'
export const reasoningLabels: Record<string, string> = {
    none: '默认',
    minimal: '极低（minimal）',
    low: '低（low）',
    medium: '中（medium）',
    high: '高（high）',
    xhigh: '极高（xhigh）',
    max: '最大（max）',
    ultra: '扩展（ultra）',
}

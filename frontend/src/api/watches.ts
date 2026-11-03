import { post, request } from './client'
import type {
    Advice,
    Alert,
    DashboardStatus,
    Presets,
    PriceHistory,
    Watch,
    WatchInput,
} from '../types/api'
const watchUrl = (id: string) => `/api/watches/${encodeURIComponent(id)}`
export const getStatus = (signal?: AbortSignal) =>
    request<DashboardStatus>('/api/status', { signal })
export const getWatches = (signal?: AbortSignal) =>
    request<{ watches: Watch[] }>('/api/watches', { signal })
export const getAlerts = (signal?: AbortSignal) =>
    request<{ alerts: Alert[] }>('/api/alerts', { signal })
export const getPresets = () => request<Presets>('/api/simulation-presets')
export const createWatch = (body: WatchInput) =>
    post<{ watch: Watch; created: boolean }>('/api/watches', body)
export const getPriceHistory = (id: string, signal?: AbortSignal) =>
    request<PriceHistory>(`${watchUrl(id)}/history`, { signal })
export const updateWatch = (id: string, active: boolean) =>
    request<Watch>(watchUrl(id), { method: 'PATCH', body: JSON.stringify({ active }) })
export const deleteWatch = (id: string) => request(watchUrl(id), { method: 'DELETE' })
export const refreshWatch = (id: string) =>
    post<{ status: string; error?: string; inserted?: boolean }>(`${watchUrl(id)}/refresh`)
export const restartReplay = (id: string) =>
    post<{ watch: Watch }>(`${watchUrl(id)}/replay/restart`)
export const simulatePrice = (id: string, price: string) =>
    post<{ alerts_created: number }>(`${watchUrl(id)}/simulate`, { price })
export const generateAdvice = (id: string, budget: string, urgency: string) =>
    post<Advice>(`${watchUrl(id)}/advice`, { budget: budget || null, urgency })
export const getAdvicePreview = (
    id: string,
    budget: string,
    urgency: string,
    signal?: AbortSignal,
) => {
    const query = new URLSearchParams({ urgency })
    if (budget) query.set('budget', budget)
    return request<Advice>(`${watchUrl(id)}/advice?${query}`, { signal })
}
export const readAlert = (id: number) => post(`/api/alerts/${id}/read`)
export const importPrices = (body: unknown) =>
    post<{ inserted: number; alerts_created: number; duplicates: number }>(
        '/api/prices/import',
        body,
    )

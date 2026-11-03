import { post, request, streamOperation } from './client'
import type {
    ProductDetail,
    ProgressEvent,
    SearchPage,
    SearchRecord,
    SearchResult,
} from '../types/api'
export const searchProducts = (
    description: string,
    progress: (event: ProgressEvent) => void,
    signal?: AbortSignal,
) => streamOperation<SearchResult>('/api/search/stream', { description }, progress, signal)
export const getProduct = (asin: string, signal?: AbortSignal) =>
    request<ProductDetail>(`/api/products/${encodeURIComponent(asin)}`, { signal })
export const quoteProduct = (
    asin: string,
    selections: Record<string, string>,
    signal?: AbortSignal,
) =>
    post<{ price: string }>(
        `/api/products/${encodeURIComponent(asin)}/quote`,
        { selections },
        signal,
    )
export const getSearchHistory = (query: string, cursor: string | null, signal?: AbortSignal) =>
    request<SearchPage>(
        `/api/search-history?${new URLSearchParams({ q: query, limit: '20', ...(cursor ? { before: cursor } : {}) })}`,
        { signal },
    )
export const getSearchRecord = (id: string, signal?: AbortSignal) =>
    request<SearchRecord>(`/api/search-history/${encodeURIComponent(id)}`, { signal })

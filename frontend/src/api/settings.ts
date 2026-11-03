import { request, streamOperation } from './client'
import type { ModelInput, ModelSettings, ModelTest, ProgressEvent } from '../types/api'
export const getModelSettings = () => request<ModelSettings>('/api/model-settings')
export const saveModelSettings = (body: ModelInput) =>
    request<ModelSettings>('/api/model-settings', { method: 'PUT', body: JSON.stringify(body) })
export const testModelSettings = (
    body: ModelInput,
    progress: (event: ProgressEvent) => void,
    signal?: AbortSignal,
) => streamOperation<ModelTest>('/api/model-settings/test/stream', body, progress, signal)

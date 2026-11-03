import { effectScope } from 'vue'
import { expect, it, vi } from 'vitest'
import { useModelSettings } from '../src/composables/useModelSettings'
import { getModelSettings, saveModelSettings } from '../src/api/settings'
import type { ModelSettings } from '../src/types/api'
vi.mock('../src/api/settings', () => ({
    getModelSettings: vi.fn(),
    saveModelSettings: vi.fn(),
    testModelSettings: vi.fn(),
}))
vi.mock('../src/composables/useDashboard', () => ({ useDashboard: () => ({ refresh: vi.fn() }) }))
it('sends only editable fields, preserves an existing key by sending null, and clears typed secrets after save', async () => {
    const value = {
        enabled: false,
        provider: 'openai-responses',
        model: 'demo',
        base_url: 'http://localhost/v1',
        api_key_required: true,
        has_api_key: true,
        revision: 'r1',
        persistent: true,
        load_error: null,
        timeout_sec: 12,
        max_output_tokens: 768,
        temperature: 0,
        strict_tool_schema: false,
        stream: true,
        max_retries: 2,
        reasoning_effort: 'none',
        max_context_tokens: 24576,
        search_limits: { max_searches: 2, max_inspections: 3, max_model_rounds: 7 },
    } as ModelSettings
    vi.mocked(getModelSettings).mockResolvedValue(value)
    vi.mocked(saveModelSettings).mockResolvedValue(value)
    const scope = effectScope(),
        settings = scope.run(useModelSettings)!
    await settings.load()
    expect(settings.dirty.value).toBe(false)
    await settings.submit(true)
    const body = vi.mocked(saveModelSettings).mock.calls[0]![0]
    expect(body.api_key).toBeNull()
    expect(body).not.toHaveProperty('has_api_key')
    expect(body).not.toHaveProperty('revision')
    settings.draft.api_key = 'typed-fixture'
    await settings.submit(true)
    expect(settings.draft.api_key).toBe('')
    expect(settings.dirty.value).toBe(false)
    scope.stop()
})

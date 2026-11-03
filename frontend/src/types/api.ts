export type Money = string | number
export type PriceMode = 'snapshot' | 'simulation'
export type Engine = 'model' | 'catalog' | 'partial'
export interface Product {
    asin: string
    title: string
    shop: string
    category: string
    price: number | null
    option_group_count: number
    reason?: string
}
export interface ProductDetail extends Product {
    attributes: string[]
    description: string
    option_groups: Record<string, { value: string; available: boolean; price?: number | null }[]>
}
export interface ProgressEvent {
    type: 'progress'
    message: string
    elapsed_ms: number
    sequence?: number
    step_id?: string
    stage?: string
    status?: string
    round?: number
    round_limit?: number
    engine?: Engine
}
export interface SearchResult {
    engine: Engine
    message: string
    products: Product[]
    search_id?: string
    history_warning?: string
    selection_complete?: boolean
}
export interface SearchSummary {
    id: string
    description: string
    completed_at: string
    elapsed_ms: number
    engine: Engine
    result_count: number
}
export interface SearchRecord extends SearchSummary {
    message: string
    products: Product[]
    events: ProgressEvent[]
}
export interface SearchPage {
    records: SearchSummary[]
    total: number
    next_cursor: string | null
}
export interface SimulationConfig {
    engine: 'event' | 'replay'
    scenario: string | null
    seed: number
    tick_seconds: number
}
export interface SimulationState extends SimulationConfig {
    tick: number
    event: string
    normal_price: Money
    complete: boolean
    scenario_name: string | null
    total_steps: number | null
}
export interface Scenario {
    id: string
    name: string
    steps: { percent: number | null; event: string }[]
}
export interface Presets {
    scenarios: Scenario[]
    default: SimulationConfig
}
export interface Watch {
    id: string
    asin: string
    title: string
    selections: Record<string, string>
    request: string
    mode: PriceMode
    active: boolean
    interval_seconds: number
    last_error: string | null
    next_check_at: string | null
    last_checked_at: string | null
    current_observed_at: string
    current_price: Money
    low_price: Money
    low_minor: number
    current_minor: number
    baseline_price: Money
    change_percent: number
    sample_count: number
    history_revision: number
    source?: string
    simulation?: SimulationState | null
}
export interface WatchInput {
    asin: string
    selections: Record<string, string>
    request: string
    mode: PriceMode
    interval_seconds: number
    simulation?: SimulationConfig
}
export interface Observation {
    id: number
    price: Money
    amount_minor: number
    observed_at: string
    source: string
    event?: string | null
    simulation_tick?: number | null
}
export interface PriceHistory {
    watch: Watch
    observations: Observation[]
    total: number
    limit: number
}
export interface Alert {
    id: number
    watch_id: string
    title: string
    price: Money
    previous_low: Money
    drop_percent: number
    observed_at: string
    selections: Record<string, string>
    mode: PriceMode
    is_read: boolean
}
export interface DashboardStatus {
    watch_count: number
    active_count: number
    observation_count: number
    unread_count: number
    catalog_count: number
    catalog_is_demo: boolean
    model_enabled: boolean
    model_revision: string
    scheduler_enabled: boolean
    scheduler_last_poll: string | null
    scheduler_error: string | null
}
export interface AdvicePreferences {
    budget: string
    urgency: 'flexible' | 'soon'
}
export interface Advice {
    title: string
    message: string
    engine: 'model' | 'rules'
    decision: string
    next_step: string
    scope: string
    generated_at: string
    valid_until: string
    model_revision: string
    based_on: Pick<Watch, 'history_revision' | 'last_error' | 'active' | 'interval_seconds'>
    preferences: { budget: Money | null; urgency: string }
    reasons: { id: string; text: string }[]
    metrics: { first_observed_at: string; latest_observed_at: string }
}
export interface SearchLimits {
    max_searches: number
    max_inspections: number
    max_model_rounds: number
}
export interface ModelInput {
    enabled: boolean
    provider: 'openai-responses' | 'openai-chat' | 'gemini'
    model: string
    base_url: string
    api_key_required: boolean
    api_key?: string | null
    clear_api_key: boolean
    timeout_sec: number
    max_output_tokens: number
    temperature: number
    strict_tool_schema: boolean
    reasoning_effort: string
    max_context_tokens: number
    stream: boolean
    max_retries: number
    search_limits: SearchLimits
}
export interface ModelSettings extends Omit<ModelInput, 'api_key' | 'clear_api_key'> {
    has_api_key: boolean
    revision: string
    persistent: boolean
    load_error: string | null
}
export interface ModelTest {
    ok: boolean
    message?: string
    latency_ms?: number
    provider?: string
    model?: string
    error?: {
        summary: string
        detail?: string
        hint?: string
        kind?: string
        http_status?: number
        exception_type?: string
        endpoint?: string
    }
}

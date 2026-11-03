<script setup lang="ts">
import { computed, toRef } from 'vue'
import type { Watch } from '../../types/api'
import { useAdvice } from '../../composables/useAdvice'
import { amount, date, elapsed } from '../../lib/format'
import Icon from '../common/Icon.vue'
import Notice from '../common/Notice.vue'
const props = defineProps<{ watch: Watch; busy?: boolean }>()
const emit = defineEmits<{ refresh: [] }>()
const {
    entry,
    stale,
    generate,
    previewLoading,
    previewError,
    displayed,
    budgetValid,
    loadPreview,
    elapsedMs,
    modelEnabled,
    autoHint,
} = useAdvice(toRef(props, 'watch'))
const preferenceSummary = computed(() =>
    [
        entry.value.preferences.budget
            ? `预算 ¥${amount(entry.value.preferences.budget)}`
            : '未设预算',
        entry.value.preferences.urgency === 'soon' ? '近期购买' : '不急用',
    ].join(' · '),
)
const keyReasons = computed(() =>
    ['error', 'stale', 'limited', 'budget', 'trend', 'paused']
        .flatMap((id) => displayed.value?.reasons.filter((reason) => reason.id === id) || [])
        .slice(0, 3),
)
</script>
<template>
    <section class="purchase-advice" aria-label="购买建议">
        <div class="advice-heading">
            <h3><Icon name="spark" />购买建议</h3>
            <span v-if="watch.mode === 'simulation'" class="tag simulation">模拟数据</span>
        </div>
        <div
            class="advice-overview"
            :data-decision="displayed?.decision"
            :aria-busy="previewLoading"
        >
            <template v-if="displayed">
                <div class="advice-overview-heading">
                    <strong>{{ displayed.title }}</strong>
                    <span class="tag" :class="{ agent: displayed.engine === 'model' }">{{
                        displayed.engine === 'model' ? 'Agent 分析' : '即时概览'
                    }}</span>
                </div>
                <p class="advice-action">{{ displayed.next_step }}</p>
                <dl class="advice-facts">
                    <div>
                        <dt>距采集最低价</dt>
                        <dd>
                            {{
                                displayed.metrics.sample_count < 2
                                    ? '待积累'
                                    : displayed.metrics.gap_to_low_percent === 0
                                      ? '持平'
                                      : `+${displayed.metrics.gap_to_low_percent.toFixed(2)}%`
                            }}
                        </dd>
                    </div>
                    <div>
                        <dt>已采集报价</dt>
                        <dd>{{ displayed.metrics.sample_count }} <small>条</small></dd>
                    </div>
                </dl>
                <ul v-if="keyReasons.length" class="advice-key-reasons">
                    <li v-for="reason in keyReasons" :key="reason.id">{{ reason.text }}</li>
                </ul>
                <button
                    v-if="displayed.decision === 'refresh_quote' && watch.active"
                    class="button secondary advice-refresh"
                    type="button"
                    :disabled="busy || entry.pending"
                    @click="emit('refresh')"
                >
                    <Icon name="refresh" />检查最新报价
                </button>
                <details class="advice-evidence">
                    <summary>
                        查看全部依据 <span>{{ displayed.reasons.length }} 条</span>
                    </summary>
                    <ul class="advice-reasons">
                        <li v-for="reason in displayed.reasons" :key="reason.id">
                            {{ reason.text }}
                        </li>
                    </ul>
                    <p class="advice-message">{{ displayed.message }}</p>
                    <p class="advice-scope">
                        采样范围 {{ date(displayed.metrics.first_observed_at, true) }} →
                        {{ date(displayed.metrics.latest_observed_at, true) }}<br />分析时间
                        {{ date(displayed.generated_at, true) }}
                    </p>
                </details>
            </template>
            <p v-else-if="previewLoading" class="advice-placeholder" role="status">
                正在整理已采集的价格记录…
            </p>
            <p v-else-if="!budgetValid" class="advice-placeholder">
                请先修正购买偏好中的预算金额。
            </p>
            <div v-else class="advice-placeholder">
                <p>暂时无法生成价格概览。</p>
                <button class="text-button" type="button" @click="loadPreview">重新读取</button>
            </div>
        </div>
        <p v-if="stale && entry.result" class="advice-stale-note">
            上次分析已过期，{{ displayed ? '当前展示最新规则概览。' : '正在更新价格概览。' }}
        </p>
        <p
            v-if="entry.result && !stale && entry.result.engine === 'rules' && modelEnabled"
            class="advice-stale-note"
        >
            {{ entry.result.message }}
        </p>
        <Notice :message="previewError" error />
        <fieldset class="advice-mode">
            <legend>Agent 分析方式</legend>
            <label :class="{ selected: entry.mode === 'manual' }"
                ><input
                    v-model="entry.mode"
                    type="radio"
                    :name="`advice-mode-${watch.id}`"
                    value="manual"
                />手动</label
            >
            <label :class="{ selected: entry.mode === 'auto' }"
                ><input
                    v-model="entry.mode"
                    type="radio"
                    :name="`advice-mode-${watch.id}`"
                    value="auto"
                />自动</label
            >
        </fieldset>
        <form class="advice-personalize" @submit.prevent="generate">
            <fieldset :disabled="entry.pending">
                <details class="advice-preferences">
                    <summary>
                        <span>购买偏好 <small>可选</small></span
                        ><span class="advice-preference-summary">{{ preferenceSummary }}</span>
                    </summary>
                    <div class="advice-fields">
                        <label class="field-label" for="advice-budget"
                            >预算上限（元，可选）<input
                                id="advice-budget"
                                v-model="entry.preferences.budget"
                                type="number"
                                min="0.01"
                                max="1000000000"
                                step="0.01"
                                placeholder="留空表示不限预算"
                        /></label>
                        <label class="field-label" for="advice-urgency"
                            >购买时间<select
                                id="advice-urgency"
                                v-model="entry.preferences.urgency"
                            >
                                <option value="flexible">不急用，可以等</option>
                                <option value="soon">近期需要购买</option>
                            </select></label
                        >
                    </div>
                    <Notice
                        :message="
                            budgetValid ? '' : '预算须大于 0，最多两位小数，且不超过 10 亿元。'
                        "
                        error
                    />
                </details>
                <button
                    type="submit"
                    class="button primary advice-generate"
                    :disabled="!budgetValid"
                >
                    <Icon v-if="!entry.pending" :name="modelEnabled ? 'spark' : 'refresh'" />
                    {{
                        entry.pending
                            ? '正在分析…'
                            : entry.mode === 'auto' && modelEnabled
                              ? '立即分析一次'
                              : modelEnabled
                                ? '让 Agent 进一步分析'
                                : '按购买偏好分析'
                    }}
                </button>
            </fieldset>
        </form>
        <p v-if="entry.pending" class="advice-running" role="status">
            正在结合价格记录与购买偏好分析 · 已用时 {{ elapsed(elapsedMs) }}
        </p>
        <p v-else class="advice-analysis-hint">
            {{
                entry.mode === 'auto'
                    ? autoHint
                    : modelEnabled
                      ? '点击后调用已配置模型，结合购买偏好分析。'
                      : '当前使用监控规则，可在模型配置中启用 Agent。'
            }}
        </p>
        <Notice :message="entry.error" error />
        <p class="advice-scope">
            {{
                watch.mode === 'simulation' ? '基于模拟记录，仅用于演示。' : ''
            }}仅依据本规格已采集记录，不代表全网最低，不预测未来价格。
        </p>
    </section>
</template>

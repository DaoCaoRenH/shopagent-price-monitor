<script setup lang="ts">
import { toRef } from 'vue'
import type { Watch } from '../../types/api'
import { useAdvice } from '../../composables/useAdvice'
import { date } from '../../lib/format'
import Icon from '../common/Icon.vue'
import Notice from '../common/Notice.vue'
const props = defineProps<{ watch: Watch }>()
const { entry, stale, generate } = useAdvice(toRef(props, 'watch'))
</script>
<template>
    <section class="purchase-advice" aria-label="购买建议">
        <div class="advice-heading">
            <h3><Icon name="spark" />购买建议</h3>
            <span v-if="watch.mode === 'simulation'" class="tag simulation">模拟数据</span>
        </div>
        <form @submit.prevent="generate">
            <fieldset :disabled="entry.pending">
                <div class="advice-fields">
                    <label class="field-label" for="advice-budget"
                        >预算上限（可选）<input
                            id="advice-budget"
                            v-model="entry.preferences.budget"
                            type="number"
                            min="0.01"
                            max="1000000000"
                            step="0.01"
                            placeholder="例如 100" /></label
                    ><label class="field-label" for="advice-urgency"
                        >购买时间<select id="advice-urgency" v-model="entry.preferences.urgency">
                            <option value="flexible">不急用，可以等</option>
                            <option value="soon">近期需要购买</option>
                        </select></label
                    >
                </div>
                <button type="submit" class="button secondary">
                    {{ entry.pending ? '正在分析…' : entry.result ? '重新分析' : '生成购买建议' }}
                </button>
            </fieldset>
        </form>
        <div class="advice-result" aria-live="polite" :aria-busy="entry.pending">
            <p v-if="!entry.result" class="advice-empty">
                结合价格记录和你的购买计划，分析当前是否适合入手。
            </p>
            <div v-else-if="stale" class="advice-outdated">
                <strong>建议待更新</strong>
                <p>价格、监控状态、购买偏好或模型配置已变化，请重新生成建议。</p>
                <small>上次分析 {{ date(entry.result.generated_at, true) }}</small>
            </div>
            <template v-else
                ><div class="advice-conclusion">
                    <strong>{{ entry.result.title }}</strong
                    ><span class="tag" :class="{ agent: entry.result.engine === 'model' }">{{
                        entry.result.engine === 'model' ? 'Agent 分析' : '监控规则'
                    }}</span>
                </div>
                <p class="advice-message">{{ entry.result.message }}</p>
                <ul class="advice-reasons">
                    <li v-for="reason in entry.result.reasons" :key="reason.id">
                        {{ reason.text }}
                    </li>
                </ul>
                <div class="advice-next">
                    <strong>下一步</strong>
                    <p>{{ entry.result.next_step }}</p>
                </div>
                <p class="advice-scope">
                    {{ entry.result.scope }}<br />采样范围
                    {{ date(entry.result.metrics.first_observed_at, true) }} →
                    {{ date(entry.result.metrics.latest_observed_at, true) }}<br />分析时间
                    {{ date(entry.result.generated_at, true) }}
                </p></template
            >
        </div>
        <Notice :message="entry.error" error />
    </section>
</template>

<script setup lang="ts">
import { nextTick, watch } from 'vue'
import { useProductSelection } from '../../composables/useProductSelection'
import { useDashboard } from '../../composables/useDashboard'
import { amount, errorMessage } from '../../lib/format'
import AppDialog from '../common/AppDialog.vue'
import Icon from '../common/Icon.vue'
import Notice from '../common/Notice.vue'
import VariantSelector from './VariantSelector.vue'
import SimulationSettings from './SimulationSettings.vue'
const { state, close, open, configure, back, create, canCreate } = useProductSelection()
const dashboard = useDashboard()
watch(
    () => state.open,
    async (value) => {
        if (value) {
            try {
                await dashboard.loadPresets()
            } catch (error) {
                state.error = errorMessage(error)
            }
        }
    },
)
watch(
    () => state.phase,
    async (phase) => {
        await nextTick()
        document
            .querySelector<HTMLElement>(
                phase === 'configure' ? '#watch-settings select' : '#start-watch',
            )
            ?.focus({ preventScroll: true })
        const dialog = document.querySelector('#product-dialog')
        if (dialog) dialog.scrollTop = 0
    },
)
</script>
<template>
    <AppDialog
        id="product-dialog"
        class="product-dialog"
        :open="state.open"
        labelledby="dialog-title"
        :busy="state.creating"
        @close="close"
        ><form id="watch-form" @submit.prevent="create">
            <div class="dialog-heading">
                <div>
                    <h2 id="dialog-title">
                        {{ state.phase === 'detail' ? '商品详情' : '设置价格监控' }}
                    </h2>
                </div>
                <button
                    class="icon-button"
                    type="button"
                    aria-label="关闭"
                    :disabled="state.creating"
                    @click="close"
                >
                    <Icon name="close" />
                </button>
            </div>
            <div :aria-busy="state.loading">
                <p v-if="state.loading" class="product-loading" role="status">
                    正在读取商品介绍、参数与可选规格…
                </p>
                <template v-if="state.product"
                    ><div class="dialog-product">
                        <h3>{{ state.product.title }}</h3>
                        <div class="product-overview">
                            <dl class="product-metadata">
                                <div>
                                    <dt>店铺</dt>
                                    <dd>{{ state.product.shop || '目录未提供' }}</dd>
                                </div>
                                <div>
                                    <dt>分类</dt>
                                    <dd>{{ state.product.category || '目录未提供' }}</dd>
                                </div>
                                <div>
                                    <dt>商品 ID</dt>
                                    <dd>{{ state.product.asin }}</dd>
                                </div>
                            </dl>
                            <div class="product-reference-price">
                                <span>目录参考价</span
                                ><strong>{{
                                    state.product.price == null
                                        ? '待确认'
                                        : '¥' + amount(state.product.price)
                                }}</strong
                                ><small>具体规格价格以确认结果为准</small>
                            </div>
                        </div>
                    </div>
                    <div v-if="state.phase === 'detail'">
                        <section class="product-information">
                            <h3>商品参数</h3>
                            <ul v-if="state.product.attributes.length" class="product-attributes">
                                <li v-for="item in state.product.attributes" :key="item">
                                    {{ item }}
                                </li>
                            </ul>
                            <p v-else class="product-empty">目录暂未提供商品参数。</p>
                        </section>
                        <section class="product-information">
                            <h3>商品介绍</h3>
                            <p class="product-description">
                                {{
                                    state.product.description ||
                                    '目录暂未提供商品介绍，请结合标题、参数和规格核对商品。'
                                }}
                            </p>
                        </section>
                        <section class="product-information">
                            <h3>
                                可选规格
                                <span
                                    >{{ Object.keys(state.product.option_groups).length }} 组</span
                                >
                            </h3>
                            <div
                                v-for="(values, group) in state.product.option_groups"
                                :key="group"
                                class="product-spec-group"
                            >
                                <h4>
                                    {{ group }} <span>{{ values.length }} 项</span>
                                </h4>
                                <div class="spec-chips">
                                    <span
                                        v-for="value in values.slice(0, 4)"
                                        :key="value.value"
                                        class="spec-chip"
                                        :class="{ unavailable: !value.available }"
                                        >{{ value.value
                                        }}{{ value.available ? '' : ' · 不可选' }}</span
                                    >
                                </div>
                                <details v-if="values.length > 4" class="more-specs">
                                    <summary>查看全部 {{ values.length }} 项</summary>
                                    <div class="spec-chips">
                                        <span
                                            v-for="value in values.slice(4)"
                                            :key="value.value"
                                            class="spec-chip"
                                            :class="{ unavailable: !value.available }"
                                            >{{ value.value
                                            }}{{ value.available ? '' : ' · 不可选' }}</span
                                        >
                                    </div>
                                </details>
                            </div>
                            <p
                                v-if="!Object.keys(state.product.option_groups).length"
                                class="product-empty"
                            >
                                该商品没有可选规格，将按商品本身记录价格。
                            </p>
                        </section>
                    </div></template
                >
            </div>
            <fieldset
                v-if="state.product && state.phase === 'configure'"
                id="watch-settings"
                :disabled="state.creating"
            >
                <h3 class="watch-settings-title">确认规格与价格来源</h3>
                <p class="field-help">
                    {{
                        Object.keys(state.product.option_groups).length
                            ? '选择完整规格后确认基准价，每个规格组合单独记录价格历史。'
                            : '该商品没有可选规格，将按商品本身记录价格历史。'
                    }}
                </p>
                <VariantSelector :product="state.product" v-model:selections="state.selections" />
                <div class="form-columns">
                    <label class="field-label" for="watch-mode"
                        >价格来源<select id="watch-mode" v-model="state.mode">
                            <option value="snapshot">快照监控</option>
                            <option value="simulation">模拟监控</option>
                        </select></label
                    ><label class="field-label" for="watch-interval"
                        >检查间隔<select id="watch-interval" v-model="state.interval">
                            <option :value="3600">每 1 小时</option>
                            <option :value="900">每 15 分钟</option>
                            <option :value="60">每 1 分钟</option>
                            <option :value="30">每 30 秒</option>
                            <option :value="21600">每 6 小时</option>
                        </select></label
                    >
                </div>
                <p class="field-help">
                    {{
                        state.mode === 'simulation'
                            ? '模拟价格与真实快照分开保存。价格按时钟推进，同一步内反复检查不会改价。'
                            : '定期检查最新已导入快照；静态目录本身不会产生价格变化。'
                    }}
                </p>
                <SimulationSettings
                    v-if="state.mode === 'simulation'"
                    v-model="state.simulation"
                    :interval="state.interval"
                    :presets="dashboard.state.presets"
                />
                <div
                    id="quote-preview"
                    class="quote-preview"
                    :class="{ invalid: state.quoteError }"
                    aria-live="polite"
                >
                    <template v-if="state.price != null"
                        ><span>所选规格目录基准价</span
                        ><strong>¥{{ amount(state.price) }}</strong></template
                    ><template v-else>{{
                        state.quoteError ||
                        (state.quoting ? '正在确认目录基准价…' : '请选择完整规格')
                    }}</template>
                </div>
                <button
                    v-if="state.quoteError"
                    class="text-button"
                    type="button"
                    @click="useProductSelection().quote()"
                >
                    重新确认报价
                </button>
            </fieldset>
            <Notice :message="state.error" error />
            <div class="dialog-actions">
                <button
                    class="button secondary"
                    type="button"
                    :disabled="state.creating"
                    @click="state.phase === 'detail' ? close() : back()"
                >
                    {{ state.phase === 'detail' ? '关闭' : '返回商品详情' }}</button
                ><button
                    v-if="state.error && !state.product"
                    class="button secondary"
                    type="button"
                    @click="open(state.asin, state.description)"
                >
                    重新加载</button
                ><button
                    v-if="state.phase === 'detail'"
                    id="start-watch"
                    class="button primary"
                    type="button"
                    :disabled="!state.product"
                    @click="configure"
                >
                    设置价格监控 <Icon name="arrowRight" /></button
                ><button
                    v-else
                    id="add-watch"
                    class="button primary"
                    type="submit"
                    :disabled="!canCreate"
                >
                    {{ state.creating ? '正在加入…' : '加入监控' }}
                </button>
            </div>
        </form></AppDialog
    >
</template>

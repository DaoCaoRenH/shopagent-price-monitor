<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWatchDetail } from '../composables/useWatchDetail'
import { useDashboard } from '../composables/useDashboard'
import { amount, date, interval, sourceLabel, variant } from '../lib/format'
import PriceChart from '../components/watches/PriceChart.vue'
import SimulationPanel from '../components/watches/SimulationPanel.vue'
import PurchaseAdvice from '../components/watches/PurchaseAdvice.vue'
import AppDialog from '../components/common/AppDialog.vue'
import EmptyState from '../components/common/EmptyState.vue'
import Notice from '../components/common/Notice.vue'
import Icon from '../components/common/Icon.vue'
const route = useRoute(),
    router = useRouter(),
    id = computed(() => String(route.params.id))
const { state, load, action } = useWatchDetail(id),
    dashboard = useDashboard()
const current = computed(() => state.history?.watch),
    price = ref(''),
    confirm = ref(false)
watch(id, () => {
    price.value = ''
    confirm.value = false
})
async function act(kind: 'refresh' | 'toggle' | 'delete' | 'restart' | 'simulate') {
    const originalId = id.value,
        result = await action(kind, price.value)
    if (!result || id.value !== originalId) return
    if (kind === 'simulate') price.value = ''
    if (result.deleted) {
        confirm.value = false
        await router.push({ name: 'watches' })
    } else if (result.nextId)
        await router.replace({ name: 'watch-detail', params: { id: result.nextId } })
}
</script>
<template>
    <section id="view-watch-detail" class="view">
        <div class="watch-detail-toolbar">
            <RouterLink class="button secondary" to="/watches"
                ><Icon name="arrowLeft" />返回我的监控</RouterLink
            ><span class="quiet-label">每个商品规格单独记录价格</span>
        </div>
        <section
            class="panel detail-panel"
            aria-label="所选商品价格详情"
            :aria-busy="state.loading"
        >
            <p v-if="state.loading && !state.history" class="history-placeholder" role="status">
                正在读取价格走势…
            </p>
            <EmptyState
                v-else-if="state.error && !state.history"
                title="暂时无法显示价格走势"
                :description="state.error"
                icon="chart"
                ><button class="button secondary" @click="load()">重新读取</button></EmptyState
            >
            <div v-if="current && state.history" class="detail-body">
                <Notice :message="state.error" error />
                <div class="watch-product-heading">
                    <h2>{{ current.title }}</h2>
                    <span class="tag" :class="{ simulation: current.mode === 'simulation' }">{{
                        current.mode === 'simulation' ? '模拟监控' : '价格快照'
                    }}</span>
                    <div class="detail-variant">{{ variant(current) }}</div>
                </div>
                <div class="watch-detail-columns">
                    <section class="watch-trend" aria-label="所选规格的价格曲线与采样">
                        <div class="detail-prices">
                            <div>
                                <span class="price-label">最近采样价格</span
                                ><strong class="large-price"
                                    ><span>¥</span>{{ amount(current.current_price) }}</strong
                                >
                                <div
                                    class="price-change"
                                    :class="{
                                        down: current.change_percent < 0,
                                        up: current.change_percent > 0,
                                    }"
                                >
                                    {{
                                        current.change_percent === 0
                                            ? '与首次采样持平'
                                            : `${current.change_percent < 0 ? '↓' : '↑'} ${Math.abs(current.change_percent)}% · 相比首次采样`
                                    }}
                                </div>
                            </div>
                            <div class="low-price">
                                <span class="price-label">已采集最低价</span
                                ><strong>¥{{ amount(current.low_price) }}</strong>
                            </div>
                        </div>
                        <div class="chart-heading">
                            <h3>
                                价格轨迹 {{ current.mode === 'simulation' ? '· 模拟数据' : '' }}
                            </h3>
                            <span class="chart-legend">采集最低</span>
                        </div>
                        <div class="watch-chart-wrap">
                            <PriceChart
                                :observations="state.history.observations"
                                :low-minor="current.low_minor"
                            />
                        </div>
                        <div class="chart-caption">
                            <span>{{
                                state.history.observations.length === 1
                                    ? '首个采样点已记录，后续更新将形成曲线'
                                    : `共 ${state.history.total} 次采样${state.history.total > state.history.limit ? `，显示最近 ${state.history.limit} 次` : ''}`
                            }}</span
                            ><span>CNY</span>
                        </div>
                        <h4 class="sample-heading">最近采样记录</h4>
                        <div class="sample-list">
                            <div
                                v-for="observation in state.history.observations
                                    .slice(-12)
                                    .reverse()"
                                :key="observation.id"
                                class="sample-row"
                            >
                                <span
                                    >{{ date(observation.observed_at, true) }}
                                    <span
                                        class="tag"
                                        :class="{ simulation: current.mode === 'simulation' }"
                                        >{{ sourceLabel(observation.source) }}</span
                                    ><small v-if="observation.event" class="sample-event"
                                        >第 {{ (observation.simulation_tick || 0) + 1 }} 步 ·
                                        {{ observation.event }}</small
                                    ></span
                                ><strong>¥{{ amount(observation.price) }}</strong>
                            </div>
                        </div>
                        <p class="watch-history-scope">
                            “历史最低”仅指此商品规格开始采集以来的记录。
                        </p>
                    </section>
                    <aside class="watch-support" aria-label="购买建议与监控设置">
                        <SimulationPanel
                            v-if="current.simulation"
                            :key="current.id + '-simulation'"
                            :simulation="current.simulation"
                            :presets="dashboard.state.presets"
                            :pending="!!state.pending"
                            @restart="act('restart')"
                        /><PurchaseAdvice :key="current.id" :watch="current" />
                        <section class="watch-manage">
                            <h3>监控管理</h3>
                            <div class="detail-actions">
                                <button
                                    class="button secondary"
                                    :disabled="!current.active || !!state.pending"
                                    @click="act('refresh')"
                                >
                                    <Icon name="refresh" />{{
                                        state.pending === 'refresh' ? '检查中…' : '立即检查'
                                    }}</button
                                ><button
                                    v-if="!current.simulation?.complete"
                                    class="button secondary"
                                    :disabled="!!state.pending"
                                    @click="act('toggle')"
                                >
                                    {{
                                        state.pending === 'toggle'
                                            ? '保存中…'
                                            : current.active
                                              ? '暂停监控'
                                              : '恢复监控'
                                    }}</button
                                ><button
                                    class="text-button"
                                    :disabled="!!state.pending"
                                    @click="confirm = true"
                                >
                                    删除监控
                                </button>
                            </div>
                            <div class="detail-schedule">
                                每 {{ interval(current.interval_seconds) }}检查 ·
                                {{
                                    current.active
                                        ? `下次 ${date(current.next_check_at)}`
                                        : '已暂停自动检查'
                                }}<br />最近检查 {{ date(current.last_checked_at) }} · 报价来源：{{
                                    sourceLabel(current.source)
                                }}
                            </div>
                            <Notice
                                :message="
                                    current.last_error
                                        ? `${current.last_error}，将在后续检查中重试。`
                                        : ''
                                "
                                error
                            />
                            <form
                                v-if="
                                    current.mode === 'simulation' &&
                                    current.simulation?.engine !== 'replay'
                                "
                                class="simulate-box"
                                @submit.prevent="act('simulate')"
                            >
                                <label class="field-label" for="simulation-price"
                                    >手动注入模拟报价（不改变自动事件序列）</label
                                >
                                <div class="simulate-controls">
                                    <input
                                        id="simulation-price"
                                        v-model="price"
                                        type="number"
                                        min="0.01"
                                        max="1000000000"
                                        step="0.01"
                                        required
                                        placeholder="例如 89.90"
                                        :disabled="!!state.pending"
                                    /><button
                                        class="button secondary"
                                        type="submit"
                                        :disabled="!!state.pending"
                                    >
                                        写入模拟报价
                                    </button>
                                </div>
                            </form>
                            <div v-else-if="current.mode === 'snapshot'" class="scope-note">
                                当前使用静态目录与导入快照。需要新的价格记录时，请在数据管理中导入报价。
                            </div>
                            <Notice :message="state.actionError" error />
                            <div class="detail-schedule">
                                监控 ID：<span class="wrap-anywhere">{{ current.id }}</span>
                            </div>
                        </section>
                    </aside>
                </div>
            </div>
        </section>
        <AppDialog
            class="confirm-dialog"
            :open="confirm"
            labelledby="confirm-title"
            :busy="state.pending === 'delete'"
            @close="confirm = false"
            ><h2 id="confirm-title">删除这项监控？</h2>
            <p>对应的价格记录和提醒也会被删除。</p>
            <Notice :message="state.actionError" error />
            <div class="dialog-actions">
                <button
                    class="button secondary"
                    :disabled="state.pending === 'delete'"
                    @click="confirm = false"
                >
                    保留监控</button
                ><button
                    class="button danger"
                    :disabled="state.pending === 'delete'"
                    @click="act('delete')"
                >
                    {{ state.pending === 'delete' ? '删除中…' : '确认删除' }}
                </button>
            </div></AppDialog
        >
    </section>
</template>

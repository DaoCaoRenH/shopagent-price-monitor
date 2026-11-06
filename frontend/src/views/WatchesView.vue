<script setup lang="ts">
import { computed, ref } from 'vue'
import { useDashboard } from '../composables/useDashboard'
import { amount, date, variant } from '../lib/format'
import EmptyState from '../components/common/EmptyState.vue'
import Icon from '../components/common/Icon.vue'
import PricePosition from '../components/watches/PricePosition.vue'
const { state } = useDashboard(),
    filter = ref('all')
const watches = computed(() =>
    state.watches.filter(
        (w) =>
            filter.value === 'all' ||
            (filter.value === 'active' && w.active) ||
            (filter.value === 'paused' && !w.active) ||
            (filter.value === 'simulation' && w.mode === 'simulation'),
    ),
)
</script>
<template>
    <section id="view-watches" class="view">
        <section class="panel watch-panel">
            <div class="panel-heading">
                <h2>
                    监控商品 <span class="count">{{ state.watches.length }}</span>
                </h2>
                <label class="filter-label"
                    ><span class="sr-only">筛选监控状态</span
                    ><select v-model="filter">
                        <option value="all">全部状态</option>
                        <option value="active">正在监控</option>
                        <option value="paused">已暂停</option>
                        <option value="simulation">模拟监控</option>
                    </select></label
                >
            </div>
            <div id="watch-list" aria-live="polite">
                <EmptyState v-if="state.loading" title="正在加载监控…" /><template
                    v-else-if="watches.length"
                    ><div class="watch-table-head">
                        <span>商品 / 监控状态</span><span>当前价格</span><span>采集最低</span
                        ><span>操作</span>
                    </div>
                    <RouterLink
                        v-for="watch in watches"
                        :key="watch.id"
                        class="watch-row"
                        :to="{ name: 'watch-detail', params: { id: watch.id } }"
                        :aria-label="`查看价格走势：${watch.title}`"
                        ><div>
                            <div class="product-title">{{ watch.title }}</div>
                            <div class="watch-variant" :title="variant(watch)">
                                {{ variant(watch) }}
                            </div>
                            <PricePosition :watch="watch" />
                            <div class="watch-tags">
                                <span class="status-label" :class="{ paused: !watch.active }">{{
                                    watch.simulation?.complete
                                        ? '✓ 回放完成'
                                        : watch.active
                                          ? '● 监控中'
                                          : 'Ⅱ 已暂停'
                                }}</span
                                ><span
                                    class="tag"
                                    :class="{ simulation: watch.mode === 'simulation' }"
                                    >{{
                                        watch.mode === 'simulation' ? '模拟监控' : '价格快照'
                                    }}</span
                                ><span v-if="watch.last_error" class="tag simulation"
                                    >更新异常</span
                                >
                            </div>
                        </div>
                        <div class="watch-price">
                            <span class="mobile-price-label">当前报价</span>
                            ¥{{ amount(watch.current_price)
                            }}<small>{{ date(watch.current_observed_at) }}</small>
                        </div>
                        <div class="watch-price low">
                            <span class="mobile-price-label">采集最低</span>
                            ¥{{ amount(watch.low_price)
                            }}<small>{{ watch.sample_count }} 次采样</small>
                        </div>
                        <span class="button secondary watch-trend-link"
                            >查看价格走势 <Icon name="arrowRight" /></span></RouterLink></template
                ><EmptyState
                    v-else
                    :title="state.watches.length ? '没有符合筛选的监控' : '还没有监控商品'"
                    :description="
                        state.watches.length
                            ? '切换筛选条件查看其他监控。'
                            : '先搜索商品并确认规格，添加监控后就能在这里查看价格走势。'
                    "
                    ><RouterLink v-if="!state.watches.length" class="button secondary" to="/monitor"
                        >去搜索商品 <Icon name="arrowRight" /></RouterLink
                ></EmptyState>
            </div>
        </section>
    </section>
</template>

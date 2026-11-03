<script setup lang="ts">
import { watch } from 'vue'
import { useRoute } from 'vue-router'
import { useSearchHistory } from '../composables/useSearchHistory'
import { date, elapsed, engineLabel } from '../lib/format'
import Icon from '../components/common/Icon.vue'
import Notice from '../components/common/Notice.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ProductList from '../components/products/ProductList.vue'
import ExecutionSteps from '../components/search/ExecutionSteps.vue'
const { state, load, select } = useSearchHistory(),
    route = useRoute()
watch(
    () => route.query.record,
    (id) => {
        void load(false, typeof id === 'string' ? id : undefined)
    },
    { immediate: true },
)
</script>
<template>
    <section id="view-history" class="view">
        <div class="history-grid">
            <section class="panel history-list-panel" aria-labelledby="history-list-title">
                <div class="panel-heading">
                    <h2 id="history-list-title">
                        过往搜索 <span class="count">{{ state.total }}</span>
                    </h2>
                    <button
                        class="text-button"
                        :disabled="state.loading"
                        @click="load(false, state.selected)"
                    >
                        刷新
                    </button>
                </div>
                <form class="history-filter" @submit.prevent="load(false)">
                    <label class="sr-only" for="history-filter">按历史需求查找</label
                    ><input
                        id="history-filter"
                        v-model="state.query"
                        maxlength="500"
                        placeholder="按历史需求查找"
                    /><button class="icon-button" type="submit" aria-label="查找搜索记录">
                        <Icon name="search" />
                    </button>
                </form>
                <Notice :message="state.error" error />
                <div id="search-history-list" aria-label="搜索记录列表" :aria-busy="state.loading">
                    <button
                        v-for="record in state.records"
                        :key="record.id"
                        class="history-row"
                        :class="{ selected: record.id === state.selected }"
                        :aria-pressed="record.id === state.selected"
                        @click="select(record.id)"
                    >
                        <span class="history-row-time">{{ date(record.completed_at, true) }}</span
                        ><strong>{{ record.description }}</strong
                        ><span class="history-row-meta"
                            ><span
                                >{{ record.result_count }} 个候选 ·
                                {{ engineLabel(record.engine) }}</span
                            ><span>{{ elapsed(record.elapsed_ms) }}</span></span
                        >
                    </button>
                    <p
                        v-if="state.loading && !state.records.length"
                        class="history-placeholder"
                        role="status"
                    >
                        正在读取搜索记录…
                    </p>
                    <EmptyState
                        v-if="!state.loading && !state.records.length"
                        icon="history"
                        :title="state.query ? '没有匹配的记录' : '还没有搜索记录'"
                        description="完成一次商品搜索后，候选和理由会自动保存在这里。"
                    />
                </div>
                <div class="history-pagination">
                    <button
                        v-if="state.cursor"
                        class="button secondary"
                        :disabled="state.loading"
                        @click="load(true)"
                    >
                        加载更早记录
                    </button>
                </div>
            </section>
            <section
                class="panel history-detail-panel"
                aria-label="当次搜索的候选商品"
                :aria-busy="state.detailLoading"
            >
                <p v-if="state.detailLoading" class="history-placeholder" role="status">
                    正在读取当次候选…
                </p>
                <EmptyState
                    v-else-if="state.detailError"
                    title="未能读取这条记录"
                    :description="state.detailError"
                    ><button class="button secondary" @click="select(state.selected)">
                        重新读取
                    </button></EmptyState
                ><template v-else-if="state.detail"
                    ><div class="history-detail-heading">
                        <div class="history-detail-meta">
                            <span class="tag" :class="{ agent: state.detail.engine === 'model' }">{{
                                engineLabel(state.detail.engine)
                            }}</span
                            ><time>{{ date(state.detail.completed_at, true) }}</time
                            ><span>用时 {{ elapsed(state.detail.elapsed_ms) }}</span>
                        </div>
                        <h2>{{ state.detail.description }}</h2>
                        <p class="body-copy">{{ state.detail.message }}</p>
                    </div>
                    <div class="history-price-note">
                        保留搜索当时的候选与参考价。查看详情会读取当前目录；加入监控时请重新确认规格与报价。
                    </div>
                    <div class="panel-heading">
                        <h3>
                            当次候选 <span class="count">{{ state.detail.products.length }}</span>
                        </h3>
                        <span class="quiet-label">可继续查看并加入监控</span>
                    </div>
                    <ProductList
                        :products="state.detail.products"
                        :description="state.detail.description"
                        historical /><ExecutionSteps
                        v-if="state.detail.events.length"
                        class="history-execution"
                        :events="state.detail.events"
                        historical /></template
                ><EmptyState
                    v-else
                    title="留住每一次比较"
                    icon="history"
                    description="完成搜索后，可以在这里找回候选商品。"
                    ><RouterLink class="button secondary" to="/monitor"
                        >去搜索商品 <Icon name="arrowRight" /></RouterLink
                ></EmptyState>
            </section>
        </div>
    </section>
</template>

<script setup lang="ts">
import type { Watch } from '../../types/api'
import { amount, variant } from '../../lib/format'
import Icon from '../common/Icon.vue'
import PricePosition from './PricePosition.vue'
defineProps<{ watches: Watch[]; loading: boolean }>()
</script>
<template>
    <aside class="watch-preview panel" aria-labelledby="watch-preview-title">
        <div class="panel-heading">
            <div>
                <span class="section-kicker">价格随时回看</span>
                <h2 id="watch-preview-title">正在关注</h2>
            </div>
            <Icon name="chart" />
        </div>
        <p v-if="loading" class="preview-empty" role="status">正在读取关注的商品…</p>
        <div v-else-if="!watches.length" class="preview-empty">
            <span class="preview-empty-icon"><Icon name="bag" /></span>
            <h3>把想买的商品留在这里</h3>
            <p>搜索后确认规格并加入监控，价格记录和低价提醒会持续保留。</p>
        </div>
        <RouterLink
            v-for="watch in watches.slice(0, 2)"
            :key="watch.id"
            class="preview-watch"
            :to="{ name: 'watch-detail', params: { id: watch.id } }"
        >
            <div class="preview-watch-title">
                <strong>{{ watch.title }}</strong
                ><Icon name="arrowRight" />
            </div>
            <span class="preview-variant"
                >{{ variant(watch) }} · {{ watch.mode === 'simulation' ? '模拟' : '快照'
                }}{{ !watch.active ? ' · 已暂停' : ''
                }}{{ watch.last_error ? ' · 更新异常' : '' }}</span
            >
            <div class="preview-quote">
                <strong><small>¥</small>{{ amount(watch.current_price) }}</strong
                ><PricePosition :watch="watch" />
            </div>
        </RouterLink>
        <RouterLink class="preview-all" to="/watches"
            >查看我的监控<span>{{ watches.length }} 项 <Icon name="arrowRight" /></span
        ></RouterLink>
    </aside>
</template>

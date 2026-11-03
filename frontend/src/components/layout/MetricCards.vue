<script setup lang="ts">
import type { DashboardStatus } from '../../types/api'
defineProps<{ status: DashboardStatus | null }>()
</script>
<template>
    <section class="metrics" aria-label="监控概况">
        <div>
            <span>监控商品</span><strong>{{ status?.watch_count ?? '—' }}</strong
            ><small>个商品规格</small>
        </div>
        <div>
            <span>正在监控</span><strong>{{ status?.active_count ?? '—' }}</strong
            ><small>自动定时检查</small>
        </div>
        <div>
            <span>价格采样</span><strong>{{ status?.observation_count ?? '—' }}</strong
            ><small>条已保存记录</small>
        </div>
        <div class="metric-alert">
            <span>未读低价提醒</span><strong>{{ status?.unread_count ?? '—' }}</strong
            ><small>低于此前采集最低价</small>
        </div>
    </section>
</template>

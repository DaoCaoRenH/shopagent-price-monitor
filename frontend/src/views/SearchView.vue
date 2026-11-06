<script setup lang="ts">
import { useDashboard } from '../composables/useDashboard'
import SearchPanel from '../components/search/SearchPanel.vue'
import AlertList from '../components/watches/AlertList.vue'
import WatchPreview from '../components/watches/WatchPreview.vue'
import MetricCards from '../components/layout/MetricCards.vue'
import Icon from '../components/common/Icon.vue'
const { state } = useDashboard()
</script>
<template>
    <section id="view-monitor" class="view">
        <div class="discovery-grid">
            <SearchPanel />
            <WatchPreview :watches="state.watches" :loading="state.loading" />
        </div>
        <MetricCards :status="state.status" />
        <section class="panel recent-alerts">
            <div class="panel-heading">
                <h2>
                    <Icon name="bell" /> 低价提醒
                    <span class="count">{{ state.status?.unread_count ?? '—' }} 条未读</span>
                </h2>
                <RouterLink class="text-button" to="/alerts">查看全部 ↗</RouterLink>
            </div>
            <AlertList :alerts="state.alerts.slice(0, 3)" />
        </section>
    </section>
</template>

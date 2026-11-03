<script setup lang="ts">
import { useDashboard } from '../composables/useDashboard'
import SearchPanel from '../components/search/SearchPanel.vue'
import AlertList from '../components/watches/AlertList.vue'
import Icon from '../components/common/Icon.vue'
const { state } = useDashboard()
</script>
<template>
    <section id="view-monitor" class="view">
        <SearchPanel />
        <section class="panel monitor-entry">
            <span class="monitor-entry-icon"><Icon name="chart" /></span>
            <div>
                <h2>
                    我的监控 <span class="count">{{ state.watches.length }}</span>
                </h2>
                <p>
                    {{
                        state.watches.length
                            ? `${state.watches.length} 项监控，${state.status?.active_count || 0} 项正在更新。查看价格走势、采样记录与购买建议。`
                            : '添加商品后，在这里集中查看价格走势与采样记录。'
                    }}
                </p>
            </div>
            <RouterLink class="button secondary" to="/watches"
                >查看我的监控 <Icon name="arrowRight"
            /></RouterLink>
        </section>
        <section class="panel recent-alerts">
            <div class="panel-heading">
                <h2><Icon name="bell" /> 最近低价提醒</h2>
                <RouterLink class="text-button" to="/alerts">查看全部 ↗</RouterLink>
            </div>
            <AlertList :alerts="state.alerts.slice(0, 3)" />
        </section>
    </section>
</template>

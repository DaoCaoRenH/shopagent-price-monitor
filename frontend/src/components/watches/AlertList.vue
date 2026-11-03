<script setup lang="ts">
import type { Alert } from '../../types/api'
import { amount, date } from '../../lib/format'
import { useAlerts } from '../../composables/useAlerts'
import Icon from '../common/Icon.vue'
defineProps<{ alerts: Alert[] }>()
const { pending, markRead } = useAlerts()
</script>
<template>
    <div>
        <div v-if="!alerts.length" class="alert-empty">
            <Icon name="bell" />还没有低价提醒。后续报价低于此前采集最低价时，会显示在这里。
        </div>
        <article v-for="alert in alerts" :key="alert.id" class="alert-row">
            <span class="alert-emblem"><Icon name="down" /></span>
            <div class="alert-info">
                <h3>
                    <span v-if="!alert.is_read" class="unread-dot" aria-label="未读"></span
                    >{{ alert.title }}
                </h3>
                <p>
                    <strong>¥{{ amount(alert.price) }}</strong> · 比此前最低 ¥{{
                        amount(alert.previous_low)
                    }}
                    再降 {{ alert.drop_percent }}%
                    <span v-if="alert.mode === 'simulation'" class="tag simulation">模拟提醒</span>
                </p>
                <div class="alert-time">
                    {{ date(alert.observed_at, true) }} ·
                    {{ Object.values(alert.selections).join(' / ') || '无可选规格' }}
                </div>
            </div>
            <div class="alert-side">
                <RouterLink
                    class="text-button"
                    :to="{ name: 'watch-detail', params: { id: alert.watch_id } }"
                    >查看价格走势</RouterLink
                ><span v-if="alert.is_read" class="quiet-label">已读</span
                ><button
                    v-else
                    class="text-button"
                    :disabled="pending.has(alert.id)"
                    @click="markRead(alert.id)"
                >
                    {{ pending.has(alert.id) ? '保存中…' : '标为已读' }}
                </button>
            </div>
        </article>
    </div>
</template>

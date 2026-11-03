<script setup lang="ts">
import { computed } from 'vue'
import type { Observation } from '../../types/api'
import { priceChart } from '../../lib/priceChart'
import { amount, date, sourceLabel } from '../../lib/format'
const props = defineProps<{ observations: Observation[]; lowMinor: number }>()
const chart = computed(() => priceChart(props.observations, props.lowMinor))
</script>
<template>
    <svg
        v-if="chart"
        class="chart"
        :viewBox="`0 0 ${chart.width} ${chart.height}`"
        role="img"
        :aria-label="`${observations.length} 条价格记录，已采集最低价 ${lowMinor / 100} 元`"
    >
        <title>价格记录与已采集最低价</title>
        <g v-for="line in chart.grid" :key="line.y">
            <line
                :x1="chart.left"
                :x2="chart.width - chart.right"
                :y1="line.y"
                :y2="line.y"
                stroke="#edf1ee"
            />
            <text
                :x="chart.left - 9"
                :y="line.y + 3"
                text-anchor="end"
                fill="#78867f"
                font-size="10"
            >
                {{ line.label }}
            </text>
        </g>
        <line
            :x1="chart.left"
            :x2="chart.width - chart.right"
            :y1="chart.lowY"
            :y2="chart.lowY"
            stroke="#81ab90"
            stroke-dasharray="4 4"
        />
        <polyline
            v-if="observations.length > 1"
            :points="chart.line"
            fill="none"
            stroke="#1b6351"
            stroke-width="2.2"
            stroke-linejoin="round"
        />
        <circle
            v-for="point in chart.points"
            :key="point.observation.id"
            :cx="point.x"
            :cy="point.y"
            :r="observations.length > 70 ? 1.5 : 3.5"
            fill="#1b6351"
            stroke="white"
            stroke-width="1.5"
        >
            <title>
                {{ date(point.observation.observed_at, true) }} · ¥{{
                    amount(point.observation.price)
                }}
                · {{ sourceLabel(point.observation.source) }}
            </title>
        </circle>
        <text :x="chart.left" :y="chart.height - 4" fill="#78867f" font-size="10">
            {{ date(new Date(chart.start).toISOString()) }}
        </text>
        <text
            v-if="chart.start !== chart.end"
            :x="chart.width - chart.right"
            :y="chart.height - 4"
            text-anchor="end"
            fill="#78867f"
            font-size="10"
        >
            {{ date(new Date(chart.end).toISOString()) }}
        </text>
    </svg>
    <div v-else class="chart-empty">还没有价格记录</div>
</template>

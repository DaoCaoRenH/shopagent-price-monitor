<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useId } from 'vue'
import type { Observation } from '../../types/api'
import { priceChart } from '../../lib/priceChart'
import { amount, date, sourceLabel } from '../../lib/format'
import Icon from '../common/Icon.vue'
const props = defineProps<{ observations: Observation[]; lowMinor: number }>()
const container = ref<HTMLElement | null>(null),
    availableWidth = ref(680)
const chart = computed(() => priceChart(props.observations, props.lowMinor, availableWidth.value))
let observer: ResizeObserver | undefined
onMounted(() => {
    observer = new ResizeObserver(([entry]) => {
        if (entry && entry.contentRect.width > 0) availableWidth.value = entry.contentRect.width
    })
    if (container.value) observer.observe(container.value)
})
onUnmounted(() => observer?.disconnect())
const selectedId = ref<number | null>(null)
const selectedIndex = computed(() => {
    const index = props.observations.findIndex((item) => item.id === selectedId.value)
    return index < 0 ? props.observations.length - 1 : index
})
const selected = computed(() => chart.value?.points[selectedIndex.value])
const fillId = `price-area-${useId()}`
function move(offset: number) {
    const next = props.observations[selectedIndex.value + offset]
    if (next) selectedId.value = next.id
}
function pointAt(event: PointerEvent) {
    const svg = event.currentTarget as SVGSVGElement
    const matrix = svg.getScreenCTM()
    if (!matrix || !chart.value) return
    const x = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse()).x
    const closest = chart.value.points.reduce((best, point) =>
        Math.abs(point.x - x) < Math.abs(best.x - x) ? point : best,
    )
    selectedId.value = closest.observation.id
}
</script>
<template>
    <div ref="container" class="price-chart">
        <template v-if="chart && selected">
            <div class="chart-readout">
                <div aria-live="polite" aria-atomic="true">
                    <strong>¥{{ amount(selected.observation.price) }}</strong>
                    <span
                        >{{ date(selected.observation.observed_at, true) }} ·
                        {{ sourceLabel(selected.observation.source) }}</span
                    >
                </div>
                <div class="chart-navigation" aria-label="逐条查看价格记录">
                    <button
                        type="button"
                        class="icon-button"
                        aria-label="上一个采样"
                        :disabled="selectedIndex === 0"
                        @click="move(-1)"
                    >
                        <Icon name="arrowLeft" />
                    </button>
                    <button
                        type="button"
                        class="icon-button"
                        aria-label="下一个采样"
                        :disabled="selectedIndex === observations.length - 1"
                        @click="move(1)"
                    >
                        <Icon name="arrowRight" />
                    </button>
                </div>
            </div>
            <svg
                class="chart"
                :viewBox="`0 0 ${chart.width} ${chart.height}`"
                role="img"
                :aria-label="`${observations.length} 条价格记录，已采集最低价 ${lowMinor / 100} 元`"
                @pointermove="pointAt"
                @pointerdown="pointAt"
            >
                <title>价格记录与已采集最低价；可用上方按钮逐条查看报价</title>
                <defs>
                    <linearGradient :id="fillId" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#087f86" stop-opacity="0.16" />
                        <stop offset="100%" stop-color="#087f86" stop-opacity="0" />
                    </linearGradient>
                </defs>
                <g v-for="line in chart.grid" :key="line.y">
                    <line
                        :x1="chart.left"
                        :x2="chart.width - chart.right"
                        :y1="line.y"
                        :y2="line.y"
                        class="chart-gridline"
                    />
                    <text :x="chart.left - 9" :y="line.y + 4" text-anchor="end" class="chart-axis">
                        {{ line.label }}
                    </text>
                </g>
                <polygon
                    v-if="observations.length > 1 && chart.start !== chart.end"
                    :points="`${chart.left},${chart.height - 28} ${chart.line} ${chart.width - chart.right},${chart.height - 28}`"
                    :fill="`url(#${fillId})`"
                />
                <line
                    :x1="chart.left"
                    :x2="chart.width - chart.right"
                    :y1="chart.lowY"
                    :y2="chart.lowY"
                    class="chart-low-line"
                />
                <polyline
                    v-if="observations.length > 1"
                    :points="chart.line"
                    class="chart-price-line"
                />
                <line
                    :x1="selected.x"
                    :x2="selected.x"
                    y1="15"
                    :y2="chart.height - 28"
                    class="chart-cursor"
                />
                <circle
                    v-for="point in chart.points"
                    :key="point.observation.id"
                    :cx="point.x"
                    :cy="point.y"
                    :r="observations.length > 70 ? 1.5 : 3"
                    class="chart-point"
                >
                    <title>
                        {{ date(point.observation.observed_at, true) }} · ¥{{
                            amount(point.observation.price)
                        }}
                        · {{ sourceLabel(point.observation.source) }}
                    </title>
                </circle>
                <circle :cx="selected.x" :cy="selected.y" r="9" class="chart-selected-halo" />
                <circle :cx="selected.x" :cy="selected.y" r="4.5" class="chart-selected-point" />
                <text :x="chart.left" :y="chart.height - 4" class="chart-axis">
                    {{ date(new Date(chart.start).toISOString()) }}
                </text>
                <text
                    v-if="chart.start !== chart.end"
                    :x="chart.width - chart.right"
                    :y="chart.height - 4"
                    text-anchor="end"
                    class="chart-axis"
                >
                    {{ date(new Date(chart.end).toISOString()) }}
                </text>
            </svg>
            <p class="chart-help">移动到曲线查看报价，或用箭头逐条查看。</p>
        </template>
        <div v-else class="chart-empty">还没有价格记录</div>
    </div>
</template>

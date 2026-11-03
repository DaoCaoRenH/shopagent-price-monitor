<script setup lang="ts">
import { computed } from 'vue'
import type { Presets, SimulationState } from '../../types/api'
import { amount, interval } from '../../lib/format'
import ScenarioSteps from './ScenarioSteps.vue'
const props = defineProps<{
    simulation: SimulationState
    presets: Presets | null
    pending?: boolean
}>()
defineEmits<{ restart: [] }>()
const replay = computed(() => props.simulation.engine === 'replay')
const scenario = computed(() =>
    props.presets?.scenarios.find((s) => s.id === props.simulation.scenario),
)
</script>
<template>
    <section class="simulation-summary" aria-label="模拟运行状态">
        <div class="simulation-title">
            <strong>{{ replay ? '固定场景回放' : '事件驱动模拟' }}</strong
            ><span class="tag simulation">{{
                replay
                    ? `${simulation.complete ? '已完成 · ' : ''}${simulation.tick + 1} / ${simulation.total_steps} 步`
                    : `第 ${simulation.tick + 1} 步`
            }}</span>
        </div>
        <p>
            {{ replay ? simulation.scenario_name : `正常售价 ¥${amount(simulation.normal_price)}` }}
        </p>
        <div class="simulation-event">{{ simulation.event }}</div>
        <p class="quiet-label">
            每 {{ interval(simulation.tick_seconds) }}推进一步 ·
            {{ replay ? '固定序列' : '种子 ' + simulation.seed
            }}<br />同一步报价固定；暂停或离线期间时钟继续，恢复后采集当前步。
        </p>
        <details v-if="scenario">
            <summary>查看固定序列与当前步骤</summary>
            <p class="quiet-label">数值为相对初始报价的比例</p>
            <ScenarioSteps :scenario="scenario" :current="simulation.tick" />
        </details>
        <button
            v-if="replay"
            class="button secondary"
            :disabled="pending"
            @click="$emit('restart')"
        >
            重新回放（保留记录）
        </button>
    </section>
</template>

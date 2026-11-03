<script setup lang="ts">
import { computed } from 'vue'
import type { Presets, SimulationConfig } from '../../types/api'
import ScenarioSteps from '../watches/ScenarioSteps.vue'
const props = defineProps<{
    modelValue: SimulationConfig
    interval: number
    presets: Presets | null
}>()
const emit = defineEmits<{ 'update:modelValue': [value: SimulationConfig] }>()
function set<K extends keyof SimulationConfig>(key: K, value: SimulationConfig[K]) {
    emit('update:modelValue', { ...props.modelValue, [key]: value })
}
const replay = computed(() => props.modelValue.engine === 'replay')
const scenario = computed(() =>
    props.presets?.scenarios.find((s) => s.id === props.modelValue.scenario),
)
</script>
<template>
    <fieldset id="simulation-settings" class="simulation-settings">
        <legend>模拟价格如何变化</legend>
        <label class="field-label" for="simulation-engine"
            >模拟方式<select
                id="simulation-engine"
                :value="modelValue.engine"
                @change="
                    set('engine', ($event.target as HTMLSelectElement).value as 'event' | 'replay')
                "
            >
                <option value="event">事件驱动：同价、调价与促销</option>
                <option value="replay">固定场景回放</option>
            </select></label
        >
        <div class="form-columns">
            <label v-if="!replay" class="field-label" for="simulation-seed"
                >随机种子<input
                    id="simulation-seed"
                    :value="modelValue.seed"
                    type="number"
                    min="0"
                    max="2147483647"
                    step="1"
                    required
                    @input="
                        set('seed', Number(($event.target as HTMLInputElement).value))
                    " /></label
            ><label class="field-label" for="simulation-period"
                >价格推进间隔<select
                    id="simulation-period"
                    :value="modelValue.tick_seconds"
                    @change="
                        set('tick_seconds', Number(($event.target as HTMLSelectElement).value))
                    "
                >
                    <option :value="30">每 30 秒一步</option>
                    <option :value="60">每 1 分钟一步</option>
                    <option :value="300">每 5 分钟一步</option>
                </select></label
            >
        </div>
        <label v-if="replay" class="field-label" for="simulation-scenario"
            >回放场景<select
                id="simulation-scenario"
                :value="modelValue.scenario || ''"
                required
                @change="set('scenario', ($event.target as HTMLSelectElement).value)"
            >
                <option value="" disabled>请选择场景</option>
                <option v-for="item in presets?.scenarios" :key="item.id" :value="item.id">
                    {{ item.name }}
                </option>
            </select></label
        >
        <p class="field-help">
            {{
                replay
                    ? '按固定序列回放，结束后停止采样；重播会保留本次记录。'
                    : '大部分时间同价，偶尔调价或限时促销，促销结束恢复正常售价。固定种子可复现事件序列。'
            }}{{
                interval > modelValue.tick_seconds
                    ? replay
                        ? ' 请将检查间隔调至不大于价格推进间隔。'
                        : ' 采样较慢时可能错过中间价格。'
                    : ''
            }}
        </p>
        <details v-if="replay && scenario" class="scenario-preview">
            <summary>预览固定价格序列</summary>
            <p>相对初始报价的比例</p>
            <ScenarioSteps :scenario="scenario" />
        </details>
    </fieldset>
</template>

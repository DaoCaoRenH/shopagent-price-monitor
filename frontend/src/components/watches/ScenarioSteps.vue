<script setup lang="ts">
import type { Scenario } from '../../types/api'
defineProps<{ scenario: Scenario; current?: number }>()
</script>
<template>
    <ol class="scenario-steps">
        <li
            v-for="(step, index) in scenario.steps"
            :key="index"
            :class="{ current: index === current }"
        >
            <span>{{ index + 1 }}</span
            ><strong>{{ step.percent == null ? '获取失败' : step.percent + '%' }}</strong
            ><small>{{ step.event }}</small>
        </li>
    </ol>
</template>

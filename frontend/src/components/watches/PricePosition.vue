<script setup lang="ts">
import { computed } from 'vue'
import type { Watch } from '../../types/api'
const props = defineProps<{ watch: Watch }>()
// This describes saved observations; it does not make a purchase recommendation.
const position = computed(() => {
    if (props.watch.sample_count < 2) return { text: '首条报价 · 待积累', low: false }
    const gap = props.watch.current_minor - props.watch.low_minor
    return gap === 0
        ? { text: '与采集最低持平', low: true }
        : { text: `距采集最低 +${((gap / props.watch.low_minor) * 100).toFixed(2)}%`, low: false }
})
</script>
<template>
    <span class="price-position" :class="{ 'at-low': position.low }">{{ position.text }}</span>
</template>

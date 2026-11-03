<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { ProgressEvent } from '../../types/api'
import { elapsed } from '../../lib/format'
const props = defineProps<{ events: ProgressEvent[]; historical?: boolean }>()
const log = ref<HTMLOListElement | null>(null)
const labels: Record<string, string> = {
    running: '进行中',
    completed: '已完成',
    notice: '提示',
    blocked: '已阻断',
    interrupted: '已中止',
}
const status = (event: ProgressEvent) =>
    props.historical && event.status === 'running' ? 'interrupted' : event.status || 'notice'
watch(
    () => props.events.map((e) => `${e.step_id}:${e.status}:${e.message}`).join('|'),
    async () => {
        const atBottom =
            !log.value || log.value.scrollHeight - log.value.scrollTop - log.value.clientHeight < 35
        await nextTick()
        if (atBottom && log.value) log.value.scrollTop = log.value.scrollHeight
    },
)
</script>
<template>
    <details class="search-progress-details" :open="!historical">
        <summary>
            {{ historical ? '查看当次执行记录' : '执行记录' }} <span>{{ events.length }} 步</span>
        </summary>
        <ol
            ref="log"
            :id="historical ? undefined : 'search-progress-log'"
            aria-label="搜索执行记录"
        >
            <li
                v-for="(event, index) in events"
                :key="event.step_id || index"
                class="search-step"
                :class="'is-' + status(event)"
            >
                <span class="search-step-dot" aria-hidden="true"></span>
                <div>
                    <p>{{ event.message }}</p>
                    <small>{{ elapsed(event.elapsed_ms) }}</small>
                </div>
                <span class="search-step-status">{{ labels[status(event)] || '提示' }}</span>
            </li>
        </ol>
    </details>
</template>

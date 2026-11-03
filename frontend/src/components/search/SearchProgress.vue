<script setup lang="ts">
import { computed } from 'vue'
import { useSearch } from '../../composables/useSearch'
import { elapsed, engineLabel } from '../../lib/format'
import ExecutionSteps from './ExecutionSteps.vue'
const { state, round, roundLimit, stats } = useSearch()
const titles: Record<string, string> = {
    starting: '正在准备搜索',
    planning: 'Agent 正在分析',
    model_stream: '正在接收模型响应',
    model_retry: '正在重试当前轮',
    tool_repair: '正在补正工具调用',
    model_error: '模型调用未能完成',
    searching: '正在检索商品',
    inspecting: '正在核对商品',
    summarizing: '正在整理候选',
    retaining: '正在保留已有候选',
    fallback: '正在使用目录检索',
    tool_limit: '正在调整执行步骤',
    completed: '正在接收搜索结果',
}
const progressState = computed(() =>
    state.running
        ? 'running'
        : state.error
          ? 'error'
          : state.result?.engine === 'partial'
            ? 'partial'
            : 'complete',
)
const title = computed(() =>
    state.running
        ? titles[state.latest?.stage || 'starting'] || '正在执行搜索'
        : state.error
          ? '搜索已中断'
          : state.result?.engine === 'partial'
            ? '已保留候选，筛选未完成'
            : '搜索已完成',
)
const message = computed(() =>
    state.running
        ? state.latest?.message || '正在提交搜索请求…'
        : state.error || state.result?.message,
)
</script>
<template>
    <section
        v-if="state.started"
        id="search-progress"
        class="search-progress"
        :data-state="progressState"
        aria-label="搜索执行进度"
        :aria-busy="state.running"
    >
        <div class="search-progress-heading">
            <strong>{{ title }}</strong
            ><span>{{ state.running ? '已用时' : '总用时' }} {{ elapsed(state.elapsed) }}</span>
        </div>
        <p id="search-progress-message" role="status" aria-live="polite">{{ message }}</p>
        <div
            class="search-progress-track"
            role="progressbar"
            aria-label="搜索执行进度"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-valuenow="progressState === 'complete' ? 100 : undefined"
            :aria-valuetext="message"
            aria-describedby="search-progress-message"
        >
            <span></span>
        </div>
        <div class="search-progress-meta">
            <span
                >{{
                    round ? `第 ${round}${roundLimit ? '/' + roundLimit : ''} 轮分析 · ` : ''
                }}已检索 {{ stats.searches }} 次 · 已查看 {{ stats.inspections }} 次</span
            ><span>{{ engineLabel(state.result?.engine || state.latest?.engine || '') }}</span>
        </div>
        <ExecutionSteps :events="state.events" />
    </section>
</template>

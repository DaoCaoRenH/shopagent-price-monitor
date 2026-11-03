<script setup lang="ts">
import type { SearchLimits } from '../../types/api'
const model = defineModel<SearchLimits>({ required: true })
</script>
<template>
    <section class="settings-budget" aria-labelledby="search-budget-title">
        <h3 id="search-budget-title">搜索执行预算</h3>
        <p class="field-help">每次商品搜索独立计数，保存后用于新发起的搜索。</p>
        <div class="settings-fields search-budget-fields">
            <label class="field-label" for="search-max-searches"
                >最多搜索次数<input
                    id="search-max-searches"
                    v-model.number="model.max_searches"
                    type="number"
                    min="1"
                    max="20"
                    step="1"
                    required
                /><small class="field-help">1–20 次，默认 2 次</small></label
            ><label class="field-label" for="search-max-inspections"
                >最多查看商品次数<input
                    id="search-max-inspections"
                    v-model.number="model.max_inspections"
                    type="number"
                    min="0"
                    max="30"
                    step="1"
                    required
                /><small class="field-help">0–30 次，默认 3 次</small></label
            ><label class="field-label" for="search-max-rounds"
                >最多模型调用轮次<input
                    id="search-max-rounds"
                    v-model.number="model.max_model_rounds"
                    type="number"
                    min="2"
                    max="50"
                    step="1"
                    required
                /><small class="field-help">2–50 轮，默认 7 轮</small></label
            >
        </div>
        <p class="field-help budget-explanation">
            每轮模型选择一个操作，被阻断的尝试和最终返回候选也占一轮。无效工具调用每次搜索最多补正 2
            次，并计入总轮次；保留已有搜索与详情。补正或轮次用尽仍未完成时保留已有候选，暂无候选时才回退目录检索。提高上限可能增加耗时。
        </p>
    </section>
</template>

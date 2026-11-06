<script setup lang="ts">
import { useSearch } from '../../composables/useSearch'
import Icon from '../common/Icon.vue'
import Notice from '../common/Notice.vue'
import ProductList from '../products/ProductList.vue'
import SearchProgress from './SearchProgress.vue'
const { state, search, cancel } = useSearch()
</script>
<template>
    <section class="search-panel" aria-labelledby="search-title">
        <div class="section-title">
            <div class="title-with-icon">
                <span class="accent-icon"><Icon name="search" /></span>
                <h2 id="search-title">想关注什么商品？</h2>
            </div>
            <span class="search-source"
                ><span class="dot"></span
                >{{ state.running ? '搜索进行中' : '从商品需求开始' }}</span
            >
        </div>
        <form id="search-form" @submit.prevent="search">
            <label class="sr-only" for="description">需要监控的商品描述</label>
            <div class="search-input-wrap">
                <textarea
                    id="description"
                    v-model="state.description"
                    rows="2"
                    maxlength="500"
                    placeholder="例如：想关注一款无线降噪耳机，黑色，日常通勤使用"
                    required
                    :disabled="state.running"
                ></textarea
                ><button class="button primary" type="submit" :disabled="state.running">
                    <Icon name="search" />{{ state.running ? '正在搜索…' : '搜索商品' }}
                </button>
            </div>
        </form>
        <p class="search-guidance">写下商品、规格和预算，找到候选后再确认要跟踪的款式。</p>
        <div class="search-examples">
            <span>试试搜索</span
            ><button
                v-for="query in ['无线降噪耳机 黑色', '跑步运动鞋 透气', '保温杯 不锈钢']"
                :key="query"
                :disabled="state.running"
                @click="state.description = query"
            >
                {{ query }}</button
            ><button v-if="state.running" class="text-button" @click="cancel">停止接收</button>
        </div>
        <ol v-if="!state.result && !state.running" class="search-flow" aria-label="添加监控的步骤">
            <li>
                <span>1</span>
                <div><strong>找到商品</strong><small>按需求搜索候选</small></div>
            </li>
            <li>
                <span>2</span>
                <div><strong>确认规格</strong><small>选定要关注的款式</small></div>
            </li>
            <li>
                <span>3</span>
                <div><strong>跟踪价格</strong><small>查看记录与低价提醒</small></div>
            </li>
        </ol>
        <SearchProgress /><Notice :message="state.result?.history_warning" error />
        <div v-if="state.result && state.visible" id="search-results">
            <div class="results-heading">
                <h3>
                    候选商品 <span>{{ state.result.products.length }} 个</span>
                </h3>
                <div class="results-actions">
                    <RouterLink
                        v-if="state.result.search_id"
                        class="text-button"
                        :to="{ name: 'history', query: { record: state.result.search_id } }"
                        >查看本次记录 ↗</RouterLink
                    ><button class="text-button" @click="state.visible = false">收起结果</button>
                </div>
            </div>
            <ProductList
                :products="state.result.products"
                :description="state.submittedDescription"
            />
        </div>
        <button v-else-if="state.result" class="text-button" @click="state.visible = true">
            展开 {{ state.result.products.length }} 个候选商品
        </button>
    </section>
</template>

<script setup lang="ts">
import { computed, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDashboard } from '../../composables/useDashboard'
import Icon from '../common/Icon.vue'
import Notice from '../common/Notice.vue'
import MetricCards from './MetricCards.vue'
const route = useRoute(),
    router = useRouter(),
    { state } = useDashboard()
const navigation = [
    { name: 'monitor', label: '价格监控', icon: 'activity' },
    { name: 'watches', label: '我的监控', icon: 'chart' },
    { name: 'history', label: '搜索记录', icon: 'history' },
    { name: 'alerts', label: '低价提醒', icon: 'bell' },
    { name: 'data', label: '数据管理', icon: 'database' },
    { name: 'settings', label: '模型配置', icon: 'settings' },
]
const current = computed(() => (route.name === 'watch-detail' ? 'watches' : route.name))
const connection = computed(() =>
    state.error
        ? '连接已断开'
        : !state.status
          ? '正在连接…'
          : state.status.scheduler_error
            ? '检查异常，将重试'
            : state.status.scheduler_enabled
              ? '自动检查已开启'
              : '自动检查已关闭',
)
const today = new Date().toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
})
function focusMain() {
    document.getElementById('main')?.focus()
}
async function newWatch() {
    await router.push({ name: 'monitor' })
    await nextTick()
    document.getElementById('description')?.focus()
    document.getElementById('search-form')?.scrollIntoView({ block: 'center' })
}
watch(
    () => route.name,
    async () => {
        document.body.classList.toggle('settings-view', route.name === 'settings')
        document.body.classList.toggle('watch-detail-view', route.name === 'watch-detail')
        await nextTick()
        document.getElementById('page-title')?.focus({ preventScroll: true })
        window.scrollTo(0, 0)
    },
    { immediate: true },
)
</script>
<template>
    <a class="skip-link" href="#main" @click.prevent="focusMain">跳到主要内容</a>
    <aside class="sidebar">
        <RouterLink class="brand" to="/monitor" aria-label="ShopAgent 首页"
            ><span class="brand-mark"><Icon name="activity" /></span
            ><span>ShopAgent<small>价格观察台</small></span></RouterLink
        >
        <div class="nav-label">我的工作台</div>
        <nav aria-label="主导航">
            <RouterLink
                v-for="item in navigation"
                :key="item.name"
                class="nav-item"
                :class="{ active: current === item.name }"
                :aria-current="current === item.name ? 'page' : undefined"
                :to="{ name: item.name }"
                ><Icon :name="item.icon" />{{ item.label
                }}<span
                    v-if="item.name === 'alerts' && state.status?.unread_count"
                    class="nav-count"
                    >{{ state.status.unread_count }}</span
                ></RouterLink
            >
        </nav>
        <div class="sidebar-foot">
            <Icon name="database" /><span>本机工作空间<small>每个规格，一份价格记录。</small></span>
        </div>
    </aside>
    <div class="workspace">
        <header class="topbar">
            <div class="breadcrumb">
                工作台 <span>/</span><strong>{{ route.meta.breadcrumb }}</strong>
            </div>
            <div class="topbar-right">
                <span
                    class="connection"
                    :class="{ offline: state.error || state.status?.scheduler_error }"
                    >{{ connection }}</span
                ><button class="button primary compact" @click="newWatch">
                    <Icon name="plus" />新建监控
                </button>
            </div>
        </header>
        <main id="main" tabindex="-1">
            <Notice
                :message="
                    state.error ? `无法连接监控服务：${state.error} 恢复后页面会自动重试。` : ''
                "
                error
            />
            <div v-if="state.status?.catalog_is_demo" class="demo-banner" role="note">
                <span class="demo-label">演示模式</span>
                <span>商品与报价均为虚构内容，供体验搜索、监控与低价提醒。</span>
            </div>
            <section class="page-heading">
                <div>
                    <h1 id="page-title" tabindex="-1">{{ route.meta.title }}</h1>
                    <p>{{ route.meta.subtitle }}</p>
                </div>
                <div class="heading-date">{{ today }}</div>
            </section>
            <MetricCards
                v-if="['watches', 'alerts'].includes(String(route.name))"
                :status="state.status"
            /><slot />
            <footer class="page-footer">
                <span>ShopAgent / Price Monitor</span
                ><span>历史最低价依据已采集记录 · 人民币 CNY</span>
            </footer>
        </main>
    </div>
</template>

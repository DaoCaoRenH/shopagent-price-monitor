import { createRouter, createWebHashHistory } from 'vue-router'
import SearchView from './views/SearchView.vue'
import WatchesView from './views/WatchesView.vue'
import WatchDetailView from './views/WatchDetailView.vue'
import HistoryView from './views/HistoryView.vue'
import AlertsView from './views/AlertsView.vue'
import DataView from './views/DataView.vue'
import SettingsView from './views/SettingsView.vue'

// Preserve links shared by the original static application.
const legacy = window.location.hash.slice(1)
if (/^(monitor|watches|history|alerts|data|settings|watch\/[^/]+)$/.test(legacy))
    window.history.replaceState(
        null,
        '',
        `${window.location.pathname}${window.location.search}#/${legacy}`,
    )
export const router = createRouter({
    history: createWebHashHistory(),
    routes: [
        { path: '/', redirect: '/monitor' },
        {
            path: '/monitor',
            name: 'monitor',
            component: SearchView,
            meta: {
                breadcrumb: '价格监控',
                title: '商品价格监控',
                subtitle: '关注想买的商品，等一个更合适的价格。',
            },
        },
        {
            path: '/watches',
            name: 'watches',
            component: WatchesView,
            meta: {
                breadcrumb: '我的监控',
                title: '我的监控',
                subtitle: '关注的商品都在这里，选择一项查看具体价格走势。',
            },
        },
        {
            path: '/watch/:id',
            name: 'watch-detail',
            component: WatchDetailView,
            meta: {
                breadcrumb: '我的监控 / 价格走势',
                title: '商品价格走势',
                subtitle: '查看所选规格的价格变化、采样依据与购买建议。',
            },
        },
        {
            path: '/history',
            name: 'history',
            component: HistoryView,
            meta: {
                breadcrumb: '搜索记录',
                title: '回到上一次的好选择',
                subtitle: '找回搜索时的候选与理由，继续比较，随时加入监控。',
            },
        },
        {
            path: '/alerts',
            name: 'alerts',
            component: AlertsView,
            meta: {
                breadcrumb: '低价提醒',
                title: '低价提醒',
                subtitle: '每一次新低，都有对应的价格记录。',
            },
        },
        {
            path: '/data',
            name: 'data',
            component: DataView,
            meta: {
                breadcrumb: '数据管理',
                title: '价格数据管理',
                subtitle: '导入明确报价，为关注的商品积累价格历史。',
            },
        },
        {
            path: '/settings',
            name: 'settings',
            component: SettingsView,
            meta: {
                breadcrumb: '模型配置',
                title: '配置你的 Agent',
                subtitle: '选择模型服务，为商品搜索和购买建议提供分析。',
            },
        },
        { path: '/:pathMatch(.*)*', redirect: '/monitor' },
    ],
})

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useDashboard } from './composables/useDashboard'
import { useSearch } from './composables/useSearch'
import { errorMessage } from './lib/format'
import AppLayout from './components/layout/AppLayout.vue'
import ProductDialog from './components/products/ProductDialog.vue'
import ToastHost from './components/common/ToastHost.vue'
const dashboard = useDashboard()
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
    void dashboard.refresh()
    void dashboard.loadPresets().catch((error) => {
        dashboard.state.error = errorMessage(error)
    })
    timer = setInterval(() => {
        dashboard.now.value = Date.now()
        if (
            !document.hidden &&
            !document.querySelector('dialog[open]') &&
            !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName || '')
        )
            void dashboard.refresh()
    }, 10000)
})
onUnmounted(() => {
    if (timer) clearInterval(timer)
    if (useSearch().state.running) useSearch().cancel()
})
</script>
<template>
    <AppLayout><RouterView /></AppLayout><ProductDialog /><ToastHost />
</template>

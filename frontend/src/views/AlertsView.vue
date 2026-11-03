<script setup lang="ts">
import { useDashboard } from '../composables/useDashboard'
import AlertList from '../components/watches/AlertList.vue'
const { state } = useDashboard()
</script>
<template>
    <section id="view-alerts" class="view">
        <section class="panel">
            <div class="panel-heading">
                <h2>提醒记录</h2>
                <span class="quiet-label">首次采样与相同最低价不会触发提醒</span>
            </div>
            <AlertList :alerts="state.alerts" />
        </section>
    </section>
</template>

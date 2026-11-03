<script setup lang="ts">
import Icon from './Icon.vue'
withDefaults(defineProps<{ title: string; description?: string; icon?: string }>(), { icon: 'bag' })
</script>
<template>
    <div class="empty-state">
        <span class="empty-icon"><Icon :name="icon" /></span>
        <h3>{{ title }}</h3>
        <p v-if="description">{{ description }}</p>
        <slot />
    </div>
</template>

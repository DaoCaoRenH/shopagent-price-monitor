<script setup lang="ts">
defineProps<{ message?: string; error?: boolean }>()
</script>
<template>
    <div v-if="message" class="notice" :class="{ error }" :role="error ? 'alert' : 'status'">
        {{ message }}
    </div>
</template>

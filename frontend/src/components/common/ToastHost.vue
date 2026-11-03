<script setup lang="ts">
import { useNotifications } from '../../composables/useNotifications'
const { message } = useNotifications()
</script>
<template>
    <div id="toast" role="status" class="toast" :hidden="!message">{{ message }}</div>
</template>

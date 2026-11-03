<script setup lang="ts">
defineProps<{ name: string }>()
// Only these internal SVG constants may be rendered as markup.
const paths: Record<string, string> = {
    bag: '<path d="M5 7h14l1 14H4L5 7Z"/><path d="M9 8V6a3 3 0 0 1 6 0v2m-6 6 3 3 4-5"/>',
    activity: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m6 14 4-4 4 3 4-6"/>',
    history: '<path d="M3 11a9 9 0 1 1 2.6 7.4M3 4v7h7M12 7v5l3 2"/>',
    bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
    database:
        '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    arrowRight: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
    arrowLeft: '<path d="M19 12H5m6-6-6 6 6 6"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    spark: '<path d="m12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3L12 3Zm7-1v4m-2-2h4"/>',
    chart: '<path d="M4 3v17h17M7 14l4-5 4 3 5-7"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    refresh:
        '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1"/>',
    down: '<path d="M12 3v17m-6-6 6 6 6-6"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/>',
    settings:
        '<path d="m9 3-1 3-3 1-2 5 2 5 3 1 1 3h6l1-3 3-1 2-5-2-5-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/>',
}
</script>
<template>
    <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" v-html="paths[name] || paths.bag" />
</template>

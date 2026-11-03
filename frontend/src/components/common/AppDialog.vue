<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
const props = defineProps<{ open: boolean; labelledby: string; busy?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
let previousFocus: HTMLElement | null = null
async function sync() {
    await nextTick()
    if (props.open && !dialog.value?.open) {
        previousFocus =
            document.activeElement instanceof HTMLElement ? document.activeElement : null
        dialog.value?.showModal()
    } else if (!props.open && dialog.value?.open) {
        dialog.value.close()
        previousFocus?.focus()
    }
}
watch(() => props.open, sync)
onMounted(sync)
onBeforeUnmount(() => {
    dialog.value?.close()
    previousFocus?.focus()
})
</script>
<template>
    <dialog
        ref="dialog"
        :aria-labelledby="labelledby"
        :aria-busy="busy"
        @cancel.prevent="!busy && emit('close')"
    >
        <slot />
    </dialog>
</template>

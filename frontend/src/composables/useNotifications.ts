import { ref } from 'vue'
const message = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
export function notify(text: string) {
    clearTimeout(timer)
    message.value = text
    timer = setTimeout(() => {
        message.value = ''
    }, 4500)
}
export function useNotifications() {
    return { message, notify }
}

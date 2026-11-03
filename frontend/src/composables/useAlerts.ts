import { ref } from 'vue'
import { readAlert } from '../api/watches'
import { useDashboard } from './useDashboard'
import { notify } from './useNotifications'
import { errorMessage } from '../lib/format'
export function useAlerts() {
    const pending = ref(new Set<number>())
    async function markRead(id: number) {
        if (pending.value.has(id)) return
        pending.value.add(id)
        try {
            await readAlert(id)
            await useDashboard().refresh()
        } catch (error) {
            notify(errorMessage(error))
        } finally {
            pending.value.delete(id)
        }
    }
    return { pending, markRead }
}

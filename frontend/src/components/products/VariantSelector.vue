<script setup lang="ts">
import type { ProductDetail } from '../../types/api'
defineProps<{ product: ProductDetail; selections: Record<string, string> }>()
defineEmits<{ 'update:selections': [value: Record<string, string>] }>()
</script>
<template>
    <div id="option-fields">
        <label
            v-for="(values, group) in product.option_groups"
            :key="group"
            class="field-label option-field"
            >{{ group
            }}<select
                :value="selections[group] || ''"
                required
                @change="
                    $emit('update:selections', {
                        ...selections,
                        [group]: ($event.target as HTMLSelectElement).value,
                    })
                "
            >
                <option value="">请选择{{ group }}</option>
                <option
                    v-for="value in values"
                    :key="value.value"
                    :value="value.value"
                    :disabled="!value.available"
                >
                    {{ value.value }}{{ value.available ? '' : '（不可选）' }}
                </option>
            </select></label
        >
    </div>
</template>

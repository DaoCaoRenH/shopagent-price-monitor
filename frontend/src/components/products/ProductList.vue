<script setup lang="ts">
import type { Product } from '../../types/api'
import { useProductSelection } from '../../composables/useProductSelection'
import ProductCard from './ProductCard.vue'
import EmptyState from '../common/EmptyState.vue'
defineProps<{ products: Product[]; description: string; historical?: boolean }>()
const selection = useProductSelection()
</script>
<template>
    <div>
        <ProductCard
            v-for="product in products"
            :key="product.asin"
            :product="product"
            :historical="historical"
            @select="selection.open($event, description)"
        /><EmptyState
            v-if="!products.length"
            title="没有找到相关商品"
            description="试试保留品类、品牌或型号，减少场景描述。"
        />
    </div>
</template>

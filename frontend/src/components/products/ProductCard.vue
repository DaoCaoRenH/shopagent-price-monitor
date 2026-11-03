<script setup lang="ts">
import type { Product } from '../../types/api'
import { amount } from '../../lib/format'
import Icon from '../common/Icon.vue'
defineProps<{ product: Product; historical?: boolean }>()
defineEmits<{ select: [asin: string] }>()
</script>
<template>
    <article class="product-row">
        <div class="product-symbol"><Icon name="bag" /></div>
        <div>
            <div class="product-title">{{ product.title }}</div>
            <div class="product-meta">
                店铺：{{ product.shop || '未提供' }} · 分类：{{ product.category || '未提供' }}
            </div>
            <div class="product-facts">
                <span>{{
                    product.option_group_count
                        ? `${product.option_group_count} 组可选规格`
                        : '无可选规格'
                }}</span
                ><span>商品 ID：{{ product.asin }}</span>
            </div>
            <p v-if="product.reason" class="product-reason">{{ product.reason }}</p>
        </div>
        <div class="product-price">
            <strong>{{ product.price == null ? '待确认' : '¥' + amount(product.price) }}</strong
            ><small>{{ historical ? '当次目录参考价' : '目录参考价' }}</small>
        </div>
        <button
            class="button secondary"
            :aria-label="`查看详情：${product.title}`"
            @click="$emit('select', product.asin)"
        >
            查看详情 <Icon name="arrowRight" />
        </button>
    </article>
</template>

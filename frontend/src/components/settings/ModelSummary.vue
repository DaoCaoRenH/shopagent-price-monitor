<script setup lang="ts">
import type { ModelSettings } from '../../types/api'
import { reasoningLabels } from '../../lib/format'
defineProps<{ settings: ModelSettings | null }>()
const providers = {
    'openai-responses': 'Responses',
    'openai-chat': 'Chat Completions',
    gemini: 'Gemini 原生',
}
</script>
<template>
    <aside class="panel settings-summary">
        <div class="panel-heading"><h2>当前生效配置</h2></div>
        <div class="panel-body">
            <div aria-live="polite">
                <template v-if="settings"
                    ><span class="tag" :class="{ agent: settings.enabled }">{{
                        settings.enabled ? '模型已启用' : '模型已关闭'
                    }}</span>
                    <dl class="settings-facts">
                        <dt>模型</dt>
                        <dd>{{ settings.model }}</dd>
                        <dt>接口</dt>
                        <dd>{{ providers[settings.provider] }}</dd>
                        <dt>地址</dt>
                        <dd>{{ settings.base_url }}</dd>
                        <dt>认证</dt>
                        <dd>
                            {{
                                settings.api_key_required
                                    ? settings.has_api_key
                                        ? '已配置密钥'
                                        : '尚未配置密钥'
                                    : '无需认证'
                            }}
                        </dd>
                        <dt>思考强度</dt>
                        <dd>
                            {{
                                reasoningLabels[settings.reasoning_effort] ||
                                settings.reasoning_effort
                            }}
                        </dd>
                        <dt>上下文</dt>
                        <dd>{{ settings.max_context_tokens.toLocaleString('zh-CN') }} Token</dd>
                        <dt>搜索上限</dt>
                        <dd>{{ settings.search_limits.max_searches }} 次 / 每次搜索任务</dd>
                        <dt>查看上限</dt>
                        <dd>{{ settings.search_limits.max_inspections }} 次 / 每次搜索任务</dd>
                        <dt>轮次上限</dt>
                        <dd>{{ settings.search_limits.max_model_rounds }} 轮模型调用</dd>
                    </dl>
                    <p class="field-help">
                        {{
                            settings.persistent
                                ? '配置保存在本机，重启应用后继续使用。'
                                : '配置在本次服务会话生效。'
                        }}
                    </p>
                    <p class="field-help">
                        {{ settings.stream ? '流式接收' : '完整响应' }} · 失败后最多自动重试
                        {{ settings.max_retries }} 次
                    </p></template
                >
                <p v-else>正在读取…</p>
            </div>
            <div class="scope-note">
                保存后，新发起的搜索与购买建议使用此配置。关闭模型后，商品使用目录检索，购买建议使用监控规则。
            </div>
            <p class="field-help">
                测试连接会发起一次工具调用请求，使用当前填写的设置，不会保存配置。
            </p>
        </div>
    </aside>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useModelSettings } from '../composables/useModelSettings'
import { reasoningLabels } from '../lib/format'
import Notice from '../components/common/Notice.vue'
import ModelSummary from '../components/settings/ModelSummary.vue'
import SearchBudgetFields from '../components/settings/SearchBudgetFields.vue'
const { draft, current, state, dirty, load, submit } = useModelSettings(),
    form = ref<HTMLFormElement | null>(null)
function test() {
    if (form.value?.reportValidity()) void submit(false)
}
onMounted(load)
</script>
<template>
    <section id="view-settings" class="view">
        <div class="settings-grid">
            <section class="panel settings-panel" aria-labelledby="model-settings-title">
                <div class="panel-heading">
                    <h2 id="model-settings-title">Agent 模型</h2>
                    <span class="quiet-label">{{
                        state.loading
                            ? '正在读取配置…'
                            : state.loadFailed
                              ? '读取失败'
                              : dirty
                                ? '有未保存的修改'
                                : '与当前配置一致'
                    }}</span>
                </div>
                <form
                    ref="form"
                    class="panel-body"
                    autocomplete="off"
                    @submit.prevent="submit(true)"
                >
                    <fieldset :disabled="state.loading || state.loadFailed || !!state.pending">
                        <label class="settings-toggle"
                            ><input
                                id="model-enabled"
                                v-model="draft.enabled"
                                type="checkbox"
                            />启用模型分析<span class="quiet-label"
                                >用于商品搜索和购买建议</span
                            ></label
                        >
                        <div class="settings-fields">
                            <label class="field-label" for="model-provider"
                                >接口协议<select id="model-provider" v-model="draft.provider">
                                    <option value="openai-responses">OpenAI Responses</option>
                                    <option value="openai-chat">OpenAI Chat Completions</option>
                                </select></label
                            ><label class="field-label" for="model-name"
                                >模型名称<input
                                    id="model-name"
                                    v-model="draft.model"
                                    required
                                    maxlength="200"
                                    placeholder="deepseek-v4.1-flash"
                                    spellcheck="false" /></label
                            ><label class="field-label settings-wide" for="model-url"
                                >服务地址<input
                                    id="model-url"
                                    v-model.trim="draft.base_url"
                                    type="url"
                                    required
                                    maxlength="500"
                                    placeholder="https://api.example.com/v1"
                                    spellcheck="false"
                                /><small class="field-help">{{
                                    `填写供应商的根地址，通常包含 /v1；无需填写 ${draft.provider === 'openai-chat' ? '/chat/completions' : '/responses'}。`
                                }}</small></label
                            ><label class="settings-toggle settings-wide"
                                ><input
                                    id="model-auth"
                                    v-model="draft.api_key_required"
                                    type="checkbox"
                                />服务需要 API Key</label
                            ><label class="field-label settings-wide" for="model-key"
                                >API Key<input
                                    id="model-key"
                                    v-model="draft.api_key"
                                    type="password"
                                    maxlength="4096"
                                    autocomplete="new-password"
                                    :placeholder="
                                        current?.has_api_key
                                            ? '已配置，留空保留；输入新密钥可替换'
                                            : '不需要认证时可留空'
                                    "
                                /><small class="field-help"
                                    >密钥只保存在本机，不会回传到页面。</small
                                ></label
                            ><label
                                v-if="current?.has_api_key"
                                class="settings-toggle settings-wide"
                                ><input v-model="draft.clear_api_key" type="checkbox" />清除已保存的
                                API Key</label
                            >
                        </div>
                        <details class="settings-advanced">
                            <summary>高级参数</summary>
                            <div class="settings-fields">
                                <label class="field-label" for="model-reasoning"
                                    >思考强度<select
                                        id="model-reasoning"
                                        v-model="draft.reasoning_effort"
                                    >
                                        <option
                                            v-for="(label, value) in reasoningLabels"
                                            :key="value"
                                            :value="value"
                                        >
                                            {{ label }}
                                        </option></select
                                    ><small class="field-help"
                                        >默认不额外指定思考参数；其他档位需模型服务支持。</small
                                    ></label
                                ><label class="field-label" for="model-context"
                                    >上下文长度（Token）<input
                                        id="model-context"
                                        v-model.number="draft.max_context_tokens"
                                        type="number"
                                        min="2048"
                                        max="2097152"
                                        step="1"
                                        required
                                    /><small class="field-help"
                                        >默认
                                        24K（24,576）。包含输入与输出预留，请与服务端实际窗口保持一致。</small
                                    ></label
                                ><label class="field-label" for="model-timeout"
                                    >单次请求超时（秒）<input
                                        id="model-timeout"
                                        v-model.number="draft.timeout_sec"
                                        type="number"
                                        min="1"
                                        max="120"
                                        step="1"
                                        required /></label
                                ><label class="field-label" for="model-retries"
                                    >失败后自动重试次数<input
                                        id="model-retries"
                                        v-model.number="draft.max_retries"
                                        type="number"
                                        min="0"
                                        max="5"
                                        step="1"
                                        required
                                    /><small class="field-help"
                                        >默认 2 次；仅重试当前轮，保留已有搜索与查看结果。</small
                                    ></label
                                ><label class="field-label" for="model-output"
                                    >最大输出 Token<input
                                        id="model-output"
                                        v-model.number="draft.max_output_tokens"
                                        type="number"
                                        min="128"
                                        max="4096"
                                        step="1"
                                        required /></label
                                ><label class="field-label" for="model-temperature"
                                    >Temperature<input
                                        id="model-temperature"
                                        v-model.number="draft.temperature"
                                        type="number"
                                        min="0"
                                        max="2"
                                        step="0.1"
                                        required /></label
                                ><label class="settings-toggle"
                                    ><input
                                        v-model="draft.strict_tool_schema"
                                        type="checkbox"
                                    />严格工具 Schema（Responses）</label
                                ><label class="settings-toggle settings-wide"
                                    ><input
                                        v-model="draft.stream"
                                        type="checkbox"
                                        :disabled="draft.provider !== 'openai-responses'"
                                    />流式接收模型响应（Responses）</label
                                ><small class="field-help settings-wide">{{
                                    draft.provider === 'openai-responses'
                                        ? '实时检测生成和工具参数；完整接收并校验后才执行工具。'
                                        : '当前协议使用完整响应；自动重试仍有效。'
                                }}</small>
                            </div>
                            <p class="field-help">
                                超时按每次无数据等待计算；临时网络错误、限流和服务端故障按以上次数自动重试。搜索中的无效工具调用另有最多
                                2 次协议补正。
                            </p>
                        </details>
                        <SearchBudgetFields v-model="draft.search_limits" />
                        <div class="settings-actions">
                            <button type="button" class="button secondary" @click="test">
                                {{ state.pending === 'test' ? '测试中…' : '测试连接' }}</button
                            ><button type="submit" class="button primary">
                                {{ state.pending === 'save' ? '保存中…' : '保存并生效' }}</button
                            ><button type="button" class="text-button" @click="load">
                                撤销修改
                            </button>
                        </div>
                    </fieldset>
                    <Notice :message="state.feedback" :error="state.error" /><button
                        v-if="state.loadFailed"
                        type="button"
                        class="text-button"
                        @click="load"
                    >
                        重新读取配置
                    </button>
                </form>
            </section>
            <ModelSummary :settings="current" />
        </div>
    </section>
</template>

<script setup lang="ts">
import { usePriceImport } from '../composables/usePriceImport'
import { useDashboard } from '../composables/useDashboard'
import { date } from '../lib/format'
import Icon from '../components/common/Icon.vue'
import Notice from '../components/common/Notice.vue'
const { state, file, example, submit } = usePriceImport(),
    dashboard = useDashboard()
async function readFile(event: Event) {
    const input = event.target as HTMLInputElement
    if (input.files?.[0]) await file(input.files[0])
    input.value = ''
}
</script>
<template>
    <section id="view-data" class="view">
        <div class="data-grid">
            <section class="panel import-panel">
                <div class="panel-heading">
                    <h2>导入价格快照</h2>
                    <span class="tag">JSON</span>
                </div>
                <form class="panel-body" @submit.prevent="submit">
                    <p class="body-copy">
                        为已监控的商品导入所选规格报价。记录观测时间，更新价格历史；出现新的最低价时自动提醒。
                    </p>
                    <label class="field-label" for="import-watch">示例使用的监控</label
                    ><select id="import-watch" v-model="dashboard.state.selected">
                        <option v-if="!dashboard.state.watches.length" :value="null">
                            请先添加监控
                        </option>
                        <option
                            v-for="watch in dashboard.state.watches"
                            :key="watch.id"
                            :value="watch.id"
                        >
                            {{ watch.title }} · {{ Object.values(watch.selections).join(' / ') }}
                        </option></select
                    ><label class="field-label" for="import-json">报价数据</label
                    ><textarea
                        id="import-json"
                        v-model="state.json"
                        class="code-input"
                        rows="14"
                        spellcheck="false"
                        required
                        :disabled="state.pending"
                        placeholder='{"observations": [{"watch_id": "监控 ID", "price": "89.90", "observed_at": "含时区的观测时间"}]}'
                    ></textarea>
                    <div class="import-toolbar">
                        <label class="button secondary file-button"
                            ><input
                                type="file"
                                accept=".json,application/json"
                                :disabled="state.pending"
                                @change="readFile"
                            /><Icon name="upload" />选择文件</label
                        ><button
                            class="text-button"
                            type="button"
                            :disabled="state.pending"
                            @click="example"
                        >
                            填入所选商品示例</button
                        ><button class="button primary" type="submit" :disabled="state.pending">
                            {{ state.pending ? '导入中…' : '导入快照' }}
                        </button>
                    </div>
                    <Notice :message="state.feedback" :error="state.error" />
                </form>
            </section>
            <section class="panel data-notes">
                <div class="panel-heading"><h2>数据来源与更新</h2></div>
                <div class="panel-body">
                    <div class="source-block">
                        <span class="source-number">01</span>
                        <h3>商品目录</h3>
                        <p>
                            {{
                                !dashboard.state.status
                                    ? '正在读取目录来源…'
                                    : dashboard.state.status.catalog_is_demo
                                      ? 'ShopAgent 虚构演示目录'
                                      : '本地导入商品目录'
                            }}
                        </p>
                        <strong
                            >{{
                                dashboard.state.status?.catalog_count.toLocaleString('zh-CN') ?? '—'
                            }}
                            个商品</strong
                        >
                    </div>
                    <div class="source-block">
                        <span class="source-number">02</span>
                        <h3>快照监控</h3>
                        <p>
                            以目录报价建立初始基准，后续导入有明确时间的价格快照。静态目录不会自行产生新价格。
                        </p>
                    </div>
                    <div class="source-block">
                        <span class="source-number">03</span>
                        <h3>模拟监控</h3>
                        <p>
                            事件模拟与固定场景用于体验价格变化和低价提醒。模拟报价单独保存，不会进入快照监控的价格历史。
                        </p>
                    </div>
                    <div class="scope-note">
                        “历史最低”仅指开始采集以来的记录，不代表电商平台全站历史最低价。
                    </div>
                    <p class="quiet-label">
                        后台检查{{
                            dashboard.state.status?.scheduler_enabled ? '已开启' : '已关闭'
                        }}
                        · 最近轮询
                        {{
                            date(dashboard.state.status?.scheduler_last_poll)
                        }}。应用运行期间按每项监控的间隔检查。
                    </p>
                    <p class="field-help">
                        研究阶段的目录来源与 ShopSimulator 说明见项目文档；当前未接入真实电商平台。
                    </p>
                </div>
            </section>
        </div>
    </section>
</template>

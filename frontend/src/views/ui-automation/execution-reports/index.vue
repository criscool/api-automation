<template>
  <AppPage>
    <n-space vertical size="large">
      <n-tabs v-model:value="viewMode" type="segment" @update:value="onViewChange">
        <n-tab-pane name="executions" tab="单次执行" />
        <n-tab-pane name="batches" tab="批次执行" />
      </n-tabs>

      <!-- ============ 顶部筛选 ============ -->
      <n-card size="small" v-if="viewMode === 'executions'">
        <n-space justify="space-between" align="center">
          <n-space>
            <n-input
              v-model:value="filter.script_id"
              placeholder="按脚本 ID 过滤"
              clearable
              style="width: 240px"
              @keyup.enter="loadList"
            >
              <template #prefix>
                <n-icon><Icon icon="mdi:magnify" /></n-icon>
              </template>
            </n-input>
            <n-select
              v-model:value="filter.status"
              placeholder="状态"
              clearable
              :options="statusOptions"
              style="width: 160px"
              @update:value="loadList"
            />
            <n-button @click="loadList">刷新</n-button>
          </n-space>
        </n-space>
      </n-card>

      <n-card size="small" v-if="viewMode === 'batches'">
        <n-space justify="space-between" align="center">
          <n-button @click="loadBatchList">刷新</n-button>
        </n-space>
      </n-card>

      <!-- ============ 单次执行列表 ============ -->
      <n-card v-if="viewMode === 'executions'" title="执行记录" size="small">
        <n-data-table
          remote
          :columns="columns"
          :data="list"
          :pagination="pagination"
          :loading="loading"
          :row-key="(row) => row.execution_id"
          @update:page="onPageChange"
        />
      </n-card>

      <!-- ============ 批次列表 ============ -->
      <n-card v-if="viewMode === 'batches'" title="批次执行" size="small">
        <n-data-table
          remote
          :columns="batchColumns"
          :data="batchList"
          :pagination="batchPagination"
          :loading="batchLoading"
          :row-key="(row) => row.batch_id"
          @update:page="onBatchPageChange"
        />
      </n-card>
    </n-space>

    <!-- ============ 详情抽屉 ============ -->
    <n-drawer v-model:show="detailVisible" :width="980" placement="right">
      <n-drawer-content :title="`执行 ${detail?.execution_id?.slice(0, 12) || ''}`" closable>
        <n-spin :show="detailLoading">
          <n-space v-if="detail" vertical size="large">
            <n-descriptions :column="2" bordered label-placement="left" size="small">
              <n-descriptions-item label="执行ID">{{ detail.execution_id }}</n-descriptions-item>
              <n-descriptions-item label="用例名称">{{ detail.script_name || detail.script_id }}</n-descriptions-item>
              <n-descriptions-item label="状态">
                <n-tag :type="statusToType(detail.status)" size="small">{{ detail.status }}</n-tag>
              </n-descriptions-item>
              <n-descriptions-item label="退出码">{{ detail.exit_code ?? '-' }}</n-descriptions-item>
              <n-descriptions-item label="开始">{{ detail.start_time || '-' }}</n-descriptions-item>
              <n-descriptions-item label="结束">{{ detail.end_time || '-' }}</n-descriptions-item>
              <n-descriptions-item label="耗时">{{ detail.duration_ms ? detail.duration_ms + ' ms' : '-' }}</n-descriptions-item>
              <n-descriptions-item label="触发人">{{ detail.triggered_by || '-' }}</n-descriptions-item>
              <n-descriptions-item v-if="detail.error_message" :span="2" label="错误">
                <span style="color: #e74c3c">{{ detail.error_message }}</span>
              </n-descriptions-item>
            </n-descriptions>

            <!-- 实时执行日志(SSE) -->
            <n-card v-if="liveActive || liveLogs.length" size="small" title="实时执行日志(SSE)">
              <template #header-extra>
                <n-tag :type="liveActive ? 'success' : 'default'" size="small">
                  {{ liveActive ? '订阅中' : '已结束' }}
                </n-tag>
              </template>
              <div class="live-log" ref="liveLogRef">
                <div v-for="(line, idx) in liveLogs" :key="idx" :class="['log-line', line.message_type]">
                  <span class="ts">{{ line.timestamp || '' }}</span>
                  <span class="region">[{{ line.region || 'process' }}]</span>
                  <span class="content">{{ line.content }}</span>
                </div>
                <div v-if="!liveLogs.length" class="empty-log">等待消息...</div>
              </div>
            </n-card>

            <!-- 报告区：Tab 切换 Playwright(默认) / Allure(按需生成) -->
            <n-card v-if="detail.report" size="small" title="测试报告">
              <template #header-extra>
                <n-space size="small">
                  <n-tag size="small" type="success">通过 {{ detail.report.passed }}</n-tag>
                  <n-tag size="small" type="error">失败 {{ detail.report.failed }}</n-tag>
                  <n-tag size="small">跳过 {{ detail.report.skipped }}</n-tag>
                </n-space>
              </template>

              <n-tabs v-model:value="reportTab" type="line" animated>
                <!-- Playwright 原生（默认 Tab）-->
                <n-tab-pane name="playwright" tab="Playwright 详情">
                  <div v-if="detail.report.report_url">
                    <n-space size="small" style="margin-bottom: 8px;">
                      <n-button size="tiny" tag="a" :href="detail.report.report_url" target="_blank">
                        新标签页打开
                      </n-button>
                    </n-space>
                    <iframe
                      :src="detail.report.report_url"
                      class="report-frame"
                      sandbox="allow-scripts allow-same-origin"
                    />
                  </div>
                  <n-empty v-else description="未生成 Playwright 报告" />
                </n-tab-pane>

                <!-- Allure（按需生成）-->
                <n-tab-pane name="allure" tab="Allure">
                  <!-- ready：显示报告 + 新标签页按钮 -->
                  <template v-if="detail.report.allure_status === 'ready' && detail.report.allure_report_url">
                    <n-space size="small" style="margin-bottom: 8px;">
                      <n-button size="tiny" tag="a" :href="detail.report.allure_report_url" target="_blank">
                        新标签页打开
                      </n-button>
                      <n-button size="tiny" :loading="allureTriggering" @click="triggerSingleAllure">
                        重新生成
                      </n-button>
                      <n-text v-if="detail.report.allure_generated_at" depth="3" style="font-size: 12px;">
                        生成于 {{ detail.report.allure_generated_at }}
                      </n-text>
                    </n-space>
                    <iframe
                      :src="detail.report.allure_report_url"
                      class="report-frame"
                      sandbox="allow-scripts allow-same-origin"
                    />
                  </template>

                  <!-- generating：转圈 -->
                  <div v-else-if="detail.report.allure_status === 'generating'" class="allure-empty">
                    <n-spin size="medium" />
                    <n-text depth="3" style="margin-top: 12px;">
                      Allure 报告生成中（最长 3 分钟）…
                    </n-text>
                  </div>

                  <!-- failed：错误 + 重试 -->
                  <div v-else-if="detail.report.allure_status === 'failed'" class="allure-empty">
                    <n-alert type="error" :show-icon="false" style="margin-bottom: 12px; max-width: 480px;">
                      生成失败：{{ detail.report.allure_error || '未知错误' }}
                    </n-alert>
                    <n-button
                      type="primary"
                      :loading="allureTriggering"
                      :disabled="!allureCliAvailable"
                      @click="triggerSingleAllure"
                    >
                      重试
                    </n-button>
                  </div>

                  <!-- not_generated（初始状态）：按钮触发 -->
                  <div v-else class="allure-empty">
                    <n-text depth="3" style="margin-bottom: 12px;">
                      尚未生成 Allure 报告（提供历史趋势、失败聚合、业务分类视图）
                    </n-text>
                    <n-button
                      type="primary"
                      :loading="allureTriggering"
                      :disabled="!allureCliAvailable"
                      @click="triggerSingleAllure"
                    >
                      生成 Allure 报告
                    </n-button>
                    <n-text v-if="!allureCliAvailable" depth="3" style="font-size: 12px; margin-top: 8px;">
                      服务器未安装 Allure CLI
                    </n-text>
                  </div>
                </n-tab-pane>
              </n-tabs>
            </n-card>

            <!-- 产物列表 -->
            <n-card v-if="detail.artifacts?.length" size="small" title="产物清单">
              <n-data-table
                :columns="artifactColumns"
                :data="detail.artifacts"
                :row-key="(r) => r.artifact_id"
                size="small"
              />
            </n-card>

            <!-- stdout/stderr -->
            <n-collapse v-if="detail.stdout || detail.stderr" :default-expanded-names="['stderr']">
              <n-collapse-item v-if="detail.stdout" title="stdout (截断后)" name="stdout">
                <n-input type="textarea" :value="detail.stdout?.slice(-20000)" readonly :autosize="{ minRows: 8, maxRows: 18 }" class="code-area" />
              </n-collapse-item>
              <n-collapse-item v-if="detail.stderr" title="stderr (截断后)" name="stderr">
                <n-input type="textarea" :value="detail.stderr?.slice(-20000)" readonly :autosize="{ minRows: 8, maxRows: 18 }" class="code-area" />
              </n-collapse-item>
            </n-collapse>

            <n-space justify="end">
              <n-button v-if="detail.status === 'running' || detail.status === 'pending'" type="warning" @click="onCancel">
                取消执行
              </n-button>
              <n-button @click="detailVisible = false">关闭</n-button>
            </n-space>
          </n-space>
        </n-spin>
      </n-drawer-content>
    </n-drawer>

    <!-- ============ 批次详情抽屉 ============ -->
    <n-drawer v-model:show="batchDetailVisible" :width="1020" placement="right">
      <n-drawer-content :title="`批次 ${batchDetail?.batch_id?.slice(0, 8) || ''} - ${batchDetail?.name || ''}`" closable>
        <n-spin :show="detailLoading">
          <n-space v-if="batchDetail" vertical size="large">
            <!-- 汇总卡片 -->
            <n-space size="small">
              <n-card size="small" embedded style="flex:1;text-align:center">
                <n-statistic label="脚本总数" :value="batchDetail.total_scripts || 0" />
              </n-card>
              <n-card size="small" embedded style="flex:1;text-align:center">
                <n-statistic label="通过用例" :value="batchDetail.total_passed || 0">
                  <template #suffix><span style="color:#18a058">PASS</span></template>
                </n-statistic>
              </n-card>
              <n-card size="small" embedded style="flex:1;text-align:center">
                <n-statistic label="失败用例" :value="batchDetail.total_failed || 0">
                  <template #suffix><span style="color:#d03050">FAIL</span></template>
                </n-statistic>
              </n-card>
              <n-card size="small" embedded style="flex:1;text-align:center">
                <n-statistic label="跳过" :value="batchDetail.total_skipped || 0" />
              </n-card>
            </n-space>

            <n-descriptions :column="2" bordered label-placement="left" size="small">
              <n-descriptions-item label="状态">
                <n-tag :type="statusToType(batchDetail.status)" size="small">{{ batchDetail.status }}</n-tag>
              </n-descriptions-item>
              <n-descriptions-item label="耗时">{{ batchDetail.duration_ms ? batchDetail.duration_ms + ' ms' : '-' }}</n-descriptions-item>
              <n-descriptions-item label="成功脚本">{{ batchDetail.success_count }}/{{ batchDetail.total_scripts }}</n-descriptions-item>
              <n-descriptions-item label="失败脚本">{{ batchDetail.failed_count || 0 }}</n-descriptions-item>
              <n-descriptions-item label="触发人">{{ batchDetail.triggered_by || '-' }}</n-descriptions-item>
              <n-descriptions-item label="开始时间">{{ batchDetail.start_time || '-' }}</n-descriptions-item>
            </n-descriptions>

            <!-- 批次级 Allure 汇总报告（按需生成）-->
            <n-card size="small" title="批次汇总报告（Allure）">
              <!-- ready：嵌入 iframe -->
              <template v-if="batchDetail.batch_allure_status === 'ready' && batchDetail.batch_allure_report_url">
                <n-space size="small" style="margin-bottom: 8px;">
                  <n-button size="tiny" tag="a" :href="batchDetail.batch_allure_report_url" target="_blank">
                    新标签页打开
                  </n-button>
                  <n-button size="tiny" :loading="batchAllureTriggering" @click="triggerBatchAllure">
                    重新生成
                  </n-button>
                  <n-text v-if="batchDetail.batch_allure_generated_at" depth="3" style="font-size: 12px;">
                    生成于 {{ batchDetail.batch_allure_generated_at }}
                  </n-text>
                </n-space>
                <iframe
                  :src="batchDetail.batch_allure_report_url"
                  class="report-frame"
                  sandbox="allow-scripts allow-same-origin"
                />
              </template>

              <!-- generating -->
              <div v-else-if="batchDetail.batch_allure_status === 'generating'" class="allure-empty">
                <n-spin size="medium" />
                <n-text depth="3" style="margin-top: 12px;">
                  批次汇总报告生成中（最长 3 分钟）…
                </n-text>
              </div>

              <!-- failed -->
              <div v-else-if="batchDetail.batch_allure_status === 'failed'" class="allure-empty">
                <n-alert type="error" :show-icon="false" style="margin-bottom: 12px; max-width: 480px;">
                  生成失败：{{ batchDetail.batch_allure_error || '未知错误' }}
                </n-alert>
                <n-button
                  type="primary"
                  :loading="batchAllureTriggering"
                  :disabled="!allureCliAvailable"
                  @click="triggerBatchAllure"
                >
                  重试
                </n-button>
              </div>

              <!-- not_generated -->
              <div v-else class="allure-empty">
                <n-text depth="3" style="margin-bottom: 12px;">
                  尚未生成。点下方按钮一站式查看 {{ batchDetail.total_scripts || 0 }} 个脚本的合并报告。
                </n-text>
                <n-button
                  type="primary"
                  :loading="batchAllureTriggering"
                  :disabled="!allureCliAvailable"
                  @click="triggerBatchAllure"
                >
                  生成批次汇总
                </n-button>
                <n-text v-if="!allureCliAvailable" depth="3" style="font-size: 12px; margin-top: 8px;">
                  服务器未安装 Allure CLI
                </n-text>
              </div>
            </n-card>

            <!-- 子执行列表 -->
            <n-card size="small" title="脚本执行明细">
              <n-data-table
                :columns="batchExecColumns"
                :data="batchDetail.executions || []"
                :row-key="(r) => r.execution_id"
                size="small"
                :max-height="400"
              />
            </n-card>

            <n-space justify="end">
              <n-button v-if="batchDetail.status === 'running' || batchDetail.status === 'pending'" type="warning" @click="onCancelBatch">
                取消批次
              </n-button>
              <n-button @click="batchDetailVisible = false">关闭</n-button>
            </n-space>
          </n-space>
        </n-spin>
      </n-drawer-content>
    </n-drawer>
  </AppPage>
</template>

<script setup>
import { h, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { NButton, NSpace, NTag } from 'naive-ui'
import api from '@/api'

const route = useRoute()
const router = useRouter()

const statusOptions = [
  { label: 'pending', value: 'pending' },
  { label: 'running', value: 'running' },
  { label: 'success', value: 'success' },
  { label: 'failed', value: 'failed' },
  { label: 'timeout', value: 'timeout' },
  { label: 'cancelled', value: 'cancelled' },
  { label: 'safety_blocked', value: 'safety_blocked' },
  { label: 'error', value: 'error' },
  { label: 'interrupted', value: 'interrupted' },
]

function statusToType(s) {
  if (s === 'success') return 'success'
  if (s === 'failed' || s === 'error' || s === 'safety_blocked') return 'error'
  if (s === 'timeout' || s === 'cancelled' || s === 'interrupted') return 'warning'
  if (s === 'running' || s === 'pending') return 'info'
  return 'default'
}

// ----------------------------------------------------------------------------
// 列表
// ----------------------------------------------------------------------------
const list = ref([])
const loading = ref(false)
const filter = ref({ script_id: '', status: null })
const pagination = ref({ page: 1, pageSize: 10, itemCount: 0, showSizePicker: false })

const columns = [
  { title: '执行ID', key: 'execution_id', width: 220, ellipsis: { tooltip: true } },
  { title: '用例名称', key: 'script_name', width: 220, ellipsis: { tooltip: true },
    render: (row) => row.script_name || row.script_id || '-' },
  {
    title: '状态',
    key: 'status',
    width: 130,
    render: (row) => h(NTag, { type: statusToType(row.status), size: 'small' }, () => row.status),
  },
  { title: '退出码', key: 'exit_code', width: 80 },
  {
    title: '耗时(ms)',
    key: 'duration_ms',
    width: 100,
    render: (row) => row.duration_ms || '-',
  },
  { title: '触发人', key: 'triggered_by', width: 100 },
  { title: '开始时间', key: 'start_time', width: 170 },
  {
    title: '操作',
    key: 'actions',
    width: 150,
    render: (row) => h(NSpace, { size: 'small' }, () => [
      h(NButton, {
        size: 'tiny',
        onClick: () => openDetail(row.execution_id),
      }, () => '详情'),
      (row.status === 'running' || row.status === 'pending')
        ? h(NButton, {
            size: 'tiny',
            type: 'warning',
            onClick: () => cancelById(row.execution_id),
          }, () => '取消')
        : null,
    ].filter(Boolean)),
  },
]

// ----------------------------------------------------------------------------
// 批次视图
// ----------------------------------------------------------------------------
const viewMode = ref('executions')
const batchList = ref([])
const batchLoading = ref(false)
const batchPagination = ref({ page: 1, pageSize: 10, itemCount: 0, showSizePicker: false })
const batchDetailVisible = ref(false)
const batchDetail = ref(null)

const batchColumns = [
  { title: 'batch_id', key: 'batch_id', width: 220, ellipsis: { tooltip: true } },
  { title: '名称', key: 'name', width: 200, ellipsis: { tooltip: true } },
  {
    title: '状态',
    key: 'status',
    width: 120,
    render: (row) => h(NTag, { type: statusToType(row.status), size: 'small' }, () => row.status),
  },
  {
    title: '进度',
    key: 'progress',
    width: 130,
    render: (row) => `${row.success_count || 0}/${row.total_scripts || 0}`,
  },
  { title: '失败', key: 'failed_count', width: 60 },
  { title: '超时', key: 'timeout_count', width: 60 },
  {
    title: '耗时(ms)',
    key: 'duration_ms',
    width: 100,
    render: (row) => row.duration_ms || '-',
  },
  { title: '触发人', key: 'triggered_by', width: 100 },
  { title: '创建时间', key: 'created_at', width: 170 },
  {
    title: '操作',
    key: 'actions',
    width: 200,
    render: (row) => h(NSpace, { size: 'small' }, () => [
      h(NButton, { size: 'tiny', onClick: () => openBatchDetail(row.batch_id) }, () => '详情'),
      (row.status === 'running' || row.status === 'pending')
        ? h(NButton, { size: 'tiny', type: 'warning', onClick: () => cancelBatch(row.batch_id) }, () => '取消')
        : null,
    ].filter(Boolean)),
  },
]

async function loadBatchList() {
  batchLoading.value = true
  try {
    const res = await api.uiListBatches({
      page: batchPagination.value.page,
      page_size: batchPagination.value.pageSize,
    })
    const data = res?.data ?? res
    batchList.value = data.items || []
    batchPagination.value.itemCount = data.total || 0
  } catch (e) {
    window.$message?.error('加载失败：' + (e?.message || e))
  } finally {
    batchLoading.value = false
  }
}

function onBatchPageChange(page) {
  batchPagination.value.page = page
  loadBatchList()
}

function onViewChange(mode) {
  if (mode === 'executions') loadList()
  else loadBatchList()
}

async function openBatchDetail(batchId) {
  detailLoading.value = true
  batchDetailVisible.value = true
  if (batchAllurePollTimer) { clearInterval(batchAllurePollTimer); batchAllurePollTimer = null }
  try {
    const res = await api.uiGetBatch(batchId)
    batchDetail.value = res?.data ?? res
    // 上次离开时还在 generating，继续轮询
    if (batchDetail.value?.batch_allure_status === 'generating') {
      startBatchAllurePoll()
    }
  } catch (e) {
    window.$message?.error('加载失败：' + (e?.message || e))
  } finally {
    detailLoading.value = false
  }
}

const batchExecColumns = [
  { title: '用例名称', key: 'script_name', width: 220, ellipsis: { tooltip: true },
    render: (row) => row.script_name || row.script_id || '-' },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (row) => h(NTag, { type: statusToType(row.status), size: 'small' }, () => row.status),
  },
  {
    title: '通过',
    key: 'report.passed',
    width: 60,
    render: (row) => row.report?.passed ?? '-',
  },
  {
    title: '失败',
    key: 'report.failed',
    width: 60,
    render: (row) => row.report?.failed ?? '-',
  },
  {
    title: '跳过',
    key: 'report.skipped',
    width: 60,
    render: (row) => row.report?.skipped ?? '-',
  },
  {
    title: '耗时(ms)',
    key: 'duration_ms',
    width: 90,
    render: (row) => row.duration_ms || '-',
  },
  {
    title: '报告',
    key: 'report_url',
    width: 80,
    render: (row) => row.report?.report_url
      ? h(NButton, { size: 'tiny', tag: 'a', href: row.report.report_url, target: '_blank' }, () => '打开')
      : '-',
  },
  { title: '错误', key: 'error_message', ellipsis: { tooltip: true }, width: 160 },
]

async function cancelBatch(batchId) {
  window.$dialog?.warning({
    title: '确认取消',
    content: `取消批次 ${batchId}？未开始的脚本将跳过，正在跑的会被终止。`,
    positiveText: '取消批次',
    negativeText: '返回',
    onPositiveClick: async () => {
      try {
        await api.uiCancelBatch(batchId)
        window.$message?.success('已取消')
        loadBatchList()
      } catch (e) {
        window.$message?.error('取消失败：' + (e?.message || e))
      }
    },
  })
}

function onCancelBatch() {
  if (!batchDetail.value?.batch_id) return
  cancelBatch(batchDetail.value.batch_id)
}

// 从 query.batch_id 自动打开批次详情，定时轮询进度
async function autoOpenBatchFromQuery() {
  const batchId = route.query.batch_id
  if (!batchId) return

  viewMode.value = 'batches'
  await openBatchDetail(batchId)
  // 清理 query
  if (window.history?.replaceState) {
    window.history.replaceState({}, '', route.path)
  }
  // 定时轮询批次进度
  batchPollTimer = setInterval(async () => {
    try {
      const res = await api.uiGetBatch(batchId)
      batchDetail.value = res?.data ?? res
      if (batchDetail.value?.status && !['running', 'pending'].includes(batchDetail.value.status)) {
        clearInterval(batchPollTimer)
        batchPollTimer = null
        loadBatchList()
      }
    } catch { /* 静默 */ }
  }, 3000)
}


const artifactColumns = [
  { title: '类型', key: 'artifact_type', width: 120 },
  {
    title: 'URL',
    key: 'file_url',
    ellipsis: { tooltip: true },
    render: (row) => h('a', { href: row.file_url, target: '_blank', rel: 'noopener noreferrer' }, row.file_url),
  },
  {
    title: '大小',
    key: 'file_size',
    width: 100,
    render: (row) => formatSize(row.file_size),
  },
  { title: '过期时间', key: 'expires_at', width: 170 },
]

function formatSize(s) {
  if (!s) return '-'
  if (s < 1024) return `${s} B`
  if (s < 1024 * 1024) return `${(s / 1024).toFixed(1)} KB`
  return `${(s / 1024 / 1024).toFixed(1)} MB`
}

async function loadList() {
  loading.value = true
  try {
    const res = await api.uiListExecutions({
      page: pagination.value.page,
      page_size: pagination.value.pageSize,
      script_id: filter.value.script_id || undefined,
      status: filter.value.status || undefined,
    })
    const data = res?.data ?? res
    list.value = data.items || []
    pagination.value.itemCount = data.total || 0
  } catch (e) {
    window.$message?.error('加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function onPageChange(page) {
  pagination.value.page = page
  loadList()
}

async function cancelById(executionId) {
  try {
    await api.uiCancelExecution(executionId)
    window.$message?.success('已发送取消信号')
    loadList()
  } catch (e) {
    window.$message?.error('取消失败：' + (e?.message || e))
  }
}

// ----------------------------------------------------------------------------
// 详情 + SSE
// ----------------------------------------------------------------------------
const detailVisible = ref(false)
const detail = ref(null)
const detailLoading = ref(false)
const liveLogs = ref([])
const liveActive = ref(false)
const liveLogRef = ref(null)
let sse = null
let detailRefreshTimer = null
let batchPollTimer = null

// ----------------------------------------------------------------------------
// Allure 按需生成（单脚本 + 批次）
// ----------------------------------------------------------------------------
const reportTab = ref('playwright')               // 'playwright' | 'allure'
const allureCliAvailable = ref(true)              // 进页面查一次，决定按钮 disabled
const allureTriggering = ref(false)               // 单脚本「触发中」loading
const batchAllureTriggering = ref(false)          // 批次「触发中」loading
let allurePollTimer = null                        // 单脚本 status 轮询
let batchAllurePollTimer = null                   // 批次 status 轮询

async function fetchAllureCliStatus() {
  try {
    const res = await api.uiGetAllureCliStatus()
    const data = res?.data ?? res
    allureCliAvailable.value = !!data?.available
  } catch {
    allureCliAvailable.value = false
  }
}

async function triggerSingleAllure() {
  if (!detail.value?.execution_id) return
  allureTriggering.value = true
  try {
    await api.uiTriggerSingleAllure(detail.value.execution_id)
    // 立即把本地状态改成 generating，UI 同步刷新
    if (detail.value.report) {
      detail.value.report.allure_status = 'generating'
      detail.value.report.allure_error = ''
    }
    startAllurePoll()
  } catch (e) {
    window.$message?.error('触发失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    allureTriggering.value = false
  }
}

function startAllurePoll() {
  if (allurePollTimer) clearInterval(allurePollTimer)
  allurePollTimer = setInterval(async () => {
    if (!detail.value?.execution_id) {
      clearInterval(allurePollTimer)
      allurePollTimer = null
      return
    }
    try {
      const res = await api.uiGetExecution(detail.value.execution_id)
      const data = res?.data ?? res
      if (data?.report) {
        // 只更新 allure 相关字段，避免覆盖其他正在变化的字段
        detail.value.report.allure_status = data.report.allure_status
        detail.value.report.allure_report_url = data.report.allure_report_url
        detail.value.report.allure_generated_at = data.report.allure_generated_at
        detail.value.report.allure_error = data.report.allure_error
        if (data.report.allure_status === 'ready' || data.report.allure_status === 'failed') {
          clearInterval(allurePollTimer)
          allurePollTimer = null
          if (data.report.allure_status === 'ready') {
            reportTab.value = 'allure'   // 成功后自动切到 Allure Tab 展示
          }
        }
      }
    } catch {
      // 网络抖动忽略，下次轮询会重试
    }
  }, 3000)
}

async function triggerBatchAllure() {
  if (!batchDetail.value?.batch_id) return
  batchAllureTriggering.value = true
  try {
    await api.uiTriggerBatchAllure(batchDetail.value.batch_id)
    batchDetail.value.batch_allure_status = 'generating'
    batchDetail.value.batch_allure_error = ''
    startBatchAllurePoll()
  } catch (e) {
    window.$message?.error('触发失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    batchAllureTriggering.value = false
  }
}

function startBatchAllurePoll() {
  if (batchAllurePollTimer) clearInterval(batchAllurePollTimer)
  batchAllurePollTimer = setInterval(async () => {
    if (!batchDetail.value?.batch_id) {
      clearInterval(batchAllurePollTimer)
      batchAllurePollTimer = null
      return
    }
    try {
      const res = await api.uiGetBatch(batchDetail.value.batch_id)
      const data = res?.data ?? res
      if (data) {
        batchDetail.value.batch_allure_status = data.batch_allure_status
        batchDetail.value.batch_allure_report_url = data.batch_allure_report_url
        batchDetail.value.batch_allure_generated_at = data.batch_allure_generated_at
        batchDetail.value.batch_allure_error = data.batch_allure_error
        if (data.batch_allure_status === 'ready' || data.batch_allure_status === 'failed') {
          clearInterval(batchAllurePollTimer)
          batchAllurePollTimer = null
        }
      }
    } catch {
      // 忽略
    }
  }, 3000)
}

async function openDetail(executionId, sessionId) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  closeSse()
  liveLogs.value = []
  reportTab.value = 'playwright'           // 每次打开默认 Playwright Tab
  if (allurePollTimer) { clearInterval(allurePollTimer); allurePollTimer = null }
  try {
    const res = await api.uiGetExecution(executionId)
    detail.value = res?.data ?? res

    // 仍在运行 → 订阅 SSE + 定时刷新详情(报告/产物在终态时才落库)
    if (
      sessionId
      || detail.value?.status === 'running'
      || detail.value?.status === 'pending'
    ) {
      startSse(executionId, sessionId)
      detailRefreshTimer = setInterval(() => refreshDetailQuietly(executionId), 5000)
    }

    // 如果上次离开时正好处于 generating 状态，继续轮询直到结束
    if (detail.value?.report?.allure_status === 'generating') {
      startAllurePoll()
    }
  } catch (e) {
    window.$message?.error('加载失败：' + (e?.message || e))
  } finally {
    detailLoading.value = false
  }
}

async function refreshDetailQuietly(executionId) {
  try {
    const res = await api.uiGetExecution(executionId)
    detail.value = res?.data ?? res
    if (detail.value?.status && !['running', 'pending'].includes(detail.value.status)) {
      stopDetailRefresh()
      loadList()
    }
  } catch {
    /* 静默 */
  }
}

function stopDetailRefresh() {
  if (detailRefreshTimer) {
    clearInterval(detailRefreshTimer)
    detailRefreshTimer = null
  }
}

function startSse(executionId, sessionId) {
  // 没有 sessionId 也允许订阅,但拿不到该执行专属事件 —— 必须由后端在事件里带 session_id 过滤
  if (!sessionId) return
  try {
    const url = api.uiExecutionStreamUrl(executionId, sessionId)
    sse = new EventSource(url)
    liveActive.value = true
    sse.addEventListener('message', (e) => {
      try {
        const payload = JSON.parse(e.data)
        liveLogs.value.push(payload)
        if (liveLogs.value.length > 500) {
          liveLogs.value.splice(0, liveLogs.value.length - 500)
        }
        nextTick(() => {
          const el = liveLogRef.value
          if (el) el.scrollTop = el.scrollHeight
        })
        if (payload?.is_final) {
          liveActive.value = false
          closeSse()
        }
      } catch {
        /* ignore parse error */
      }
    })
    sse.addEventListener('ready', () => {
      liveLogs.value.push({ content: 'SSE 已连接,等待执行进度...', region: 'system', message_type: 'info' })
    })
    sse.onerror = () => {
      liveActive.value = false
    }
  } catch (e) {
    window.$message?.warning('SSE 订阅失败:' + e.message)
  }
}

function closeSse() {
  if (sse) {
    try { sse.close() } catch { /* ignore */ }
    sse = null
  }
  liveActive.value = false
}

async function onCancel() {
  if (!detail.value) return
  await cancelById(detail.value.execution_id)
}

watch(detailVisible, (val) => {
  if (!val) {
    closeSse()
    stopDetailRefresh()
  }
})

onUnmounted(() => {
  closeSse()
  stopDetailRefresh()
  if (allurePollTimer) {
    clearInterval(allurePollTimer)
    allurePollTimer = null
  }
  if (batchAllurePollTimer) {
    clearInterval(batchAllurePollTimer)
    batchAllurePollTimer = null
  }
})

// ----------------------------------------------------------------------------
// 入参带 execution_id → 直接打开抽屉(从脚本管理"运行"按钮跳过来)
// ----------------------------------------------------------------------------
function consumeQuery() {
  const eid = route.query.execution_id
  const sid = route.query.session_id
  if (!eid) return
  if (window.history?.replaceState) {
    window.history.replaceState({}, '', route.path)
  }
  openDetail(String(eid), sid ? String(sid) : '')
}

watch(() => route.query.execution_id, (val) => {
  if (val) consumeQuery()
})

onMounted(() => {
  loadList()
  consumeQuery()
  autoOpenBatchFromQuery()
  fetchAllureCliStatus()       // 查 Allure CLI 是否可用，决定按钮 disabled
})
</script>

<style scoped>
.live-log {
  max-height: 320px;
  overflow-y: auto;
  background: #1e1e1e;
  color: #d4d4d4;
  font-family: 'Fira Code', 'Cascadia Code', Consolas, monospace;
  font-size: 12px;
  padding: 8px 12px;
  border-radius: 4px;
  line-height: 1.6;
}
.log-line {
  white-space: pre-wrap;
  word-break: break-all;
}
.log-line.error { color: #f48771; }
.log-line.warning { color: #dcdcaa; }
.log-line.success { color: #b5cea8; }
.log-line .ts { color: #6a9955; margin-right: 8px; }
.log-line .region { color: #569cd6; margin-right: 8px; }
.empty-log { color: #6a6a6a; }
.report-frame {
  width: 100%;
  height: 480px;
  border: 1px solid #ddd;
  border-radius: 4px;
}
.allure-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 16px;
  text-align: center;
}
.code-area :deep(textarea) {
  font-family: 'Fira Code', 'Cascadia Code', Consolas, monospace;
  font-size: 12px;
}
</style>

<template>
  <div class="execution-reports">
    <!-- 页面头部 -->
    <n-card title="执行报告" class="mb-6">
      <template #header-extra>
        <n-space>
          <n-button type="primary" @click="showStatisticsModal = true">
            <template #icon>
              <n-icon><Icon icon="mdi:chart-line" /></n-icon>
            </template>
            统计分析
          </n-button>
          <n-button @click="loadReports">
            <template #icon>
              <n-icon><Icon icon="mdi:refresh" /></n-icon>
            </template>
            刷新
          </n-button>
        </n-space>
      </template>

      <!-- 筛选条件 -->
      <div class="grid grid-cols-1 md:grid-cols-6 gap-4 mb-4">
        <n-select
          v-model:value="filters.status"
          :options="statusOptions"
          placeholder="执行状态"
          clearable
          @update:value="loadReports"
        />
        <n-select
          v-model:value="filters.environment"
          :options="environmentOptions"
          placeholder="执行环境"
          clearable
          @update:value="loadReports"
        />
        <n-date-picker
          v-model:value="filters.dateRange"
          type="datetimerange"
          placeholder="执行时间"
          @update:value="loadReports"
        />
        <n-select
          v-model:value="filters.documentId"
          :options="documentOptions"
          placeholder="选择文档"
          clearable
          filterable
          @update:value="loadReports"
        />
        <n-input
          v-model:value="filters.keyword"
          placeholder="搜索执行ID、会话ID..."
          clearable
          @keyup.enter="loadReports"
        />
        <n-button type="primary" @click="loadReports">搜索</n-button>
      </div>
    </n-card>

    <!-- 执行报告列表 -->
    <n-card title="报告列表" class="list-card">
      <template #header-extra>
        <n-space>
          <n-button 
            v-if="selectedRowKeys.length > 0"
            type="error"
            @click="batchDelete"
            :loading="batchDeleting"
          >
            批量删除 ({{ selectedRowKeys.length }})
          </n-button>
          <n-button 
            v-if="selectedRowKeys.length > 1"
            type="info"
            @click="compareReports"
          >
            对比报告
          </n-button>
        </n-space>
      </template>

      <n-data-table
        class="list-table"
        :flex-height="true"
        :columns="reportColumns"
        :data="reports"
        :loading="loading"
        :row-key="row => row.executionId"
        v-model:checked-row-keys="selectedRowKeys"
      />

      <div class="pagination-wrapper">
        <n-pagination
          v-model:page="pagination.page"
          v-model:page-size="pagination.pageSize"
          :item-count="pagination.itemCount"
          :page-sizes="pagination.pageSizes"
          :page-slot="7"
          show-size-picker
          show-quick-jumper
          @update:page="handlePageChange"
          @update:page-size="handlePageSizeChange"
        >
          <template #prefix="{ itemCount }">
            <div class="pagination-prefix">
              <span class="total-text">共 {{ itemCount }} 条</span>
              <n-button
                size="tiny"
                :disabled="pagination.page === 1"
                @click="goFirst"
              >
                <template #icon>
                  <n-icon><Icon icon="mdi:page-first" /></n-icon>
                </template>
                首页
              </n-button>
            </div>
          </template>
          <template #suffix>
            <n-button
              size="tiny"
              :disabled="pagination.page >= totalPages"
              @click="goLast"
            >
              尾页
              <template #icon>
                <n-icon><Icon icon="mdi:page-last" /></n-icon>
              </template>
            </n-button>
          </template>
        </n-pagination>
      </div>
    </n-card>

    <!-- 统计分析模态框 -->
    <n-modal v-model:show="showStatisticsModal" preset="card" title="执行统计分析" style="width: 80%">
      <div v-if="statistics">
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <n-statistic label="总执行次数" :value="statistics.totalExecutions" />
          <n-statistic label="成功执行" :value="statistics.successfulExecutions" />
          <n-statistic label="失败执行" :value="statistics.failedExecutions" />
          <n-statistic label="平均成功率" :value="`${statistics.avgSuccessRate.toFixed(1)}%`" />
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <n-statistic label="总测试数" :value="statistics.totalTests" />
          <n-statistic label="总通过数" :value="statistics.totalPassed" />
          <n-statistic label="总失败数" :value="statistics.totalFailed" />
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <n-statistic label="平均执行时间" :value="`${statistics.avgExecutionTime.toFixed(2)}s`" />
          <n-statistic label="总体成功率" :value="`${((statistics.totalPassed / statistics.totalTests) * 100).toFixed(1)}%`" />
        </div>

        <!-- 图表占位 -->
        <div class="mt-6 border border-dashed border-gray-300 rounded-lg p-8 text-center text-gray-500">
          <n-icon size="48"><Icon icon="mdi:chart-pie" /></n-icon>
          <div class="mt-2">统计图表功能开发中...</div>
        </div>
      </div>
    </n-modal>

    <!-- 报告详情模态框 -->
    <n-modal v-model:show="showDetailModal" preset="card" title="执行报告详情" style="width: 95%; height: 90%">
      <div v-if="selectedReport" class="report-detail">
        <!-- 基本信息 -->
        <div class="grid grid-cols-1 md:grid-cols-6 gap-4 mb-6">
          <n-statistic label="总测试数" :value="selectedReport.totalTests" />
          <n-statistic label="通过测试" :value="selectedReport.passedTests" />
          <n-statistic label="失败测试" :value="selectedReport.failedTests" />
          <n-statistic label="跳过测试" :value="selectedReport.skippedTests" />
          <n-statistic label="成功率" :value="`${selectedReport.successRate}%`" />
          <n-statistic label="执行时间" :value="`${selectedReport.executionTime}s`" />
        </div>

        <n-tabs type="line" v-model:value="detailTab">
          <n-tab-pane name="overview" tab="概览">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <h4 class="font-semibold mb-3">执行信息</h4>
                <n-descriptions :column="1" bordered>
                  <n-descriptions-item label="执行ID">{{ selectedReport.executionId }}</n-descriptions-item>
                  <n-descriptions-item label="会话ID">{{ selectedReport.sessionId }}</n-descriptions-item>
                  <n-descriptions-item label="文档名称">{{ selectedReport.documentName }}</n-descriptions-item>
                  <n-descriptions-item label="执行环境">{{ selectedReport.environment }}</n-descriptions-item>
                  <n-descriptions-item label="执行状态">
                    <n-tag :type="getStatusType(selectedReport.status)">{{ getStatusText(selectedReport.status) }}</n-tag>
                  </n-descriptions-item>
                  <n-descriptions-item label="开始时间">{{ formatTime(selectedReport.startTime) }}</n-descriptions-item>
                  <n-descriptions-item label="结束时间">{{ formatTime(selectedReport.endTime) }}</n-descriptions-item>
                  <n-descriptions-item label="并行执行">{{ selectedReport.parallel ? '是' : '否' }}</n-descriptions-item>
                  <n-descriptions-item label="最大工作线程">{{ selectedReport.maxWorkers }}</n-descriptions-item>
                </n-descriptions>
              </div>
              
              <div>
                <h4 class="font-semibold mb-3">性能统计</h4>
                <n-descriptions :column="1" bordered>
                  <n-descriptions-item label="平均响应时间">{{ selectedReport.avgResponseTime }}ms</n-descriptions-item>
                  <n-descriptions-item label="最大响应时间">{{ selectedReport.maxResponseTime }}ms</n-descriptions-item>
                  <n-descriptions-item label="最小响应时间">{{ selectedReport.minResponseTime }}ms</n-descriptions-item>
                </n-descriptions>
                
                <h4 class="font-semibold mb-3 mt-4">执行描述</h4>
                <div class="bg-gray-50 p-3 rounded">
                  {{ selectedReport.description || '无描述' }}
                </div>
              </div>
            </div>
          </n-tab-pane>
          
          <n-tab-pane name="scripts" tab="脚本结果">
            <n-data-table
              :columns="scriptResultColumns"
              :data="selectedReport.scriptResults"
              :pagination="{ pageSize: 10 }"
              max-height="400"
            />
          </n-tab-pane>
          
          <n-tab-pane name="reports" tab="报告文件">
            <div v-if="selectedReport.reportFiles && selectedReport.reportFiles.length">
              <n-list>
                <n-list-item v-for="report in selectedReport.reportFiles" :key="report.path">
                  <div class="flex items-center justify-between w-full">
                    <div>
                      <div class="font-medium">{{ report.name }}</div>
                      <div class="text-sm text-gray-500">
                        {{ report.format.toUpperCase() }} • {{ formatFileSize(report.size) }} • {{ formatTime(report.createdAt) }}
                      </div>
                    </div>
                    <n-space>
                      <n-button size="small" @click="previewReport(report)">预览</n-button>
                      <n-button size="small" type="primary" @click="downloadReport(report)">下载</n-button>
                    </n-space>
                  </div>
                </n-list-item>
              </n-list>
            </div>
            <n-empty v-else description="暂无报告文件" />
          </n-tab-pane>
          
          <n-tab-pane name="logs" tab="执行日志">
            <div class="mb-4">
              <n-button @click="loadExecutionLogs" :loading="logsLoading">刷新日志</n-button>
            </div>
            <div class="bg-black text-green-400 p-4 rounded font-mono text-sm h-96 overflow-y-auto">
              <div v-for="(log, index) in executionLogs" :key="index" class="mb-1">
                <span class="text-gray-500">[{{ formatTime(log.timestamp) }}]</span>
                <span :class="getLogLevelClass(log.level)">[{{ log.level }}]</span>
                <span>{{ log.message }}</span>
              </div>
              <div v-if="executionLogs.length === 0" class="text-center text-gray-500">
                暂无日志数据
              </div>
            </div>
          </n-tab-pane>
          
          <n-tab-pane name="errors" tab="错误详情" v-if="selectedReport.errorDetails && selectedReport.errorDetails.length">
            <div v-for="(error, index) in selectedReport.errorDetails" :key="index" class="mb-4">
              <n-alert type="error" :title="`错误 ${index + 1}`">
                <div><strong>类型:</strong> {{ error.type || 'Unknown' }}</div>
                <div><strong>消息:</strong> {{ error.message || 'N/A' }}</div>
                <div><strong>时间:</strong> {{ error.timestamp || 'N/A' }}</div>
                <div v-if="error.stack"><strong>堆栈:</strong> <pre class="mt-2 text-xs">{{ error.stack }}</pre></div>
              </n-alert>
            </div>
          </n-tab-pane>
        </n-tabs>
      </div>

      <template #footer>
        <div class="flex justify-between">
          <n-space>
            <n-button @click="generateReport" :loading="generatingReport">
              重新生成报告
            </n-button>
            <n-button @click="shareReport">
              分享报告
            </n-button>
            <n-button @click="exportReport">
              导出报告
            </n-button>
          </n-space>
          <n-button @click="showDetailModal = false">关闭</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 报告预览模态框 -->
    <n-modal v-model:show="showPreviewModal" preset="card" title="报告预览" style="width: 95%; height: 90%">
      <div class="report-preview">
        <!-- 优先：iframe 走 src 模式，给 Allure 这种 SPA 静态站点用 -->
        <iframe
          v-if="previewSrc"
          :src="previewSrc"
          class="w-full h-full border-0"
          style="height: 75vh"
        />
        <!-- 降级：拉来的 HTML 内容用 srcdoc 渲染 -->
        <iframe
          v-else-if="previewContent && previewType === 'html'"
          :srcdoc="previewContent"
          class="w-full h-full border-0"
          style="height: 75vh"
        />
        <!-- 文本格式（json/xml/log）用代码块展示 -->
        <n-code
          v-else-if="previewContent"
          :code="previewContent"
          :language="previewType"
          show-line-numbers
          style="height: 75vh; overflow: auto"
        />
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, onMounted, h } from 'vue'
import { Icon } from '@iconify/vue'
import { NButton, NTag, useMessage, useDialog } from 'naive-ui'
import { 
  getExecutionReports, 
  getExecutionReportDetail, 
  getExecutionStatistics,
  getExecutionLogs,
  deleteExecutionReport,
  batchDeleteExecutionReports,
  generateExecutionReport,
  shareExecutionReport,
  exportExecutionReport,
  previewReportFile,
  getReportDownloadUrl
} from '@/api/execution-reports'
import { formatTime, formatFileSize } from '@/utils'

const message = useMessage()
const dialog = useDialog()

// 数据
const reports = ref([])
const statistics = ref(null)
const selectedReport = ref(null)
const executionLogs = ref([])
const previewContent = ref('')
const previewType = ref('html')
const previewSrc = ref('')

// 状态
const loading = ref(false)
const logsLoading = ref(false)
const generatingReport = ref(false)
const batchDeleting = ref(false)

// 模态框状态
const showStatisticsModal = ref(false)
const showDetailModal = ref(false)
const showPreviewModal = ref(false)
const detailTab = ref('overview')

// 选择状态
const selectedRowKeys = ref([])

// 筛选条件
const filters = ref({
  status: '',
  environment: '',
  dateRange: null,
  documentId: null,
  keyword: ''
})

// 分页
const pagination = ref({
  page: 1,
  pageSize: 20,
  itemCount: 0,
  showSizePicker: true,
  pageSizes: [10, 20, 50, 100]
})

// 总页数，用于禁用尾页按钮
const totalPages = computed(() => {
  const ps = pagination.value.pageSize || 1
  return Math.max(1, Math.ceil((pagination.value.itemCount || 0) / ps))
})

// 选项数据
const statusOptions = [
  { label: '全部', value: '' },
  { label: '等待中', value: 'PENDING' },
  { label: '处理中', value: 'PROCESSING' },
  { label: '已完成', value: 'COMPLETED' },
  { label: '已失败', value: 'FAILED' },
  { label: '已取消', value: 'CANCELLED' }
]

const environmentOptions = [
  { label: '全部', value: '' },
  { label: '测试环境', value: 'test' },
  { label: '预发布环境', value: 'staging' },
  { label: '生产环境', value: 'production' }
]

const documentOptions = ref([
  { label: '全部文档', value: null }
])

// 表格列定义
const reportColumns = [
  { type: 'selection' },
  { title: '执行ID', key: 'executionId', width: 150, ellipsis: true },
  { title: '文档名称', key: 'documentName', width: 150, ellipsis: true },
  { title: '环境', key: 'environment', width: 100 },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (row) => {
      return h(NTag, { type: getStatusType(row.status) }, { default: () => getStatusText(row.status) })
    }
  },
  { title: '总测试', key: 'totalTests', width: 80 },
  { title: '通过', key: 'passedTests', width: 80 },
  { title: '失败', key: 'failedTests', width: 80 },
  { title: '成功率', key: 'successRate', width: 100, render: (row) => `${row.successRate}%` },
  { title: '执行时间', key: 'executionTime', width: 100, render: (row) => `${row.executionTime}s` },
  { title: '创建时间', key: 'createdAt', width: 150, render: (row) => formatTime(row.createdAt) },
  {
    title: '操作',
    key: 'actions',
    width: 200,
    render: (row) => [
      h(NButton,
        {
          size: 'small',
          type: 'primary',
          onClick: () => viewReportDetail(row.executionId)
        },
        { default: () => '详情' }
      ),
      h(NButton,
        {
          size: 'small',
          type: 'info',
          style: 'margin-left: 8px',
          onClick: () => quickPreview(row.executionId)
        },
        { default: () => '预览' }
      ),
      h(NButton,
        {
          size: 'small',
          type: 'error',
          style: 'margin-left: 8px',
          onClick: () => deleteReport(row.executionId)
        },
        { default: () => '删除' }
      )
    ]
  }
]

const scriptResultColumns = [
  { title: '脚本名称', key: 'scriptName', width: 200, ellipsis: true },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (row) => {
      return h(NTag, { type: getStatusType(row.status) }, { default: () => getStatusText(row.status) })
    }
  },
  { title: '总测试', key: 'totalTests', width: 80 },
  { title: '通过', key: 'passedTests', width: 80 },
  { title: '失败', key: 'failedTests', width: 80 },
  { title: '跳过', key: 'skippedTests', width: 80 },
  { title: '成功率', key: 'successRate', width: 100, render: (row) => `${row.successRate.toFixed(1)}%` },
  { title: '执行时间', key: 'duration', width: 100, render: (row) => `${row.duration}s` },
  { title: '响应时间', key: 'responseTime', width: 100, render: (row) => `${row.responseTime}ms` },
  { title: '错误信息', key: 'errorMessage', ellipsis: true }
]

// 方法
const loadReports = async () => {
  loading.value = true
  try {
    const params = {
      page: pagination.value.page,
      page_size: pagination.value.pageSize,
      ...filters.value
    }

    if (filters.value.dateRange) {
      params.start_time = filters.value.dateRange[0]
      params.end_time = filters.value.dateRange[1]
    }

    const response = await getExecutionReports(params)
    if (response.success) {
      // 后端字段是 snake_case，前端列定义用的是 camelCase，做一次映射
      reports.value = (response.data.items || []).map(item => ({
        ...item,
        executionId: item.execution_id,
        sessionId: item.session_id,
        documentId: item.document_id,
        documentName: item.document_name,
        totalTests: item.total_tests,
        passedTests: item.passed_tests,
        failedTests: item.failed_tests,
        successRate: item.success_rate,
        executionTime: item.execution_time,
        startTime: item.start_time,
        endTime: item.end_time,
        createdAt: item.created_at,
      }))
      pagination.value.itemCount = response.data.total
      // 删除最后一页最后一条后自动跳回上一页
      if (reports.value.length === 0 && pagination.value.itemCount > 0) {
        const maxPage = Math.ceil(pagination.value.itemCount / pagination.value.pageSize)
        pagination.value.page = Math.min(pagination.value.page, maxPage)
        return loadReports()
      }
    }
  } catch (error) {
    message.error('加载执行报告失败')
    console.error('加载执行报告失败:', error)
  } finally {
    loading.value = false
  }
}

const loadStatistics = async () => {
  try {
    const params = {}
    if (filters.value.dateRange) {
      params.start_date = filters.value.dateRange[0]
      params.end_date = filters.value.dateRange[1]
    }
    if (filters.value.environment) {
      params.environment = filters.value.environment
    }

    const response = await getExecutionStatistics(params)
    if (response.success) {
      statistics.value = response.data
    }
  } catch (error) {
    message.error('加载统计信息失败')
    console.error('加载统计信息失败:', error)
  }
}

const viewReportDetail = async (executionId) => {
  try {
    const response = await getExecutionReportDetail(executionId)
    if (response.success) {
      // 后端 snake_case → 模板 camelCase，递归转换
      selectedReport.value = snakeToCamelDeep(response.data)
      showDetailModal.value = true
      detailTab.value = 'overview'
    }
  } catch (error) {
    message.error('加载报告详情失败')
    console.error('加载报告详情失败:', error)
  }
}

// snake_case → camelCase 递归转换工具
function snakeToCamelDeep(value) {
  if (Array.isArray(value)) return value.map(snakeToCamelDeep)
  if (value !== null && typeof value === 'object' && value.constructor === Object) {
    const out = {}
    for (const [k, v] of Object.entries(value)) {
      const camelKey = k.replace(/_([a-z])/g, (_, c) => c.toUpperCase())
      out[camelKey] = snakeToCamelDeep(v)
    }
    return out
  }
  return value
}

const loadExecutionLogs = async () => {
  if (!selectedReport.value) return

  logsLoading.value = true
  try {
    const response = await getExecutionLogs(selectedReport.value.executionId)
    if (response.success) {
      executionLogs.value = response.data.logs
    }
  } catch (error) {
    message.error('加载执行日志失败')
    console.error('加载执行日志失败:', error)
  } finally {
    logsLoading.value = false
  }
}

const quickPreview = async (executionId) => {
  try {
    // 先获取报告详情，找到 Allure 或 HTML 报告文件
    const response = await getExecutionReportDetail(executionId)
    if (response.success && response.data) {
      // 后端字段 snake_case，转换后才能匹配前端逻辑
      const data = snakeToCamelDeep(response.data)
      const files = data.reportFiles || []
      // 优先 Allure（功能最全），退而求其次 HTML
      const target = files.find(f => f.format === 'allure') || files.find(f => f.format === 'html')
      if (target) {
        await previewReport(target, executionId)
      } else {
        message.warning('该执行记录暂无可预览的报告文件')
      }
    }
  } catch (error) {
    message.error('预览报告失败')
    console.error('预览报告失败:', error)
  }
}

const previewReport = async (report, executionId = null) => {
  try {
    // 优先用 preview_url（Allure 这种 SPA 静态站点必须用 iframe src，不能 srcdoc）
    const url = report.previewUrl || report.preview_url
    if (url) {
      previewSrc.value = url
      previewContent.value = ''
      previewType.value = report.format
      showPreviewModal.value = true
      return
    }

    // 降级：拉文件内容用 srcdoc 渲染
    const execId = executionId || selectedReport.value.executionId
    const response = await previewReportFile(execId, report.name)
    previewSrc.value = ''
    previewContent.value = response
    previewType.value = report.format
    showPreviewModal.value = true
  } catch (error) {
    message.error('预览报告失败')
    console.error('预览报告失败:', error)
  }
}

const downloadReport = (report) => {
  const url = getReportDownloadUrl(selectedReport.value.executionId, report.name)
  const link = document.createElement('a')
  link.href = url
  link.download = report.name
  link.click()
}

const deleteReport = (executionId) => {
  dialog.warning({
    title: '确认删除',
    content: '确定要删除这个执行报告吗？此操作不可恢复。',
    positiveText: '确定',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        const response = await deleteExecutionReport(executionId)
        if (response.success) {
          message.success('删除成功')
          loadReports()
        }
      } catch (error) {
        message.error('删除失败')
        console.error('删除失败:', error)
      }
    }
  })
}

const batchDelete = () => {
  dialog.warning({
    title: '确认批量删除',
    content: `确定要删除选中的 ${selectedRowKeys.value.length} 个执行报告吗？此操作不可恢复。`,
    positiveText: '确定',
    negativeText: '取消',
    onPositiveClick: async () => {
      batchDeleting.value = true
      try {
        await batchDeleteExecutionReports(selectedRowKeys.value)
        message.success('批量删除成功')
        selectedRowKeys.value = []
        loadReports()
      } catch (error) {
        message.error('批量删除失败')
        console.error('批量删除失败:', error)
      } finally {
        batchDeleting.value = false
      }
    }
  })
}

const compareReports = () => {
  // 报告对比功能
  message.info('报告对比功能开发中...')
}

const generateReport = async () => {
  if (!selectedReport.value) return

  generatingReport.value = true
  try {
    const response = await generateExecutionReport(selectedReport.value.executionId, {
      execution_id: selectedReport.value.executionId,
      formats: ['html', 'json'],
      include_details: true,
      include_logs: true
    })

    if (response.success) {
      message.success('报告生成成功')
      // 重新加载详情
      viewReportDetail(selectedReport.value.executionId)
    }
  } catch (error) {
    message.error('生成报告失败')
    console.error('生成报告失败:', error)
  } finally {
    generatingReport.value = false
  }
}

const shareReport = async () => {
  if (!selectedReport.value) return

  try {
    const response = await shareExecutionReport(selectedReport.value.executionId)
    if (response.success) {
      // 复制分享链接到剪贴板
      navigator.clipboard.writeText(response.data.share_url)
      message.success('分享链接已复制到剪贴板')
    }
  } catch (error) {
    message.error('分享报告失败')
    console.error('分享报告失败:', error)
  }
}

const exportReport = async () => {
  if (!selectedReport.value) return

  try {
    const response = await exportExecutionReport(selectedReport.value.executionId, 'json')
    if (response.success) {
      message.success('报告导出成功')
      // 下载导出的文件
      const url = response.data.download_url
      const link = document.createElement('a')
      link.href = url
      link.download = `execution_report_${selectedReport.value.executionId}.json`
      link.click()
    }
  } catch (error) {
    message.error('导出报告失败')
    console.error('导出报告失败:', error)
  }
}

const handlePageChange = (page) => {
  pagination.value.page = page
  loadReports()
}

const handlePageSizeChange = (pageSize) => {
  pagination.value.pageSize = pageSize
  pagination.value.page = 1
  loadReports()
}

const goFirst = () => {
  if (pagination.value.page === 1) return
  pagination.value.page = 1
  loadReports()
}

const goLast = () => {
  const last = totalPages.value
  if (pagination.value.page >= last) return
  pagination.value.page = last
  loadReports()
}

// 工具方法
const getStatusType = (status) => {
  const statusMap = {
    'PENDING': 'default',
    'PROCESSING': 'warning',
    'COMPLETED': 'success',
    'FAILED': 'error',
    'CANCELLED': 'default'
  }
  return statusMap[status] || 'default'
}

const getStatusText = (status) => {
  const statusMap = {
    'PENDING': '等待中',
    'PROCESSING': '处理中',
    'COMPLETED': '已完成',
    'FAILED': '已失败',
    'CANCELLED': '已取消'
  }
  return statusMap[status] || status
}

const getLogLevelClass = (level) => {
  const classMap = {
    'ERROR': 'text-red-400',
    'WARNING': 'text-yellow-400',
    'INFO': 'text-blue-400',
    'DEBUG': 'text-gray-400'
  }
  return classMap[level] || 'text-green-400'
}

onMounted(() => {
  loadReports()
  loadStatistics()

  // 监听统计模态框打开事件
  showStatisticsModal.value && loadStatistics()
})
</script>

<style scoped>
.execution-reports {
  padding: 20px;
  height: calc(100vh - 84px);
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

.list-card {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.list-card :deep(.n-card__content) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.list-table {
  flex: 1 1 auto;
  min-height: 0;
}

.report-detail {
  height: 75vh;
  overflow-y: auto;
}

.report-preview {
  height: 75vh;
}

.pagination-wrapper {
  flex: 0 0 auto;
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.pagination-prefix {
  display: flex;
  align-items: center;
  gap: 8px;
}

.total-text {
  color: var(--n-text-color, #606266);
  font-size: 13px;
}
</style>

<template>
  <div class="test-management">
    <!-- 工具栏 -->
    <n-card class="mb-6">
      <div class="flex justify-between items-center">
        <div class="flex items-center space-x-4">
          <n-input
            v-model:value="searchKeyword"
            placeholder="搜索测试用例..."
            clearable
            style="width: 300px"
            @keyup.enter="loadTestScripts"
          >
            <template #prefix>
              <n-icon><Icon icon="mdi:magnify" /></n-icon>
            </template>
          </n-input>

          <n-select
            v-model:value="filterStatus"
            :options="statusOptions"
            placeholder="测试类型筛选"
            clearable
            style="width: 180px"
            @update:value="loadTestScripts"
          />

          <n-select
            v-model:value="filterScriptId"
            :options="scriptOptions"
            placeholder="所在脚本筛选"
            clearable
            filterable
            remote
            :loading="scriptOptionsLoading"
            style="width: 240px"
            @search="onScriptSearch"
            @update:value="loadTestScripts"
          />
        </div>

        <n-space>
          <n-button @click="batchExecute" :disabled="!selectedScripts.length">
            <template #icon>
              <n-icon><Icon icon="mdi:play" /></n-icon>
            </template>
            批量执行
          </n-button>

          <n-button @click="loadTestScripts">
            <template #icon>
              <n-icon><Icon icon="mdi:refresh" /></n-icon>
            </template>
            刷新
          </n-button>
        </n-space>
      </div>
    </n-card>

    <!-- 测试脚本列表 -->
    <n-card
      title="测试脚本列表"
      class="list-card"
      :content-style="{ display: 'flex', flexDirection: 'column', minHeight: 0, padding: '20px' }"
    >
      <n-data-table
        class="list-table"
        :columns="scriptColumns"
        :data="testScripts"
        :loading="loading"
        :row-key="(row) => row.test_id"
        :scroll-x="1460"
        :flex-height="true"
        @update:checked-row-keys="handleSelectionChange"
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

    <!-- 用例详情/编辑模态框 -->
    <n-modal v-model:show="showScriptModal" preset="card" title="测试用例详情" style="width: 90%">
      <div v-if="selectedScript">
        <n-tabs type="line" v-model:value="activeTab">
          <n-tab-pane name="info" tab="基本信息">
            <n-form
              ref="scriptFormRef"
              :model="scriptForm"
              label-placement="left"
              label-width="120px"
            >
              <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <n-form-item label="用例名称" path="scriptName">
                    <n-input v-model:value="scriptForm.scriptName" />
                  </n-form-item>

                  <n-form-item label="测试类型" path="testType">
                    <n-select v-model:value="scriptForm.testType" :options="testTypeOptions" disabled />
                  </n-form-item>

                  <n-form-item label="优先级" path="priority">
                    <n-input v-model:value="scriptForm.priority" readonly />
                  </n-form-item>

                  <n-form-item label="所在脚本文件" path="scriptFilePath">
                    <n-input v-model:value="scriptForm.scriptFilePath" readonly />
                  </n-form-item>

                  <n-form-item label="pytest 节点" path="pytestNodeId">
                    <n-input
                      :value="scriptForm.className && scriptForm.methodName
                        ? `${scriptForm.className}::${scriptForm.methodName}`
                        : (scriptForm.methodName || '-')"
                      readonly
                    />
                  </n-form-item>
                </div>

                <div>
                  <n-form-item label="关联接口" path="endpointPath">
                    <n-input v-model:value="scriptForm.endpointPath" readonly />
                  </n-form-item>

                  <n-form-item label="HTTP方法" path="httpMethod">
                    <n-tag :type="getMethodType(scriptForm.httpMethod)">
                      {{ scriptForm.httpMethod }}
                    </n-tag>
                  </n-form-item>

                  <n-form-item label="超时时间" path="timeout">
                    <n-input-number v-model:value="scriptForm.timeout" :min="1" :max="300" disabled />
                    <span class="ml-2 text-gray-500">秒</span>
                  </n-form-item>

                  <n-form-item label="重试次数" path="retryCount">
                    <n-input-number v-model:value="scriptForm.retryCount" :min="0" :max="5" disabled />
                  </n-form-item>
                </div>
              </div>

              <n-form-item label="描述" path="description">
                <n-input
                  v-model:value="scriptForm.description"
                  type="textarea"
                  :rows="3"
                  readonly
                />
              </n-form-item>
            </n-form>
          </n-tab-pane>
          
          <n-tab-pane name="code" tab="脚本代码">
            <div class="code-editor-container">
              <!-- 顶部工具栏 -->
              <div class="flex justify-between items-center mb-4">
                <n-space>
                  <n-tag>{{ scriptForm.framework }}</n-tag>
                  <n-tag type="info">{{ scriptForm.language || 'Python' }}</n-tag>
                </n-space>
                <n-space>
                  <n-text depth="3" class="text-xs">
                    {{ (isCodeEditing ? editingCode : scriptForm.scriptContent || '').split('\n').length }} 行
                  </n-text>
                  <!-- 查看模式 -->
                  <template v-if="!isCodeEditing">
                    <n-button size="small" @click="startEditCode" type="primary" ghost>
                      <template #icon><n-icon><Icon icon="mdi:pencil" /></n-icon></template>
                      编辑
                    </n-button>
                  </template>
                  <!-- 编辑模式 -->
                  <template v-else>
                    <n-button size="small" @click="saveCode" type="primary" :loading="savingCode">
                      <template #icon><n-icon><Icon icon="mdi:content-save" /></n-icon></template>
                      保存代码
                    </n-button>
                    <n-button size="small" @click="cancelEditCode" :disabled="savingCode">取消</n-button>
                  </template>
                </n-space>
              </div>
              <!-- 显示模式 -->
              <n-code
                v-if="!isCodeEditing && scriptForm.scriptContent"
                :code="scriptForm.scriptContent"
                language="python"
                show-line-numbers
                style="max-height: 500px; overflow: auto;"
              />
              <n-empty v-else-if="!isCodeEditing && !scriptForm.scriptContent" description="暂无脚本代码" />
              <!-- 编辑模式 -->
              <SimpleCodeEditor
                v-if="isCodeEditing"
                v-model="editingCode"
                language="python"
                :height="500"
                :show-header="false"
              />
            </div>
          </n-tab-pane>
          
          <n-tab-pane name="config" tab="执行配置">
            <n-form label-placement="left" label-width="120px">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <n-form-item label="执行环境">
                    <n-select v-model:value="scriptForm.environment" :options="environmentOptions" />
                  </n-form-item>
                  
                  <n-form-item label="并行执行">
                    <n-switch v-model:value="scriptForm.parallelExecution" />
                  </n-form-item>
                  
                  <n-form-item label="数据驱动">
                    <n-switch v-model:value="scriptForm.dataDrivern" />
                  </n-form-item>
                </div>
                
                <div>
                  <n-form-item label="前置条件">
                    <n-select
                      v-model:value="scriptForm.prerequisites"
                      :options="prerequisiteOptions"
                      multiple
                      placeholder="选择前置测试脚本"
                    />
                  </n-form-item>
                  
                  <n-form-item label="测试数据">
                    <n-input
                      v-model:value="scriptForm.testDataPath"
                      placeholder="测试数据文件路径"
                    />
                  </n-form-item>
                </div>
              </div>
              
              <n-form-item label="环境变量">
                <n-dynamic-input
                  v-model:value="scriptForm.environmentVariables"
                  :on-create="() => ({ key: '', value: '' })"
                >
                  <template #default="{ value }">
                    <div class="flex space-x-2 w-full">
                      <n-input v-model:value="value.key" placeholder="变量名" style="flex: 1" />
                      <n-input v-model:value="value.value" placeholder="变量值" style="flex: 1" />
                    </div>
                  </template>
                </n-dynamic-input>
              </n-form-item>
            </n-form>
          </n-tab-pane>
          
          <n-tab-pane name="history" tab="执行历史">
            <n-data-table
              :columns="historyColumns"
              :data="executionHistory"
              :pagination="{ pageSize: 10 }"
              max-height="400"
            />
          </n-tab-pane>
        </n-tabs>
      </div>

      <template #footer>
        <div class="flex justify-between">
          <n-space>
            <n-button @click="() => executeScript(selectedScript)" type="primary" :loading="executing">
              <template #icon>
                <n-icon><Icon icon="mdi:play" /></n-icon>
              </template>
              执行用例
            </n-button>
          </n-space>

          <n-space>
            <n-button @click="saveScript" type="primary" :loading="saving">保存</n-button>
            <n-button @click="closeScriptModal">关闭</n-button>
          </n-space>
        </div>
      </template>
    </n-modal>

    <!-- 执行结果模态框 -->
    <n-modal v-model:show="showExecutionModal" preset="card" title="测试执行结果" style="width: 80%">
      <div v-if="executionResult">
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <n-statistic label="执行状态" :value="executionResult.status" />
          <n-statistic label="执行时间" :value="`${executionResult.duration}s`" />
          <n-statistic label="响应时间" :value="`${executionResult.responseTime}ms`" />
          <n-statistic label="断言结果" :value="`${executionResult.passedAssertions}/${executionResult.totalAssertions}`" />
        </div>

        <n-tabs type="line">
          <n-tab-pane name="result" tab="执行结果">
            <n-alert
              :type="executionResult.status === 'passed' ? 'success' : 'error'"
              :title="executionResult.status === 'passed' ? '测试通过' : '测试失败'"
              class="mb-4"
            >
              {{ executionResult.message }}
            </n-alert>
            
            <div v-if="executionResult.assertions">
              <h4 class="font-semibold mb-2">断言详情</h4>
              <n-list>
                <n-list-item v-for="assertion in executionResult.assertions" :key="assertion.id">
                  <div class="flex items-center justify-between w-full">
                    <span>{{ assertion.description }}</span>
                    <n-tag :type="assertion.passed ? 'success' : 'error'">
                      {{ assertion.passed ? '通过' : '失败' }}
                    </n-tag>
                  </div>
                </n-list-item>
              </n-list>
            </div>
          </n-tab-pane>
          
          <n-tab-pane name="request" tab="请求详情">
            <n-code :code="JSON.stringify(executionResult.request, null, 2)" language="json" />
          </n-tab-pane>
          
          <n-tab-pane name="response" tab="响应详情">
            <n-code :code="JSON.stringify(executionResult.response, null, 2)" language="json" />
          </n-tab-pane>
          
          <n-tab-pane name="logs" tab="执行日志">
            <div class="bg-black text-green-400 p-4 rounded font-mono text-sm h-64 overflow-y-auto">
              <div v-for="(log, index) in executionResult.logs" :key="index" class="mb-1">
                <span class="text-gray-500">[{{ formatTime(log.timestamp) }}]</span>
                <span>{{ log.message }}</span>
              </div>
            </div>
          </n-tab-pane>
        </n-tabs>
      </div>
    </n-modal>

    <!-- AI 诊断抽屉 -->
    <HealingDrawer
      v-model:show="healingShow"
      :script-id="healingScriptId"
      :script-name="healingScriptName"
      :test-case-id="healingTestCaseId"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NTag, NPopover, NCode, NEmpty, NText, NIcon, useMessage } from 'naive-ui'
import { Icon } from '@iconify/vue'
import api from '@/api'
import { formatTime } from '@/utils'
import SimpleCodeEditor from '@/components/SimpleCodeEditor.vue'
import HealingDrawer from './HealingDrawer.vue'

// 动态导入Monaco Editor，如果失败则使用SimpleCodeEditor
const codeEditorComponent = shallowRef(SimpleCodeEditor)

// 异步加载Monaco Editor
const loadMonacoEditor = async () => {
  try {
    const MonacoEditor = await import('@/components/MonacoEditor.vue')
    codeEditorComponent.value = MonacoEditor.default
    console.log('✅ Monaco Editor 加载成功')
  } catch (error) {
    console.warn('⚠️ Monaco Editor 加载失败，使用简化编辑器:', error.message)
    codeEditorComponent.value = SimpleCodeEditor
  }
}

const router = useRouter()
const message = useMessage()

// 数据
const testScripts = ref([])
const loading = ref(false)
const selectedScripts = ref([])
const searchKeyword = ref('')
const filterStatus = ref('')

// 所在脚本筛选（远程搜索 + 分页 50）
const filterScriptId = ref(null)
const scriptOptions = ref([])
const scriptOptionsLoading = ref(false)
let scriptSearchTimer = null

// AI 诊断抽屉
const healingShow = ref(false)
const healingScriptId = ref('')
const healingScriptName = ref('')
const healingTestCaseId = ref('')

const openHealing = (row) => {
  if (!row.script_id) {
    message.error('该用例未关联有效脚本 ID，无法发起 AI 诊断')
    return
  }
  healingScriptId.value = row.script_id
  healingScriptName.value = row.script_file_name || row.name || ''
  healingTestCaseId.value = row.test_id || ''
  healingShow.value = true
}

// 模态框状态
const showScriptModal = ref(false)
const showCreateModal = ref(false)
const showExecutionModal = ref(false)
const activeTab = ref('info')

// 表单数据
const selectedScript = ref(null)
const scriptForm = ref({})
const createForm = ref({
  endpointId: '',
  scriptName: '',
  framework: 'pytest',
  testType: 'functional',
  templateOptions: ['basic_structure']
})

// 执行状态
const executing = ref(false)
const executingId = ref(null)
const debugging = ref(false)
const saving = ref(false)
const savingCode = ref(false)
const isCodeEditing = ref(false)
const editingCode = ref('')
const creating = ref(false)
const executionResult = ref(null)
const executionHistory = ref([])

// 分页
const pagination = ref({
  page: 1,
  pageSize: 20,
  itemCount: 0,
  pageSizes: [10, 20, 50, 100]
})

// 总页数，用于禁用尾页按钮
const totalPages = computed(() => {
  const ps = pagination.value.pageSize || 1
  return Math.max(1, Math.ceil((pagination.value.itemCount || 0) / ps))
})

// 选项数据
const statusOptions = [
  { label: '全部类型', value: '' },
  { label: '正向', value: 'positive' },
  { label: '异常', value: 'negative' },
  { label: '边界', value: 'boundary' },
  { label: '安全', value: 'security' },
  { label: '性能', value: 'performance' }
]

const frameworkOptions = [
  { label: 'pytest', value: 'pytest' },
  { label: 'unittest', value: 'unittest' },
  { label: 'requests', value: 'requests' }
]

const testTypeOptions = [
  { label: '正向测试', value: 'positive' },
  { label: '异常测试', value: 'negative' },
  { label: '边界测试', value: 'boundary' },
  { label: '安全测试', value: 'security' },
  { label: '性能测试', value: 'performance' }
]

const priorityOptions = [
  { label: '高', value: 'high' },
  { label: '中', value: 'medium' },
  { label: '低', value: 'low' }
]

const environmentOptions = [
  { label: '测试环境', value: 'test' },
  { label: '预发布环境', value: 'staging' },
  { label: '生产环境', value: 'production' }
]

const endpointOptions = ref([])
const prerequisiteOptions = ref([])

// 表格列定义
const scriptColumns = [
  { type: 'selection' },
  { title: '用例名称', key: 'name', width: 240, ellipsis: { tooltip: true } },
  {
    title: '接口信息',
    key: 'interface_info',
    width: 300,
    render: (row) => {
      if (row.interface_info && row.interface_info.method) {
        return h('div', [
          h('div', { style: 'font-weight: bold; margin-bottom: 4px;' }, row.interface_info.name || '未知接口'),
          h('div', { style: 'font-size: 12px; color: #666;' }, [
            h(NTag, {
              type: getMethodType(row.interface_info.method),
              size: 'small',
              style: 'margin-right: 8px;'
            }, { default: () => row.interface_info.method }),
            row.interface_info.path
          ])
        ])
      }
      return h('span', { style: 'color: #999;' }, '无关联接口')
    }
  },
  {
    title: '所在脚本',
    key: 'script_file_name',
    width: 200,
    minWidth: 120,
    resizable: true,
    ellipsis: { tooltip: true },
    render: (row) => row.script_file_name
      ? h('span', { style: 'font-family: ui-monospace, SFMono-Regular, monospace;' }, row.script_file_name)
      : h('span', { style: 'color: #999;' }, '-')
  },
  {
    title: '步骤',
    key: 'flow_steps',
    width: 130,
    render: (row) => {
      const fs = row.flow_summary || {}
      const kind = fs.kind || ''

      // cases 型：N 条独立用例
      if (kind === 'cases') {
        const cases = Array.isArray(fs.cases) ? fs.cases : []
        const caseCount = Number(fs.case_count ?? cases.length) || 0
        if (!caseCount) return h('span', { style: 'color: #999;' }, '-')

        const trigger = h('div', { style: 'cursor: help; display: flex; align-items: center;' }, [
          h(NTag, { type: 'warning', size: 'small' },
            { default: () => `${caseCount} 用例` }),
        ])

        const caseRows = cases.map((c, idx) => {
          const method = (c.method || '').toUpperCase()
          const methodColor = {
            GET: '#2080f0', POST: '#18a058', PUT: '#f0a020',
            PATCH: '#d03050', DELETE: '#d03050',
          }[method] || '#666'
          return h('div', {
            style: 'display: grid; grid-template-columns: 28px 56px 1fr; gap: 8px; align-items: start; padding: 6px 0; border-bottom: 1px solid #f0f0f0;'
          }, [
            h('div', { style: 'color: #999; font-size: 12px;' }, `${idx + 1}`),
            h('div', {
              style: `color: ${methodColor}; font-weight: 600; font-size: 12px; font-family: ui-monospace, SFMono-Regular, monospace;`
            }, method || '-'),
            h('div', { style: 'font-size: 12px; line-height: 1.5; word-break: break-all;' }, [
              h('div', { style: 'font-family: ui-monospace, SFMono-Regular, monospace; color: #333;' }, c.path || ''),
              c.purpose
                ? h('div', { style: 'color: #666; margin-top: 2px;' }, c.purpose)
                : null,
            ]),
          ])
        })

        const tipContent = h('div', { style: 'width: 520px; font-size: 12px;' }, [
          h('div', {
            style: 'font-weight: 600; padding-bottom: 6px; border-bottom: 1px solid #e5e5e5; margin-bottom: 4px;'
          }, `${fs.chain_name || '独立用例集'}（共 ${caseCount} 条独立用例）`),
          h('div', { style: 'max-height: 360px; overflow-y: auto; padding-right: 4px;' }, caseRows),
        ])

        return h(NPopover, {
          trigger: 'hover',
          placement: 'top',
          raw: false,
          style: { maxWidth: '560px', padding: '12px' },
        }, {
          trigger: () => trigger,
          default: () => tipContent,
        })
      }

      // scenario / 其他：合并步骤展示
      const steps = Array.isArray(fs.steps) ? fs.steps : []
      const stepCount = Number(fs.step_count ?? steps.length) || 0
      if (!stepCount) return h('span', { style: 'color: #999;' }, '-')

      const isScenario = kind === 'scenario'
      const trigger = h('div', { style: 'cursor: help; display: flex; align-items: center;' }, [
        h(NTag, { type: isScenario ? 'info' : 'default', size: 'small' },
          { default: () => `${stepCount} 步` }),
      ])

      const stepRows = steps.map((s) => {
        const method = (s.method || '').toUpperCase()
        const methodColor = {
          GET: '#2080f0', POST: '#18a058', PUT: '#f0a020',
          PATCH: '#d03050', DELETE: '#d03050',
        }[method] || '#666'
        return h('div', {
          style: 'display: grid; grid-template-columns: 28px 56px 1fr; gap: 8px; align-items: start; padding: 6px 0; border-bottom: 1px solid #f0f0f0;'
        }, [
          h('div', { style: 'color: #999; font-size: 12px;' }, `${s.no}`),
          h('div', {
            style: `color: ${methodColor}; font-weight: 600; font-size: 12px; font-family: ui-monospace, SFMono-Regular, monospace;`
          }, method || '-'),
          h('div', { style: 'font-size: 12px; line-height: 1.5; word-break: break-all;' }, [
            h('div', { style: 'font-family: ui-monospace, SFMono-Regular, monospace; color: #333;' }, s.path || ''),
            s.purpose
              ? h('div', { style: 'color: #666; margin-top: 2px;' }, s.purpose)
              : null,
          ]),
        ])
      })

      const tipContent = h('div', { style: 'width: 520px; font-size: 12px;' }, [
        h('div', {
          style: 'font-weight: 600; padding-bottom: 6px; border-bottom: 1px solid #e5e5e5; margin-bottom: 4px;'
        }, isScenario ? `Scenario：${fs.chain_name || ''}（共 ${stepCount} 步）` : `执行流（共 ${stepCount} 步）`),
        h('div', { style: 'max-height: 360px; overflow-y: auto; padding-right: 4px;' }, stepRows),
      ])

      return h(NPopover, {
        trigger: 'hover',
        placement: 'top',
        raw: false,
        style: { maxWidth: '560px', padding: '12px' },
      }, {
        trigger: () => trigger,
        default: () => tipContent,
      })
    }
  },
  {
    title: '断言',
    key: 'flow_asserts',
    width: 130,
    render: (row) => {
      const fs = row.flow_summary || {}
      const kind = fs.kind || ''

      // cases 型：聚合每条用例的断言数
      if (kind === 'cases') {
        const cases = Array.isArray(fs.cases) ? fs.cases : []
        const total = cases.reduce((sum, c) => sum + (Number(c.assertion_count) || 0), 0)
        if (!total) return h('span', { style: 'color: #999;' }, '-')

        const trigger = h('div', { style: 'cursor: help; display: flex; align-items: center;' }, [
          h(NTag, { type: 'success', size: 'small' },
            { default: () => `Σ${total} 断言` }),
        ])

        const caseRows = cases.map((c, idx) => h('div', {
          style: 'display: grid; grid-template-columns: 64px 1fr 56px; gap: 8px; align-items: start; padding: 6px 0; border-bottom: 1px solid #f0f0f0;'
        }, [
          h('div', { style: 'color: #999; font-size: 12px;' }, `用例 ${idx + 1}`),
          h('div', { style: 'font-size: 12px; line-height: 1.5; word-break: break-all;' }, [
            h('div', {
              style: 'font-family: ui-monospace, SFMono-Regular, monospace; color: #333;'
            }, `${(c.method || '').toUpperCase()} ${c.path || ''}`),
            c.purpose
              ? h('div', { style: 'color: #666; margin-top: 2px;' }, c.purpose)
              : null,
          ]),
          h('div', {
            style: 'text-align: right; color: #18a058; font-weight: 600; font-size: 12px;'
          }, `${c.assertion_count || 0} 断言`),
        ]))

        const tipContent = h('div', { style: 'width: 520px; font-size: 12px;' }, [
          h('div', {
            style: 'font-weight: 600; padding-bottom: 6px; border-bottom: 1px solid #e5e5e5; margin-bottom: 4px;'
          }, `各用例断言数（共 ${total} 条，跨 ${cases.length} 用例）`),
          h('div', { style: 'max-height: 360px; overflow-y: auto; padding-right: 4px;' }, caseRows),
        ])

        return h(NPopover, {
          trigger: 'hover',
          placement: 'top',
          raw: false,
          style: { maxWidth: '560px', padding: '12px' },
        }, {
          trigger: () => trigger,
          default: () => tipContent,
        })
      }

      // scenario / 其他：合并断言列表
      const asserts = Array.isArray(fs.assertions) ? fs.assertions : []
      const assertCount = Number(fs.assertion_count ?? asserts.length) || 0
      if (!assertCount) return h('span', { style: 'color: #999;' }, '-')

      const trigger = h('div', { style: 'cursor: help; display: flex; align-items: center;' }, [
        h(NTag, { type: 'success', size: 'small' },
          { default: () => `${assertCount} 断言` }),
      ])

      const assertRows = asserts.map((a) => {
        const stepTag = a.step_no ? `step ${a.step_no}` : '-'
        const kind = a.kind || 'equals'
        const inPath = a.in || ''
        const hasExpected = a.expected && 'value' in a.expected
        const expectedStr = hasExpected ? JSON.stringify(a.expected.value) : ''
        return h('div', {
          style: 'display: grid; grid-template-columns: 64px 1fr; gap: 8px; align-items: start; padding: 6px 0; border-bottom: 1px solid #f0f0f0;'
        }, [
          h('div', { style: 'color: #999; font-size: 12px;' }, stepTag),
          h('div', { style: 'font-size: 12px; line-height: 1.5; word-break: break-all;' }, [
            h('div', {
              style: 'font-family: ui-monospace, SFMono-Regular, monospace; color: #333;'
            }, [
              h('span', { style: 'color: #d03050; font-weight: 600;' }, kind),
              inPath ? h('span', { style: 'color: #666;' }, ` ${inPath}`) : null,
              hasExpected
                ? h('span', { style: 'color: #18a058;' }, ` → ${expectedStr}`)
                : null,
            ]),
            a.desc
              ? h('div', { style: 'color: #666; margin-top: 2px;' }, a.desc)
              : null,
          ]),
        ])
      })

      const tipContent = h('div', { style: 'width: 520px; font-size: 12px;' }, [
        h('div', {
          style: 'font-weight: 600; padding-bottom: 6px; border-bottom: 1px solid #e5e5e5; margin-bottom: 4px;'
        }, `断言（共 ${assertCount} 条）`),
        h('div', { style: 'max-height: 360px; overflow-y: auto; padding-right: 4px;' }, assertRows),
      ])

      return h(NPopover, {
        trigger: 'hover',
        placement: 'top',
        raw: false,
        style: { maxWidth: '560px', padding: '12px' },
      }, {
        trigger: () => trigger,
        default: () => tipContent,
      })
    }
  },
  {
    title: '最近执行',
    key: 'last_execution_status',
    width: 110,
    render: (row) => {
      if (!row.last_execution_status) return h('span', { style: 'color: #999;' }, '未执行')
      const map = {
        PASSED: 'success', FAILED: 'error', ERROR: 'error', SKIPPED: 'warning',
      }
      return h(NTag, { type: map[row.last_execution_status] || 'default', size: 'small' },
        { default: () => row.last_execution_status })
    }
  },
  {
    title: '最后执行',
    key: 'last_execution_time',
    width: 150,
    render: (row) => row.last_execution_time ? formatTime(row.last_execution_time) : '-'
  },
  {
    title: '操作',
    key: 'actions',
    width: 280,
    fixed: 'right',
    render: (row) => {
      const buttons = [
        h(NButton,
          {
            size: 'small',
            type: 'primary',
            onClick: () => editScript(row)
          },
          { default: () => '详情' }
        ),
        h(NButton,
          {
            size: 'small',
            type: 'info',
            style: 'margin-left: 8px',
            loading: executing.value && executingId.value === row.test_id,
            onClick: () => executeScript(row)
          },
          { default: () => '执行' }
        ),
      ]

      // 最近执行失败时才显示【AI 诊断】按钮
      const failedStatus = ['FAILED', 'ERROR']
      if (failedStatus.includes(row.last_execution_status)) {
        buttons.push(h(NButton,
          {
            size: 'small',
            type: 'warning',
            style: 'margin-left: 8px',
            onClick: () => openHealing(row)
          },
          { default: () => 'AI 诊断' }
        ))
      }

      buttons.push(h(NButton,
        {
          size: 'small',
          type: 'error',
          style: 'margin-left: 8px',
          onClick: () => deleteScript(row)
        },
        { default: () => '删除' }
      ))

      return buttons
    }
  }
]

const historyColumns = [
  { title: '执行时间', key: 'executionTime', width: 150, render: (row) => formatTime(row.executionTime) },
  { title: '状态', key: 'status', width: 100 },
  { title: '执行时长', key: 'duration', width: 100, render: (row) => `${row.duration}s` },
  { title: '环境', key: 'environment', width: 100 },
  { title: '结果', key: 'result', ellipsis: true }
]

// 方法
const loadScriptOptions = async (query = '') => {
  scriptOptionsLoading.value = true
  try {
    const res = await api.getAllScripts({
      page: 1,
      page_size: 50,
      search: query || undefined,
    })
    const list = res?.data?.scripts || res?.data?.items || (Array.isArray(res?.data) ? res.data : [])
    scriptOptions.value = list.map((s) => ({
      label: s.file_name || s.name || s.script_id,
      value: s.script_id,
    }))
  } catch (e) {
    // 静默失败，下拉为空就为空
  } finally {
    scriptOptionsLoading.value = false
  }
}

const onScriptSearch = (query) => {
  clearTimeout(scriptSearchTimer)
  scriptSearchTimer = setTimeout(() => loadScriptOptions(query), 300)
}

const loadTestScripts = async () => {
  loading.value = true
  try {
    const params = {
      page: pagination.value.page,
      page_size: pagination.value.pageSize,
      search: searchKeyword.value || undefined,
      test_type: filterStatus.value || undefined,
      script_id: filterScriptId.value || undefined,
      include_inactive: false
    }

    const response = await api.getAllTestCases(params)

    if (response && response.data && Array.isArray(response.data.items)) {
      testScripts.value = response.data.items
      pagination.value.itemCount = response.data.total || 0
      if (testScripts.value.length === 0) {
        message.info('暂无测试用例数据')
      }
    } else {
      console.error('用例列表响应格式异常:', response)
      testScripts.value = []
      pagination.value.itemCount = 0
      message.warning('获取用例列表失败，数据格式不正确')
    }
  } catch (error) {
    console.error('加载测试用例失败:', error)
    message.error('加载测试用例失败: ' + (error.message || '未知错误'))
    testScripts.value = []
    pagination.value.itemCount = 0
  } finally {
    loading.value = false
  }
}

const loadEndpoints = async () => {
  try {
    const response = await api.getApiEndpoints()
    endpointOptions.value = response.data.map(endpoint => ({
      label: `${endpoint.method} ${endpoint.path}`,
      value: endpoint.endpointId
    }))
  } catch (error) {
    message.error('加载接口列表失败')
  }
}

const handleSelectionChange = (keys) => {
  selectedScripts.value = keys
}

const handlePageChange = (page) => {
  pagination.value.page = page
  loadTestScripts()
}

const handlePageSizeChange = (pageSize) => {
  pagination.value.pageSize = pageSize
  pagination.value.page = 1
  loadTestScripts()
}

const goFirst = () => {
  if (pagination.value.page === 1) return
  pagination.value.page = 1
  loadTestScripts()
}

const goLast = () => {
  const last = totalPages.value
  if (pagination.value.page >= last) return
  pagination.value.page = last
  loadTestScripts()
}

const editScript = async (testCase) => {
  if (!testCase || typeof testCase !== 'object' || !testCase.test_id) {
    message.error('无效的用例数据')
    return
  }

  selectedScript.value = testCase

  // 详情弹窗的表单结构沿用，把用例信息映射进去（含所在脚本文件）
  scriptForm.value = {
    testId: testCase.test_id,
    scriptName: testCase.name || '',
    description: testCase.description || '',
    framework: 'pytest',
    language: 'python',
    testType: testCase.test_type || 'positive',
    priority: testCase.priority || 'P2',
    endpointPath: testCase.interface_info?.path || '',
    httpMethod: testCase.interface_info?.method || '',
    timeout: testCase.timeout || 30,
    retryCount: testCase.retry_count || 0,
    environment: 'test',
    parallelExecution: false,
    dataDrivern: false,
    prerequisites: [],
    scriptFilePath: testCase.script_file_path || '',
    scriptFileName: testCase.script_file_name || '',
    className: testCase.class_name || '',
    methodName: testCase.method_name || '',
    scriptContent: ''
  }

  // 获取用例详情（含 test_data / assertions），并尝试读取所在脚本内容
  try {
    const detailResp = await api.getTestCaseDetail(testCase.test_id)
    if (detailResp && detailResp.data) {
      const d = detailResp.data
      scriptForm.value = {
        ...scriptForm.value,
        scriptName: d.name || scriptForm.value.scriptName,
        description: d.description || scriptForm.value.description,
        testType: d.test_type || scriptForm.value.testType,
        priority: d.priority || scriptForm.value.priority,
        scriptFilePath: d.script_file_path || scriptForm.value.scriptFilePath,
        scriptFileName: d.script_file_name || scriptForm.value.scriptFileName,
        className: d.class_name || scriptForm.value.className,
        methodName: d.method_name || scriptForm.value.methodName,
        testData: d.test_data || [],
        assertions: d.assertions || [],
      }
    }
  } catch (error) {
    console.error('获取用例详情失败:', error)
    message.error('获取用例详情失败: ' + (error.message || '未知错误'))
  }

  // 加载脚本文件源代码（用于"脚本代码" Tab 展示）
  const scriptId = selectedScript.value?.script_id
  if (scriptId) {
    try {
      const scriptResp = await api.getScriptDetail(scriptId)
      if (scriptResp?.data?.content) {
        scriptForm.value.scriptContent = scriptResp.data.content
      }
    } catch {
      console.warn('读取脚本内容失败, script_id:', scriptId)
    }
  }

  executionHistory.value = []
  isCodeEditing.value = false
  editingCode.value = ''
  showScriptModal.value = true
}

const executeScript = async (testCase) => {
  if (testCase && typeof testCase === 'object' && 'value' in testCase && !testCase.test_id) {
    testCase = testCase.value
  }
  if (!testCase || !testCase.test_id) {
    testCase = selectedScript.value
  }
  if (!testCase || !testCase.test_id) {
    message.error('无效的用例ID')
    return
  }

  const testId = testCase.test_id
  executing.value = true
  executingId.value = testId
  try {
    const response = await api.runTestCase(testId, {
      environment: 'test',
      timeout: 300
    })

    if (response.code === 200 && response.data) {
      const { execution_id: executionId } = response.data
      message.success(`用例执行任务已启动（ID: ${executionId}），可在「执行报告」页查看进度`)
      showScriptModal.value = false
      await loadTestScripts()
    } else {
      message.error('启动执行失败: ' + (response.msg || '未知错误'))
    }
  } catch (error) {
    console.error('执行用例失败:', error)
    message.error('执行用例失败: ' + (error.message || '未知错误'))
  } finally {
    executing.value = false
    executingId.value = null
  }
}

const pollExecutionResult = async (scriptId, executionId, maxAttempts = 30) => {
  let attempts = 0

  const checkResult = async () => {
    try {
      attempts++
      const response = await api.getScriptExecutionResult(scriptId, executionId)

      if (response.success && response.data) {
        const result = response.data

        if (result.status === 'RUNNING') {
          // 继续轮询
          if (attempts < maxAttempts) {
            setTimeout(checkResult, 2000) // 2秒后再次检查
            return
          } else {
            message.warning('执行超时，请稍后查看结果')
            return
          }
        } else {
          // 执行完成，显示结果
          executionResult.value = {
            execution_id: executionId,
            script_id: scriptId,
            status: result.status === 'success' ? 'passed' : 'failed',
            message: result.status === 'success' ? '测试执行成功' : '测试执行失败',
            duration: result.total_duration || 0,
            responseTime: 0,
            passedAssertions: result.summary?.passed_tests || 0,
            totalAssertions: result.summary?.total_tests || 0,
            assertions: result.script_results?.map(sr => ({
              id: sr.script_id,
              description: sr.script_name,
              passed: sr.status === 'PASSED'
            })) || [],
            request: {},
            response: {},
            logs: result.script_results?.map(sr => ({
              timestamp: new Date().toISOString(),
              message: `${sr.script_name}: ${sr.status}`
            })) || []
          }

          showExecutionModal.value = true

          if (result.status === 'success') {
            message.success('脚本执行完成')
          } else {
            message.error('脚本执行失败')
          }

          // 刷新脚本列表
          loadTestScripts()
        }
      }
    } catch (error) {
      console.error('获取执行结果失败:', error)
      if (attempts < maxAttempts) {
        setTimeout(checkResult, 2000)
      } else {
        message.error('获取执行结果失败')
      }
    }
  }

  // 开始检查
  checkResult()
}

const debugScript = async () => {
  if (!selectedScript.value) {
    message.error('请先选择脚本')
    return
  }
  const scriptId = selectedScript.value.script_id || selectedScript.value.scriptId
  if (!scriptId) {
    message.error('无效的脚本ID')
    return
  }

  debugging.value = true
  try {
    const response = await api.executeSingleScript(scriptId, {
      debugMode: true
    })

    executionResult.value = response.data
    showExecutionModal.value = true
  } catch (error) {
    console.error('调试测试失败:', error)
    const detail = error?.response?.data?.detail || error?.response?.data?.msg || error?.message || '未知错误'
    message.error('调试测试失败: ' + detail)
  } finally {
    debugging.value = false
  }
}

const saveScript = async () => {
  saving.value = true
  try {
    const testId = selectedScript.value.test_id
    if (testId && scriptForm.value.scriptName) {
      await api.updateTestCase(testId, { name: scriptForm.value.scriptName })
    }
    // 如果在代码编辑模式，一并保存代码
    if (isCodeEditing.value) {
      await doSaveCode()
    }
    message.success('保存成功')
    showScriptModal.value = false
    loadTestScripts()
    showScriptModal.value = false
    loadTestScripts()
  } catch (error) {
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

// ==================== 代码编辑 ====================

const startEditCode = () => {
  editingCode.value = scriptForm.value.scriptContent || ''
  isCodeEditing.value = true
}

const cancelEditCode = () => {
  isCodeEditing.value = false
  editingCode.value = ''
}

const doSaveCode = async () => {
  const scriptId = selectedScript.value?.script_id
  if (!scriptId) throw new Error('缺少脚本 ID')
  const resp = await api.updateScriptCode(scriptId, { content: editingCode.value })
  if (resp?.data) {
    scriptForm.value.scriptContent = editingCode.value
    isCodeEditing.value = false
  } else {
    throw new Error(resp?.msg || '保存失败')
  }
}

const saveCode = async () => {
  savingCode.value = true
  try {
    await doSaveCode()
    message.success('代码已保存')
  } catch (error) {
    const detail = error?.response?.data?.detail || error?.message || '未知错误'
    message.error('保存代码失败: ' + detail)
  } finally {
    savingCode.value = false
  }
}

const closeScriptModal = () => {
  if (isCodeEditing.value && editingCode.value !== (scriptForm.value.scriptContent || '')) {
    if (!window.confirm('代码尚未保存，确定关闭吗？')) return
  }
  isCodeEditing.value = false
  editingCode.value = ''
  showScriptModal.value = false
}

const createTestScript = async () => {
  creating.value = true
  try {
    // 暂时禁用创建功能，提示用户使用脚本生成功能
    message.warning('请使用接口管理页面的"生成脚本"功能来创建测试脚本')
    showCreateModal.value = false

    // 重置表单
    createForm.value = {
      endpointId: '',
      scriptName: '',
      framework: 'pytest',
      testType: 'functional',
      templateOptions: ['basic_structure']
    }
  } catch (error) {
    message.error('操作失败')
  } finally {
    creating.value = false
  }
}

const deleteScript = async (testCase) => {
  try {
    const testId = testCase.test_id
    if (!testId) {
      message.error('无效的用例ID')
      return
    }
    await api.deleteTestCase(testId)
    message.success('删除成功')
    await loadTestScripts()
  } catch (error) {
    console.error('删除用例失败:', error)
    message.error('删除用例失败: ' + (error.message || '未知错误'))
  }
}

const batchExecute = async () => {
  if (!selectedScripts.value.length) {
    message.warning('请先勾选要执行的用例')
    return
  }

  try {
    const response = await api.executeTestCases({
      test_ids: selectedScripts.value,
      environment: 'test',
      timeout: 300,
      max_workers: 4,
    })

    if (response.code === 200 && response.data) {
      const { execution_id, test_case_count, script_count, max_workers } = response.data
      message.success(`已提交 ${test_case_count} 条用例（${script_count} 个脚本并发度 ${max_workers}）`)
      router.push(`/api-automation/execution-reports/${execution_id}`)
    } else {
      message.error('启动批量执行失败: ' + (response.msg || '未知错误'))
    }
  } catch (error) {
    console.error('批量执行失败:', error)
    const detail = error?.response?.data?.detail || error?.message || '未知错误'
    message.error('批量执行失败: ' + detail)
  }
}

const formatCode = () => {
  message.info('代码格式化功能开发中...')
}

const validateCode = () => {
  message.info('语法验证功能开发中...')
}

// Monaco Editor 相关方法
const getEditorLanguage = () => {
  const framework = scriptForm.value.framework || 'pytest'
  const language = scriptForm.value.language || 'python'

  // 根据框架和语言返回Monaco Editor支持的语言
  if (language.toLowerCase() === 'python' || framework.includes('pytest') || framework.includes('unittest')) {
    return 'python'
  } else if (language.toLowerCase() === 'javascript' || framework.includes('jest') || framework.includes('mocha')) {
    return 'javascript'
  } else if (language.toLowerCase() === 'java' || framework.includes('junit')) {
    return 'java'
  }

  return 'python' // 默认返回Python
}

const getEditorPlaceholder = () => {
  const framework = scriptForm.value.framework || 'pytest'
  const interfacePath = scriptForm.value.endpointPath || '/api/test'
  const method = (scriptForm.value.httpMethod || 'GET').toLowerCase()

  if (framework === 'pytest') {
    return `# Python + Pytest 测试脚本
import pytest
import requests

def test_${scriptForm.value.scriptName || 'api_endpoint'}():
    """测试 ${interfacePath} 接口"""
    url = "http://localhost:8000${interfacePath}"
    response = requests.${method}(url)
    assert response.status_code == 200`
  } else if (framework === 'unittest') {
    return `# Python + Unittest 测试脚本
import unittest
import requests

class TestAPI(unittest.TestCase):
    def test_${scriptForm.value.scriptName || 'api_endpoint'}(self):
        """测试 ${interfacePath} 接口"""
        url = "http://localhost:8000${interfacePath}"
        response = requests.${method}(url)
        self.assertEqual(response.status_code, 200)`
  }

  return '# 请输入测试脚本代码...'
}

const onCodeChange = (value) => {
  console.log('代码内容变化:', value.length, '字符')
}

const onCodeFocus = () => {
  console.log('代码编辑器获得焦点')
}

const onCodeBlur = () => {
  console.log('代码编辑器失去焦点')
}

const insertTemplate = () => {
  const framework = scriptForm.value.framework || 'pytest'
  let template = ''

  if (framework === 'pytest') {
    template = `import pytest
import requests
from typing import Dict, Any


class TestAPI:
    """API测试类"""

    def setup_method(self):
        """测试前置设置"""
        self.base_url = "http://localhost:8000"
        self.headers = {"Content-Type": "application/json"}

    def test_${scriptForm.value.scriptName || 'api_endpoint'}(self):
        """测试API端点"""
        # 准备测试数据
        url = f"{self.base_url}${scriptForm.value.endpointPath || '/api/test'}"
        data = {
            # 添加测试数据
        }

        # 发送请求
        response = requests.${(scriptForm.value.httpMethod || 'GET').toLowerCase()}(
            url,
            headers=self.headers,
            json=data if '${scriptForm.value.httpMethod || 'GET'}' != 'GET' else None
        )

        # 验证响应
        assert response.status_code == 200
        assert response.json() is not None

        # 添加更多断言
        result = response.json()
        # assert result["success"] is True
        # assert "data" in result

    def teardown_method(self):
        """测试后清理"""
        pass`
  } else if (framework === 'unittest') {
    template = `import unittest
import requests
from typing import Dict, Any


class Test${scriptForm.value.scriptName || 'API'}(unittest.TestCase):
    """API测试类"""

    def setUp(self):
        """测试前置设置"""
        self.base_url = "http://localhost:8000"
        self.headers = {"Content-Type": "application/json"}

    def test_${scriptForm.value.scriptName || 'api_endpoint'}(self):
        """测试API端点"""
        # 准备测试数据
        url = f"{self.base_url}${scriptForm.value.endpointPath || '/api/test'}"
        data = {
            # 添加测试数据
        }

        # 发送请求
        response = requests.${(scriptForm.value.httpMethod || 'GET').toLowerCase()}(
            url,
            headers=self.headers,
            json=data if '${scriptForm.value.httpMethod || 'GET'}' != 'GET' else None
        )

        # 验证响应
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json())

        # 添加更多断言
        result = response.json()
        # self.assertTrue(result["success"])
        # self.assertIn("data", result)

    def tearDown(self):
        """测试后清理"""
        pass


if __name__ == '__main__':
    unittest.main()`
  }

  if (template) {
    scriptForm.value.scriptContent = template
    message.success('模板插入成功')
  } else {
    message.warning('暂不支持该框架的模板')
  }
}

const handleEndpointSelect = (endpointId) => {
  // 根据选择的接口自动填充脚本名称
  const endpoint = endpointOptions.value.find(opt => opt.value === endpointId)
  if (endpoint) {
    createForm.value.scriptName = `test_${endpoint.label.replace(/[^a-zA-Z0-9]/g, '_').toLowerCase()}`
  }
}

const getMethodType = (method) => {
  const typeMap = {
    'GET': 'success',
    'POST': 'warning',
    'PUT': 'info',
    'DELETE': 'error',
    'PATCH': 'default'
  }
  return typeMap[method] || 'default'
}

onMounted(async () => {
  loadTestScripts()
  loadEndpoints()
  loadScriptOptions()
})
</script>

<style scoped>
.test-management {
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
}

.list-table {
  flex: 1 1 auto;
  min-height: 0;
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

.code-editor-container {
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 16px;
}

.code-editor {
  font-family: 'Courier New', monospace;
}
</style>

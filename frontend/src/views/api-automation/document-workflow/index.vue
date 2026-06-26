<template>
  <div class="document-workflow">
    <!-- 步骤导航 -->
    <n-card class="mb-6">
      <n-steps :current="visualStep" :status="stepStatus">
        <n-step title="上传文档" description="上传API文档文件" />
        <n-step title="文档解析" description="智能解析API结构" />
        <n-step title="接口分析" description="深度分析API接口" />
        <n-step title="生成测试" description="生成测试脚本" />
      </n-steps>
    </n-card>

    <!-- 步骤1: 文档上传 -->
    <n-card v-if="currentStep === 1" title="上传API文档" class="mb-6">
      <div class="upload-section">
        <n-upload
          ref="uploadRef"
          :file-list="fileList"
          :max="1"
          accept=".json,.yaml,.yml,.pdf"
          :default-upload="false"
          @before-upload="beforeUpload"
          @change="handleFileChange"
        >
          <n-upload-dragger>
            <div style="margin-bottom: 12px">
              <n-icon size="48" :depth="3">
                <Icon icon="mdi:cloud-upload" />
              </n-icon>
            </div>
            <n-text style="font-size: 16px"> 点击或者拖动文件到该区域来上传 </n-text>
            <n-p depth="3" style="margin: 8px 0 0 0">
              支持 OpenAPI/Swagger (.json, .yaml)、Postman Collection (.json) 和 PDF 接口文档格式
            </n-p>
            <n-p depth="3" style="margin: 4px 0 0 0; font-size: 12px; color: #f0a020;">
              提示：预分析依赖 JSON 文件（含 chains/dependencies 结构）请使用 Step 3 的「快速导入」通道
            </n-p>
          </n-upload-dragger>
        </n-upload>

        <div v-if="selectedFile" class="mt-4">
          <n-alert type="info" title="文件已选择">
            文件: {{ selectedFile.name }} ({{ formatFileSize(selectedFile.size) }})
          </n-alert>

          <div class="mt-4 flex justify-end">
            <n-button type="primary" :loading="uploading || parsing" @click="uploadAndParse">
              {{ uploading ? '上传中...' : parsing ? '解析中...' : '上传并解析' }}
            </n-button>
          </div>
        </div>

        <div v-if="uploadedFile && !parsing" class="mt-4">
          <n-alert type="success" title="文件上传成功">
            文件: {{ uploadedFile.name }} ({{ formatFileSize(uploadedFile.size) }})
          </n-alert>
        </div>
      </div>
    </n-card>

    <!-- 步骤2: 文档解析 -->
    <n-card v-if="currentStep === 2" title="文档解析中" class="mb-6">
      <div class="parsing-section">
        <div class="mb-4 flex items-center">
          <n-spin size="small" />
          <span class="ml-2">{{ parsingStatus }}</span>
        </div>

        <n-progress
          type="line"
          :percentage="parsingProgress"
          :show-indicator="true"
          status="active"
        />

        <!-- 实时解析日志 -->
        <div class="mt-4">
          <n-collapse>
            <n-collapse-item title="解析日志" name="logs">
              <div
                class="h-48 overflow-y-auto rounded bg-black p-4 text-sm font-mono text-green-400"
              >
                <div v-for="(log, index) in parsingLogs" :key="index" class="mb-1">
                  <span class="text-gray-500">[{{ formatTime(log.timestamp) }}]</span>
                  <span>{{ log.message }}</span>
                </div>
              </div>
            </n-collapse-item>
          </n-collapse>
        </div>
      </div>
    </n-card>

    <!-- 步骤3: 解析结果 -->
    <n-card v-if="currentStep === 3" title="解析结果" class="mb-6">
      <!-- ========== 0 接口：依赖 JSON 快速导入通道 ========== -->
      <template v-if="parseResult && parseResult.endpointsCount === 0">
        <n-alert type="warning" title="未解析到标准 API 接口" class="mb-4">
          <p>当前文档未检测到 OpenAPI/Swagger/Postman 标准接口结构。</p>
          <p>
            如果该文件是<strong>预分析依赖 JSON</strong>（含 chains / dependencies / baseUrl 字段），
            请直接使用下方通道导入，可跳过分析流程生成场景测试脚本。
          </p>
        </n-alert>

        <n-card title="快速导入：预分析依赖 JSON → 场景测试脚本" size="small" class="mb-4">
          <n-alert type="info" :bordered="false" class="mb-4">
            上传预分析依赖 JSON 文件（如 ai-testmind 产出的依赖分析文件），
            将直接通过模板渲染生成场景测试脚本，不经过 ApiAnalyzer / TestCaseGenerator。
          </n-alert>
          <div class="dependency-import-upload">
            <n-input
              v-model:value="depImportDisplayName"
              placeholder="用例名称（中文，必填）"
              clearable
              maxlength="64"
              show-count
              style="margin-bottom: 12px"
            />
            <!-- 已上传文件可复用：识别为依赖 JSON 时直接展示，不再要求重新选 -->
            <n-alert
              v-if="uploadedFile?.docId"
              type="success"
              :bordered="false"
              class="mb-3"
            >
              已识别为依赖 JSON，将使用 Step 1 上传的文件：
              <strong>{{ uploadedFile.name }}</strong>
            </n-alert>

            <!-- 兜底：docId 不可用时退化为传统手选 -->
            <template v-else>
              <n-upload
                ref="depImportUploadRef"
                :max="1"
                accept=".json"
                :default-upload="false"
                @change="handleDepImportFileChange"
              >
                <n-button>选择依赖 JSON</n-button>
              </n-upload>
              <div v-if="depImportFile" class="mt-2">
                <n-tag type="info">{{ depImportFile.name }}</n-tag>
              </div>
            </template>
            <div class="mt-4 flex items-center gap-3">
              <n-button
                type="primary"
                :loading="depImporting"
                :disabled="
                  uploadedFile?.docId
                    ? !depImportDisplayName?.trim()
                    : !depImportFile || !depImportDisplayName?.trim()
                "
                @click="handleDepImportSubmit"
              >
                导入并生成场景脚本
              </n-button>
              <n-button v-if="depImportTaskId" size="small" @click="checkDepImportResult">
                查询结果
              </n-button>
            </div>
            <n-alert
              v-if="depImportAlert"
              :type="depImportAlert.type"
              class="mt-4"
              :title="depImportAlert.title"
            >
              {{ depImportAlert.msg }}
              <div v-if="depImportAlert.data" class="mt-2 text-sm">
                <div>场景数: {{ depImportAlert.data.scenariosCount }}</div>
                <div v-if="depImportAlert.data.endpointsCount">
                  接口数: {{ depImportAlert.data.endpointsCount }}
                </div>
                <div v-if="depImportAlert.data.testCasesCount">
                  测试用例: {{ depImportAlert.data.testCasesCount }}
                </div>
                <div v-if="depImportAlert.data.scriptsExpected">
                  预期脚本: {{ depImportAlert.data.scriptsExpected }}
                </div>
              </div>
              <div v-if="depImportAlert.data?.scriptsExpected" class="mt-2">
                <n-button size="small" @click="goToScriptManagement">去脚本管理查看</n-button>
              </div>
            </n-alert>
          </div>
        </n-card>

        <div class="flex justify-between">
          <n-button @click="currentStep = 1">重新上传其他文档</n-button>
        </div>
      </template>

      <!-- ========== 有接口：正常流程 ========== -->
      <div v-else-if="parseResult">
        <!-- 解析摘要 -->
        <div class="grid grid-cols-1 mb-6 gap-4 md:grid-cols-4">
          <n-statistic label="接口数量" :value="parseResult.endpointsCount" />
          <n-statistic label="数据模型" :value="parseResult.schemasCount" />
          <n-statistic label="解析置信度" :value="`${parseResult.confidenceScore}%`" />
          <n-statistic label="处理时间" :value="`${parseResult.processingTime}s`" />
        </div>

        <!-- 接口列表预览 -->
        <n-tabs type="line" class="mb-4">
          <n-tab-pane name="endpoints" tab="接口列表">
            <n-data-table
              :columns="endpointColumns"
              :data="parseResult.endpoints || []"
              :pagination="{ pageSize: 10 }"
              max-height="400"
            />
          </n-tab-pane>

          <n-tab-pane name="schemas" tab="数据模型">
            <n-tree :data="schemaTreeData" :render-label="renderSchemaLabel" block-line />
          </n-tab-pane>
        </n-tabs>

        <div class="flex justify-between">
          <n-button @click="currentStep = 1">重新上传</n-button>
          <n-space>
            <n-button type="primary" :loading="directGenerating" @click="directGenerateTests">
              直接生成测试用例
            </n-button>
            <n-button @click="startAnalysis"> 开始接口分析 </n-button>
          </n-space>
        </div>

        <!-- 直接生成进度 -->
        <div v-if="directGenerating" class="mt-4 border rounded p-4">
          <div class="mb-2 flex items-center">
            <n-spin size="small" />
            <span class="ml-2">{{ directGenStatus }}</span>
          </div>
          <n-progress
            type="line"
            :percentage="directGenProgress"
            :show-indicator="true"
            status="active"
          />
        </div>
        <div v-else-if="directGenResult" class="mt-4">
          <n-alert type="success" title="测试用例生成完成" class="mb-2">
            已生成 {{ directGenResult.scriptsCount || 0 }} 个测试脚本，包含
            {{ directGenResult.totalTestCases || 0 }} 个测试用例
          </n-alert>
          <div class="flex justify-end">
            <n-button size="small" @click="goToScriptManagement">管理测试脚本</n-button>
          </div>
        </div>
        <n-alert
          v-else-if="directGenError"
          type="error"
          title="生成失败"
          class="mt-4"
          closable
          @close="directGenError = null"
        >
          {{ directGenError }}
        </n-alert>

        <!-- 依赖 JSON 导入旁路 -->
        <n-divider />
        <n-collapse class="mt-2">
          <n-collapse-item
            title="快速导入：预分析依赖 JSON 直接生成脚本（跳过分析流程）"
            name="dependency-import"
          >
            <n-alert type="info" :bordered="false" class="mb-4">
              上传预分析依赖 JSON 文件（如 ai-testmind 产出的依赖分析文件），
              将直接通过模板渲染生成场景测试脚本，不经过 ApiAnalyzer / TestCaseGenerator。
            </n-alert>
            <div class="dependency-import-upload">
              <n-upload
                ref="depImportUploadRef"
                :max="1"
                accept=".json"
                :default-upload="false"
                @change="handleDepImportFileChange"
              >
                <n-button>选择依赖 JSON</n-button>
              </n-upload>
              <div v-if="depImportFile" class="mt-2">
                <n-tag type="info">{{ depImportFile.name }}</n-tag>
              </div>
              <div class="mt-4 flex items-center gap-3">
                <n-button
                  type="primary"
                  secondary
                  :loading="depImporting"
                  :disabled="!depImportFile || !depImportDisplayName?.trim()"
                  @click="importDependencyDoc"
                >
                  导入并生成场景脚本
                </n-button>
                <n-button v-if="depImportTaskId" size="small" @click="checkDepImportResult">
                  查询结果
                </n-button>
              </div>
              <n-alert
                v-if="depImportAlert"
                :type="depImportAlert.type"
                class="mt-4"
                :title="depImportAlert.title"
              >
                {{ depImportAlert.msg }}
                <div v-if="depImportAlert.data" class="mt-2 text-sm">
                  <div>场景数: {{ depImportAlert.data.scenariosCount }}</div>
                  <div v-if="depImportAlert.data.endpointsCount">
                    接口数: {{ depImportAlert.data.endpointsCount }}
                  </div>
                  <div v-if="depImportAlert.data.testCasesCount">
                    测试用例: {{ depImportAlert.data.testCasesCount }}
                  </div>
                  <div v-if="depImportAlert.data.scriptsExpected">
                    预期脚本: {{ depImportAlert.data.scriptsExpected }}
                  </div>
                </div>
                <div v-if="depImportAlert.data?.scriptsExpected" class="mt-2">
                  <n-button size="small" @click="goToScriptManagement">去脚本管理查看</n-button>
                </div>
              </n-alert>
            </div>
          </n-collapse-item>
        </n-collapse>
      </div>
    </n-card>

    <!-- 步骤4: 接口分析 -->
    <n-card v-if="currentStep === 4" title="接口分析" class="mb-6">
      <div v-if="!analyzing">
        <!-- 分析配置 -->
        <n-form
          ref="analysisFormRef"
          :model="analysisConfig"
          label-placement="left"
          label-width="120px"
        >
          <div class="grid grid-cols-1 gap-6 md:grid-cols-2">
            <div>
              <n-form-item label="分析类型">
                <n-checkbox-group v-model:value="analysisConfig.analysisTypes">
                  <n-space vertical>
                    <n-checkbox value="dependency">依赖关系分析</n-checkbox>
                    <n-checkbox value="security">安全性评估</n-checkbox>
                    <n-checkbox value="performance">性能分析</n-checkbox>
                    <n-checkbox value="complexity">复杂度评估</n-checkbox>
                  </n-space>
                </n-checkbox-group>
              </n-form-item>
            </div>

            <div>
              <n-form-item label="分析深度">
                <n-radio-group v-model:value="analysisConfig.depth">
                  <n-space vertical>
                    <n-radio value="basic">基础分析</n-radio>
                    <n-radio value="detailed">详细分析</n-radio>
                    <n-radio value="comprehensive">全面分析</n-radio>
                  </n-space>
                </n-radio-group>
              </n-form-item>
            </div>
          </div>

          <n-form-item>
            <n-button type="primary" :loading="analyzing" @click="executeAnalysis">
              执行分析
            </n-button>
          </n-form-item>
        </n-form>
      </div>

      <!-- 分析进行中 -->
      <div v-if="analyzing" class="analysis-progress">
        <div class="mb-4 flex items-center">
          <n-spin size="small" />
          <span class="ml-2">{{ analysisStatus }}</span>
        </div>

        <n-progress
          type="line"
          :percentage="analysisProgress"
          :show-indicator="true"
          status="active"
        />
      </div>

      <!-- 分析结果 -->
      <div v-if="analysisResult" class="analysis-result mt-6">
        <n-alert type="success" title="分析完成" class="mb-4">
          接口分析已完成，发现 {{ analysisResult.totalEndpoints }} 个接口，
          {{ analysisResult.dependenciesCount }} 个依赖关系
        </n-alert>

        <div class="flex justify-between">
          <n-button @click="viewAnalysisDetail">查看详细分析</n-button>
          <n-button type="primary" @click="proceedToTestGeneration"> 生成测试脚本 </n-button>
        </div>
      </div>
    </n-card>

    <!-- 步骤5: 测试生成 -->
    <n-card v-if="currentStep === 5" title="生成测试脚本" class="mb-6">
      <div v-if="!generating">
        <!-- 测试生成配置 -->
        <n-form
          ref="generationFormRef"
          :model="generationConfig"
          label-placement="left"
          label-width="120px"
        >
          <div class="grid grid-cols-1 gap-6 md:grid-cols-2">
            <div>
              <n-form-item label="测试框架">
                <n-select v-model:value="generationConfig.framework" :options="frameworkOptions" />
              </n-form-item>

              <n-form-item label="测试类型">
                <n-checkbox-group v-model:value="generationConfig.testTypes">
                  <n-space vertical>
                    <n-checkbox value="functional">功能测试</n-checkbox>
                    <n-checkbox value="boundary">边界测试</n-checkbox>
                    <n-checkbox value="security">安全测试</n-checkbox>
                    <n-checkbox value="performance">性能测试</n-checkbox>
                  </n-space>
                </n-checkbox-group>
              </n-form-item>
            </div>

            <div>
              <n-form-item label="测试级别">
                <n-radio-group v-model:value="generationConfig.testLevel">
                  <n-space vertical>
                    <n-radio value="unit">单元测试</n-radio>
                    <n-radio value="integration">集成测试</n-radio>
                    <n-radio value="e2e">端到端测试</n-radio>
                  </n-space>
                </n-radio-group>
              </n-form-item>

              <n-form-item label="生成选项">
                <n-checkbox-group v-model:value="generationConfig.options">
                  <n-space vertical>
                    <n-checkbox value="mock_data">生成模拟数据</n-checkbox>
                    <n-checkbox value="assertions">智能断言</n-checkbox>
                    <n-checkbox value="error_handling">错误处理</n-checkbox>
                    <n-checkbox value="documentation">测试文档</n-checkbox>
                  </n-space>
                </n-checkbox-group>
              </n-form-item>
            </div>
          </div>

          <n-form-item>
            <n-button type="primary" :loading="generating" @click="generateTests">
              生成测试脚本
            </n-button>
          </n-form-item>
        </n-form>
      </div>

      <!-- 生成进行中 -->
      <div v-if="generating" class="generation-progress">
        <div class="mb-4 flex items-center">
          <n-spin size="small" />
          <span class="ml-2">{{ generationStatus }}</span>
        </div>

        <n-progress
          type="line"
          :percentage="generationProgress"
          :show-indicator="true"
          status="active"
        />
      </div>

      <!-- 生成结果 -->
      <div v-if="generationResult" class="generation-result mt-6">
        <n-alert type="success" title="测试脚本生成完成" class="mb-4">
          已生成 {{ generationResult.totalTestFiles }} 个测试文件， 包含
          {{ generationResult.totalTestCases }} 个测试用例
        </n-alert>

        <div class="grid grid-cols-1 mb-4 gap-4 md:grid-cols-3">
          <n-statistic label="测试文件" :value="generationResult.totalTestFiles" />
          <n-statistic label="测试用例" :value="generationResult.totalTestCases" />
          <n-statistic label="覆盖率评分" :value="`${generationResult.coverageScore}%`" />
        </div>

        <div class="flex justify-between">
          <n-space>
            <n-button @click="previewTestScripts">预览脚本</n-button>
            <n-button @click="downloadTestScripts">下载脚本</n-button>
          </n-space>
          <n-button type="primary" @click="goToTestManagement"> 管理测试脚本 </n-button>
        </div>
      </div>
    </n-card>

    <!-- 重复接口确认弹窗 -->
    <n-modal
      v-model:show="duplicatesModal"
      preset="card"
      title="检测到重复接口"
      style="width: 800px"
      :mask-closable="false"
      :close-on-esc="false"
      :closable="false"
    >
      <n-alert type="warning" class="mb-4">
        以下 {{ pendingDuplicatesList.length }} 个接口与已有文档中的接口存在重复（method + path
        相同）。 请逐一选择处理方式后提交。
      </n-alert>

      <n-data-table
        :columns="duplicateColumns"
        :data="pendingDuplicatesList"
        :pagination="{ pageSize: 10 }"
        max-height="400"
        :row-key="(row) => row.fingerprint"
      />

      <div class="mt-4 flex items-center justify-between">
        <n-space>
          <n-button size="small" @click="batchSetAction('overwrite')">全部使用新版本</n-button>
          <n-button size="small" @click="batchSetAction('keep_existing')">全部保留旧版本</n-button>
        </n-space>
        <n-space>
          <n-button @click="duplicatesModal = false">稍后处理</n-button>
          <n-button
            type="primary"
            :loading="resolvingDuplicates"
            :disabled="!allResolved"
            @click="submitResolveDuplicates"
          >
            提交（已选 {{ resolvedCount }}/{{ pendingDuplicatesList.length }}）
          </n-button>
        </n-space>
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NTag, NRadioGroup, NRadio, NSpace, useMessage, useDialog } from 'naive-ui'
import { Icon } from '@iconify/vue'
import api from '@/api'
import { formatTime, formatFileSize } from '@/utils'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()

// 当前步骤
const currentStep = ref(1)
const stepStatus = ref('process')

// 步骤条显示用的视觉步骤（步骤条只有 4 个节点，但 currentStep 有 5 个）
// 1=上传 / 2=解析中 / 3=解析结果 / 4=接口分析 / 5=生成测试
const visualStep = computed(() => {
  const step = currentStep.value
  if (step <= 2) return step // 上传 / 解析
  if (step === 3 || step === 4) return 3 // 解析结果 + 接口分析 都算"接口分析"步
  return 4 // 生成测试
})

// 文件上传
const uploadRef = ref()
const fileList = ref([])
const selectedFile = ref(null)
const uploadedFile = ref(null)
const uploading = ref(false)

// 解析状态
const parsing = ref(false)
const parsingStatus = ref('')
const parsingProgress = ref(0)
const parsingLogs = ref([])
const parseResult = ref(null)

// 重复接口确认弹窗
const duplicatesModal = ref(false)
const pendingDuplicatesList = ref([])
const resolutions = ref({}) // { fingerprint: 'overwrite' | 'keep_existing' }
const resolvingDuplicates = ref(false)
const currentDocId = ref(null)

// 分析状态
const analyzing = ref(false)
const analysisStatus = ref('')
const analysisProgress = ref(0)
const analysisResult = ref(null)
const analysisConfig = ref({
  analysisTypes: ['dependency', 'security'],
  depth: 'detailed',
})

// 生成状态
const generating = ref(false)
const generationStatus = ref('')
const generationProgress = ref(0)
const generationResult = ref(null)
const generationConfig = ref({
  framework: 'pytest',
  testTypes: ['functional'],
  testLevel: 'integration',
  options: ['mock_data', 'assertions'],
})

// 直接生成测试用例
const directGenerating = ref(false)
const directGenProgress = ref(0)
const directGenStatus = ref('')
const directGenResult = ref(null)
const directGenError = ref(null)

// 依赖 JSON 导入
const depImportUploadRef = ref()
const depImportFile = ref(null)
const depImportDisplayName = ref('')
const depImporting = ref(false)
const depImportTaskId = ref(null)
const depImportDocId = ref(null)
const depImportAlert = ref(null)

const handleDepImportFileChange = ({ fileList: newFileList }) => {
  if (newFileList.length > 0) {
    depImportFile.value = newFileList[0].file
    depImportAlert.value = null
  } else {
    depImportFile.value = null
  }
}

const importDependencyDoc = async () => {
  if (!depImportFile.value) return
  const displayName = (depImportDisplayName.value || '').trim()
  if (!displayName) {
    depImportAlert.value = {
      type: 'warning',
      title: '请填写用例名称',
      msg: '用例名称（中文）必填，将作为脚本管理列表显示的用例名',
      data: null,
    }
    return
  }
  const formData = new FormData()
  formData.append('file', depImportFile.value)
  formData.append('display_name', displayName)
  await _runDepImport(formData)
}

// Step 3「0 接口」分支：复用 Step 1 已上传文件，不再要求重新选
const importDependencyDocFromUploaded = async () => {
  if (!uploadedFile.value?.docId) {
    depImportAlert.value = {
      type: 'error',
      title: '缺少文档 ID',
      msg: '请重新上传文件',
      data: null,
    }
    return
  }
  const displayName = (depImportDisplayName.value || '').trim()
  if (!displayName) {
    depImportAlert.value = {
      type: 'warning',
      title: '请填写用例名称',
      msg: '用例名称（中文）必填，将作为脚本管理列表显示的用例名',
      data: null,
    }
    return
  }
  const formData = new FormData()
  formData.append('display_name', displayName)
  formData.append('from_doc_id', uploadedFile.value.docId)
  await _runDepImport(formData)
}

// 统一的提交入口：模板上的「导入并生成场景脚本」按钮调用
// 有 docId → 复用 Step 1 文件；否则 → 走传统手选上传
const handleDepImportSubmit = async () => {
  if (uploadedFile.value?.docId) {
    await importDependencyDocFromUploaded()
  } else {
    await importDependencyDoc()
  }
}

// 共享提交逻辑：发请求 + 处理成功/失败 alert
const _runDepImport = async (formData) => {
  depImporting.value = true
  depImportAlert.value = null
  try {
    const resp = await api.importDependencyDoc(formData)

    if (resp.success) {
      depImportTaskId.value = resp.data.taskId
      depImportDocId.value = resp.data.docId
      depImportAlert.value = {
        type: 'success',
        title: '导入成功，脚本正在生成中',
        msg: `已提交 ${resp.data.scenariosCount} 个场景，预期生成 ${resp.data.scriptsExpected} 个脚本文件`,
        data: resp.data,
      }
    } else {
      depImportAlert.value = {
        type: 'error',
        title: '导入失败',
        msg: resp.msg || '请检查文件格式',
        data: null,
      }
    }
  } catch (err) {
    const detail = err?.response?.data?.detail || err.message || '未知错误'
    depImportAlert.value = {
      type: 'error',
      title: '导入失败',
      msg: detail,
      data: null,
    }
  } finally {
    depImporting.value = false
  }
}

const checkDepImportResult = async () => {
  if (!depImportTaskId.value) return
  try {
    const resp = await api.getDependencyImportResult({
      taskId: depImportTaskId.value,
      docId: depImportDocId.value,
    })
    if (resp.success) {
      const status = resp.data?.status
      if (status === 'completed') {
        depImportAlert.value = {
          type: 'success',
          title: '脚本生成完成',
          msg: `共生成 ${resp.data.scriptsCount} 个脚本文件`,
          data: { scriptsExpected: resp.data.scriptsCount },
        }
      } else if (status === 'failed') {
        depImportAlert.value = {
          type: 'error',
          title: '脚本生成失败',
          msg: resp.msg || '请查看日志',
          data: null,
        }
      } else {
        depImportAlert.value = {
          type: 'warning',
          title: '生成进行中',
          msg: '脚本仍在生成中，请稍后查询',
          data: null,
        }
      }
    }
  } catch (err) {
    depImportAlert.value = {
      type: 'error',
      title: '查询失败',
      msg: err?.response?.data?.detail || err.message || '未知错误',
      data: null,
    }
  }
}

const goToScriptManagement = () => {
  router.push('/api-automation/script-management')
}

// 选项数据
const frameworkOptions = [
  { label: 'pytest', value: 'pytest' },
  { label: 'unittest', value: 'unittest' },
  { label: 'requests', value: 'requests' },
]

// 表格列定义
const endpointColumns = [
  { title: '方法', key: 'method', width: 80 },
  { title: '路径', key: 'path', width: 200 },
  { title: '摘要', key: 'summary', ellipsis: true },
  {
    title: '认证',
    key: 'authRequired',
    width: 80,
    render: (row) => (row.authRequired ? '是' : '否'),
  },
  {
    title: '操作',
    key: 'actions',
    width: 80,
    render(row) {
      return h(NButton, {
        size: 'tiny',
        type: 'error',
        onClick: () => deleteEndpoint(row),
      }, {
        default: () => '删除',
        icon: () => h(Icon, { icon: 'mdi:delete' }),
      })
    },
  },
]

const deleteEndpoint = (row) => {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除接口 "${row.method} ${row.path}" 吗？`,
    positiveText: '确定',
    onPositiveClick: async () => {
      try {
        await api.deleteApiInterface(row.endpoint_id)
        message.success('已删除')
        const endpoints = parseResult.value?.endpoints
        if (endpoints) {
          const idx = endpoints.findIndex((e) => e.endpoint_id === row.endpoint_id)
          if (idx !== -1) endpoints.splice(idx, 1)
          parseResult.value.endpointsCount = endpoints.length
        }
      } catch (error) {
        message.error('删除失败')
      }
    },
  })
}

// 计算属性
const schemaTreeData = computed(() => {
  if (!parseResult.value?.schemas) return []
  return Object.keys(parseResult.value.schemas).map((key) => ({
    label: key,
    key: key,
    children: [],
  }))
})

// 重复接口弹窗计算属性
const resolvedCount = computed(() => {
  return pendingDuplicatesList.value.filter((d) => resolutions.value[d.fingerprint]).length
})
const allResolved = computed(() => {
  return (
    pendingDuplicatesList.value.length > 0 &&
    resolvedCount.value === pendingDuplicatesList.value.length
  )
})

// 重复接口表格列
const duplicateColumns = [
  {
    title: '方法',
    key: 'method',
    width: 80,
    render: (row) => h(NTag, { type: 'info', size: 'small' }, { default: () => row.method }),
  },
  { title: '路径', key: 'path', width: 220, ellipsis: { tooltip: true } },
  {
    title: '新接口',
    key: 'new_name',
    ellipsis: { tooltip: true },
    render: (row) => row.new_name || '-',
  },
  {
    title: '已有接口（来自）',
    key: 'existing',
    ellipsis: { tooltip: true },
    render: (row) => `${row.existing_name || '-'} (${row.existing_document_name || '未知文档'})`,
  },
  {
    title: '处理方式',
    key: 'action',
    width: 230,
    render: (row) =>
      h(
        NRadioGroup,
        {
          value: resolutions.value[row.fingerprint] || null,
          'onUpdate:value': (v) => {
            resolutions.value = { ...resolutions.value, [row.fingerprint]: v }
          },
        },
        {
          default: () =>
            h(NSpace, null, {
              default: () => [
                h(NRadio, { value: 'overwrite' }, { default: () => '使用新版本' }),
                h(NRadio, { value: 'keep_existing' }, { default: () => '保留旧版本' }),
              ],
            }),
        }
      ),
  },
]

// 方法
const beforeUpload = (data) => {
  const { file } = data

  console.log('文件上传检查:', {
    name: file.name,
    type: file.type,
    size: file.size,
    sizeInMB: (file.size / 1024 / 1024).toFixed(2),
  })

  // 支持的文件类型（包含各种可能的MIME类型）
  const supportedTypes = [
    // JSON格式
    'application/json',
    'text/json',
    'text/plain', // 有时JSON文件被识别为text/plain

    // YAML格式
    'text/yaml',
    'text/x-yaml',
    'application/x-yaml',
    'application/yaml',

    // PDF格式
    'application/pdf',
  ]

  const supportedExtensions = ['.json', '.yaml', '.yml', '.pdf']

  // 检查文件类型
  const fileName = file.name.toLowerCase()
  const fileType = file.type.toLowerCase()

  const isValidType =
    supportedTypes.includes(fileType) || supportedExtensions.some((ext) => fileName.endsWith(ext))

  if (!isValidType) {
    message.error(`不支持的文件格式。文件: ${file.name}, 类型: ${file.type}`)
    return false
  }

  // 判断是否为PDF文件
  const isPdfFile = fileName.endsWith('.pdf') || fileType === 'application/pdf'

  // 根据文件类型设置大小限制
  const maxSize = isPdfFile ? 50 : 10 // PDF: 50MB, 其他: 10MB
  const fileSizeInMB = file.size / 1024 / 1024

  console.log('文件大小检查:', {
    isPdfFile,
    maxSize,
    fileSizeInMB: fileSizeInMB.toFixed(2),
    isValid: fileSizeInMB < maxSize,
  })

  if (fileSizeInMB >= maxSize) {
    message.error(`文件大小 ${fileSizeInMB.toFixed(2)}MB 超过限制 ${maxSize}MB`)
    return false
  }

  // 文件大小为0的检查
  if (file.size === 0) {
    message.error('文件为空，请选择有效的文件')
    return false
  }

  message.success(`文件检查通过: ${file.name} (${fileSizeInMB.toFixed(2)}MB)`)
  return true
}

const handleUploadFinish = ({ file, event }) => {
  try {
    const response = JSON.parse(event.target.response)
    if (response.success) {
      uploadedFile.value = {
        name: file.name,
        size: file.size,
        docId: response.data.docId,
      }
      message.success('文件上传成功')
    } else {
      message.error(response.message || '上传失败')
    }
  } catch (error) {
    message.error('上传响应解析失败')
  }
}

const handleUploadError = () => {
  message.error('文件上传失败')
}

const handleFileChange = ({ fileList: newFileList }) => {
  fileList.value = newFileList
  if (newFileList.length > 0) {
    selectedFile.value = newFileList[0].file
    console.log('选择的文件:', selectedFile.value)
  } else {
    selectedFile.value = null
  }
}

const uploadAndParse = async () => {
  if (!selectedFile.value) {
    message.error('请先选择文件')
    return
  }

  uploading.value = true

  try {
    console.log('开始上传文件:', selectedFile.value.name)

    // 创建FormData
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    formData.append('doc_format', 'auto')
    formData.append('auto_parse', 'true') // 启用自动解析
    formData.append(
      'config',
      JSON.stringify({
        extractSchemas: true,
        analyzeDependencies: true,
        generateExamples: true,
        isPdfDocument: selectedFile.value.name.toLowerCase().endsWith('.pdf'),
      })
    )

    // 调用上传API
    const response = await api.uploadDocument(formData)

    console.log('上传响应:', response)

    if (response.success) {
      uploadedFile.value = {
        name: selectedFile.value.name,
        size: selectedFile.value.size,
        docId: response.data.docId,
        sessionId: response.data.sessionId,
        status: response.data.status,
        autoParse: response.data.autoParse,
      }

      message.success('文件上传成功')

      // 如果启用了自动解析，开始监控解析状态
      if (response.data.autoParse && response.data.status === 'parsing') {
        currentStep.value = 2
        parsing.value = true
        parsingStatus.value = '文档上传成功，正在后台解析...'
        parsingProgress.value = 10

        // 开始轮询解析状态
        await monitorParsingStatus(response.data.sessionId)
      } else {
        // 手动解析模式，显示解析按钮
        currentStep.value = 2
      }
    } else {
      message.error(response.message || '文件上传失败')
    }
  } catch (error) {
    console.error('上传失败:', error)
    message.error(`文件上传失败: ${error.message || '未知错误'}`)
  } finally {
    uploading.value = false
  }
}

// 监控解析状态
const monitorParsingStatus = async (sessionId) => {
  const maxAttempts = 60 // 最多查询60次（5分钟）
  let attempts = 0

  const checkStatus = async () => {
    try {
      attempts++
      console.log(`查询解析状态 (${attempts}/${maxAttempts}):`, sessionId)

      const response = await api.getParseStatus(sessionId)

      if (response.success) {
        const { status, progress, message: statusMessage, result } = response.data

        // 更新进度
        parsingProgress.value = progress || 0
        parsingStatus.value = statusMessage || '正在解析...'

        console.log(`解析状态: ${status}, 进度: ${progress}%`)

        if (status === 'completed') {
          // 解析完成
          parsing.value = false
          currentStep.value = 3
          parsingProgress.value = 100
          parsingStatus.value = '文档解析完成'

          if (result) {
            parseResult.value = result
            currentDocId.value = result.docId || null

            // 检测是否存在重复接口待用户确认
            const pendings = result.pendingDuplicates
            if (Array.isArray(pendings) && pendings.length > 0) {
              pendingDuplicatesList.value = pendings
              resolutions.value = {}
              duplicatesModal.value = true
              message.warning(`检测到 ${pendings.length} 个重复接口，请确认处理方式`)
            } else {
              message.success('文档解析完成！')
            }
          }

          return true // 完成
        } else if (status === 'failed') {
          // 解析失败
          parsing.value = false
          parsingProgress.value = 0
          parsingStatus.value = `解析失败: ${response.data.error || '未知错误'}`
          message.error('文档解析失败')

          return true // 结束
        } else if (status === 'parsing' || status === 'processing') {
          // 继续解析中
          return false // 继续监控
        } else {
          // 其他状态
          console.warn('未知解析状态:', status)
          return false
        }
      } else {
        console.error('查询解析状态失败:', response.message)
        return false
      }
    } catch (error) {
      console.error('查询解析状态异常:', error)
      return false
    }
  }

  // 开始轮询
  const pollInterval = setInterval(async () => {
    const isComplete = await checkStatus()

    if (isComplete || attempts >= maxAttempts) {
      clearInterval(pollInterval)

      if (attempts >= maxAttempts && parsing.value) {
        // 超时处理
        parsing.value = false
        parsingStatus.value = '解析超时，请手动查询状态'
        message.warning('解析查询超时，请手动刷新页面查看结果')
      }
    }
  }, 5000) // 每5秒查询一次

  // 立即执行一次
  const isComplete = await checkStatus()
  if (isComplete) {
    clearInterval(pollInterval)
  }
}

// 批量设置所有重复项的处理方式
const batchSetAction = (action) => {
  const next = {}
  for (const item of pendingDuplicatesList.value) {
    next[item.fingerprint] = action
  }
  resolutions.value = next
}

// 提交重复接口的处理决策
const submitResolveDuplicates = async () => {
  if (!currentDocId.value) {
    message.error('缺少文档ID，无法提交')
    return
  }
  if (!allResolved.value) {
    message.warning('请为每一个重复接口选择处理方式')
    return
  }

  resolvingDuplicates.value = true
  try {
    const resolutionList = pendingDuplicatesList.value.map((item) => ({
      fingerprint: item.fingerprint,
      action: resolutions.value[item.fingerprint],
    }))

    const response = await api.resolveDuplicates({
      doc_id: currentDocId.value,
      resolutions: resolutionList,
    })

    if (response.success) {
      const { overwritten = 0, skipped = 0 } = response.data || {}
      message.success(`处理完成：覆盖 ${overwritten} 个，保留原有 ${skipped} 个`)
      duplicatesModal.value = false
      pendingDuplicatesList.value = []
      resolutions.value = {}

      // 重新拉取解析结果，刷新接口列表
      if (uploadedFile.value?.sessionId) {
        try {
          const refresh = await api.getParseStatus(uploadedFile.value.sessionId)
          if (refresh.success && refresh.data?.result) {
            parseResult.value = refresh.data.result
          }
        } catch (e) {
          console.warn('刷新解析结果失败:', e)
        }
      }
    } else {
      message.error(response.message || '处理失败')
    }
  } catch (error) {
    console.error('提交重复接口决策失败:', error)
    message.error(`提交失败: ${error.message || '未知错误'}`)
  } finally {
    resolvingDuplicates.value = false
  }
}

const startParsing = async () => {
  if (!uploadedFile.value) return

  parsing.value = true
  currentStep.value = 2

  // 根据文件类型设置不同的解析提示
  const isPdf = uploadedFile.value.name.toLowerCase().endsWith('.pdf')
  parsingStatus.value = isPdf ? '开始解析PDF文档，正在提取文本内容...' : '开始解析文档...'
  parsingProgress.value = 10

  try {
    // 手动触发解析
    const response = await api.triggerDocumentParse(uploadedFile.value.sessionId, {
      extractSchemas: true,
      analyzeDependencies: true,
      generateExamples: true,
      isPdfDocument: isPdf,
    })

    if (response.success) {
      message.success('解析已启动')

      // 开始监控解析状态
      await monitorParsingStatus(uploadedFile.value.sessionId)
    } else {
      throw new Error(response.message || '启动解析失败')
    }
  } catch (error) {
    parsing.value = false
    parsingProgress.value = 0
    parsingStatus.value = '解析失败'
    message.error(`解析失败: ${error.message}`)
  }
}

const startAnalysis = () => {
  currentStep.value = 4
}

const executeAnalysis = async () => {
  analyzing.value = true
  analysisStatus.value = '开始分析接口...'
  analysisProgress.value = 0

  try {
    const response = await api.analyzeApiEndpoints({
      docId: uploadedFile.value.docId,
      config: analysisConfig.value,
    })

    // 模拟分析进度
    const progressInterval = setInterval(() => {
      if (analysisProgress.value < 90) {
        analysisProgress.value += 15
        analysisStatus.value = `分析中... ${analysisProgress.value}%`
      }
    }, 1500)

    // 轮询分析结果（带错误重试上限，避免后端重启或 404 时无限轮询）
    let errorRetries = 0
    const MAX_ERROR_RETRIES = 5

    const stopWithError = (msg) => {
      clearInterval(progressInterval)
      analyzing.value = false
      analysisStatus.value = msg
      message.error(msg)
      // 失败时停留在"接口分析"步骤显示错误，不要静默回退到表单
      // 用户可以选择"重试"或返回上一步
    }

    const checkAnalysis = async () => {
      try {
        const result = await api.getAnalysisResult({
          analysisId: response.data.analysisId,
          docId: uploadedFile.value.docId,
        })
        errorRetries = 0
        const status = result?.data?.status
        if (status === 'completed') {
          clearInterval(progressInterval)
          analysisProgress.value = 100
          analysisStatus.value = '分析完成'
          analysisResult.value = result.data
          analyzing.value = false
        } else if (status === 'failed') {
          stopWithError(result?.msg || '分析失败')
        } else {
          setTimeout(checkAnalysis, 2000)
        }
      } catch (e) {
        errorRetries += 1
        if (errorRetries >= MAX_ERROR_RETRIES) {
          stopWithError(`分析状态查询失败：${e?.message || '请检查后端服务'}`)
          return
        }
        setTimeout(checkAnalysis, 2000)
      }
    }

    setTimeout(checkAnalysis, 2000)
  } catch (error) {
    analyzing.value = false
    message.error('启动分析失败')
  }
}

const proceedToTestGeneration = () => {
  currentStep.value = 5
}

const generateTests = async () => {
  generating.value = true
  generationStatus.value = '开始生成测试脚本...'
  generationProgress.value = 0

  try {
    const response = await api.generateTestScripts({
      docId: uploadedFile.value.docId,
      analysisId: analysisResult.value.analysisId,
      config: generationConfig.value,
    })

    // 模拟生成进度
    const progressInterval = setInterval(() => {
      if (generationProgress.value < 90) {
        generationProgress.value += 12
        generationStatus.value = `生成中... ${generationProgress.value}%`
      }
    }, 1200)

    let errorRetries = 0
    const MAX_ERROR_RETRIES = 5

    const stopWithError = (msg) => {
      clearInterval(progressInterval)
      generating.value = false
      generationStatus.value = msg
      message.error(msg)
    }

    // 轮询生成结果
    const checkGeneration = async () => {
      try {
        const result = await api.getGenerationResult({
          taskId: response.data.taskId,
          docId: uploadedFile.value.docId,
        })
        errorRetries = 0
        const status = result?.data?.status
        if (status === 'completed') {
          clearInterval(progressInterval)
          generationProgress.value = 100
          generationStatus.value = '生成完成'
          generationResult.value = result.data
          generating.value = false
        } else if (status === 'failed') {
          stopWithError(result?.msg || '生成失败')
        } else {
          setTimeout(checkGeneration, 2000)
        }
      } catch (e) {
        errorRetries += 1
        if (errorRetries >= MAX_ERROR_RETRIES) {
          stopWithError(`生成状态查询失败：${e?.message || '请检查后端服务'}`)
          return
        }
        setTimeout(checkGeneration, 2000)
      }
    }

    setTimeout(checkGeneration, 2000)
  } catch (error) {
    generating.value = false
    message.error('启动生成失败')
  }
}

const directGenerateTests = async () => {
  if (!uploadedFile.value?.docId) {
    message.error('请先上传文档')
    return
  }

  directGenerating.value = true
  directGenProgress.value = 0
  directGenStatus.value = '正在启动流水线...'
  directGenResult.value = null
  directGenError.value = null

  try {
    // Step 1: 触发分析流水线（自动链式触发 Analyzer → TestCaseGenerator → ScriptGenerator）
    directGenStatus.value = '正在分析接口...'
    const analysisResp = await api.analyzeApiEndpoints({
      docId: uploadedFile.value.docId,
      config: { analysisTypes: ['dependency', 'security'], depth: 'detailed' },
    })

    if (!analysisResp.success) {
      throw new Error(analysisResp.msg || '启动分析失败')
    }

    const analysisId = analysisResp.data.analysisId
    directGenProgress.value = 20

    // Step 2: 轮询结果（流水线完成后脚本落库，analysis-result 返回 scriptsCount）
    let errorRetries = 0
    const MAX_ERROR_RETRIES = 5

    const pollResult = await new Promise((resolve, reject) => {
      const check = async () => {
        try {
          const result = await api.getAnalysisResult({
            analysisId,
            docId: uploadedFile.value.docId,
          })
          errorRetries = 0

          const status = result?.data?.status
          if (status === 'completed') {
            directGenProgress.value = 95
            directGenStatus.value = '测试用例生成完成'
            resolve(result.data)
          } else if (status === 'failed') {
            reject(new Error(result?.msg || '生成失败'))
          } else {
            directGenProgress.value = Math.min(directGenProgress.value + 5, 80)
            directGenStatus.value = `生成中... ${Math.round(directGenProgress.value)}%`
            setTimeout(check, 2000)
          }
        } catch (e) {
          errorRetries += 1
          if (errorRetries >= MAX_ERROR_RETRIES) {
            reject(new Error(`查询失败：${e?.message || '请检查后端服务'}`))
          } else {
            setTimeout(check, 2000)
          }
        }
      }
      setTimeout(check, 2000)
    })

    directGenProgress.value = 100
    directGenStatus.value = '完成'
    directGenResult.value = pollResult
    message.success(`测试用例生成完成，共 ${pollResult.scriptsCount || 0} 个脚本`)
  } catch (error) {
    directGenError.value = error.message || '未知错误'
    directGenStatus.value = '失败'
    message.error(`生成失败: ${error.message}`)
  } finally {
    directGenerating.value = false
  }
}

const viewAnalysisDetail = () => {
  router.push({
    path: '/api-automation/analysis-detail',
    query: { analysisId: analysisResult.value.analysisId },
  })
}

const previewTestScripts = () => {
  const taskId = generationResult.value?.taskId
  if (!taskId) {
    message.warning('生成任务尚未就绪，请稍候再试')
    return
  }
  router.push({
    path: '/api-automation/script-preview',
    query: {
      taskId,
      docId: uploadedFile.value?.docId,
    },
  })
}

const downloadTestScripts = () => {
  // 下载测试脚本
  message.info('下载功能开发中...')
}

const goToTestManagement = () => {
  router.push('/api-automation/script-management')
}

const renderSchemaLabel = ({ option }) => {
  return h('span', option.label)
}

onMounted(() => {
  // 初始化
})
</script>

<style scoped>
.document-workflow {
  padding: 20px;
}

.upload-section {
  max-width: 600px;
  margin: 0 auto;
}

.parsing-section,
.analysis-progress,
.generation-progress {
  max-width: 800px;
  margin: 0 auto;
}
</style>

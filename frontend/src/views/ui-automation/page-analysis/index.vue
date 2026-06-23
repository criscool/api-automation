<template>
  <AppPage>
    <n-space vertical size="large">
      <!-- ============ 顶部：触发分析 ============ -->
      <n-card title="发起页面分析" size="small">
        <n-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-placement="left"
          label-width="100"
          require-mark-placement="right-hanging"
        >
          <n-grid :cols="24" :x-gap="16">
            <n-form-item-gi :span="8" label="分析模式" path="analysis_type">
              <n-radio-group v-model:value="form.analysis_type">
                <n-radio-button value="image">仅截图</n-radio-button>
                <n-radio-button value="text">仅文字</n-radio-button>
                <n-radio-button value="hybrid">图文混合</n-radio-button>
                <n-radio-button value="live_url">Live URL</n-radio-button>
              </n-radio-group>
            </n-form-item-gi>
            <n-form-item-gi :span="8" label="页面名称" path="page_name">
              <n-input v-model:value="form.page_name" placeholder="如：登录页 / 订单详情" maxlength="80" />
            </n-form-item-gi>
            <n-form-item-gi :span="8" label="页面 URL" path="page_url">
              <n-input v-model:value="form.page_url" placeholder="可选，便于脚本生成时定位" />
            </n-form-item-gi>

            <n-form-item-gi v-if="needScreenshot" :span="12" label="截图" path="screenshot_path">
              <n-space vertical style="width: 100%">
                <n-tabs v-model:value="screenshotSourceTab" type="segment" size="small" animated>
                  <n-tab-pane name="upload" tab="上传新截图">
                    <n-upload
                      ref="uploadRef"
                      accept="image/jpeg,image/png,image/webp,image/bmp"
                      :default-upload="false"
                      :max="1"
                      :show-file-list="false"
                      @change="onUploadChange"
                    >
                      <n-upload-dragger>
                        <div class="upload-tip">
                          <n-icon size="36" :depth="3">
                            <Icon icon="mdi:cloud-upload-outline" />
                          </n-icon>
                          <div>点击或拖拽页面截图到此处（jpg/png/webp/bmp，≤10MB）</div>
                          <div style="font-size: 11px; color: #aaa">
                            上传后会自动入图片库（SHA256 查重），可在「图片库」复用
                          </div>
                        </div>
                      </n-upload-dragger>
                    </n-upload>
                  </n-tab-pane>
                  <n-tab-pane name="library" tab="从图片库选择">
                    <n-space vertical>
                      <n-button block dashed @click="openLibraryPicker">
                        <template #icon>
                          <n-icon><Icon icon="mdi:image-multiple-outline" /></n-icon>
                        </template>
                        {{ form.image_id ? '已选择 · 点击重新选择' : '打开图片库挑选' }}
                      </n-button>
                      <n-text v-if="form.image_id" depth="3" style="font-size: 12px">
                        image_id：{{ form.image_id }}
                      </n-text>
                    </n-space>
                  </n-tab-pane>
                </n-tabs>
                <n-space v-if="uploadedFile" align="center">
                  <n-tag type="success" size="small">已就绪</n-tag>
                  <span class="upload-meta">
                    {{ uploadedFile.original_name || uploadedFile.title || uploadedFile.image_id }}
                    <template v-if="uploadedFile.size || uploadedFile.file_size">
                      · {{ formatBytes(uploadedFile.size || uploadedFile.file_size) }}
                    </template>
                  </span>
                  <n-button text type="error" size="tiny" @click="clearUpload">清除</n-button>
                </n-space>
                <n-image v-if="previewUrl" :src="previewUrl" width="220" style="border-radius: 6px" />
              </n-space>
            </n-form-item-gi>

            <n-form-item-gi v-if="needText" :span="12" label="文字需求" path="text_description">
              <n-input
                v-model:value="form.text_description"
                type="textarea"
                placeholder="自然语言描述测试场景，如：测试登录流程，输入正确账号密码后跳转到主页"
                :autosize="{ minRows: 4, maxRows: 8 }"
                maxlength="2000"
                show-count
              />
            </n-form-item-gi>

            <!-- ============ Live URL 模式专用(crawl4ai,2026-06-17 引入) ============ -->
            <n-form-item-gi v-if="needLiveUrl" :span="12" label="抓取 URL" path="live_url">
              <n-input
                v-model:value="form.live_url"
                placeholder="https://your-app.com/dashboard"
              />
            </n-form-item-gi>
            <n-form-item-gi v-if="needLiveUrl" :span="12" label="登录态文件" path="storage_state_relpath">
              <n-input
                v-model:value="form.storage_state_relpath"
                placeholder="留空走系统默认登录态 (.auth/user.json)"
                clearable
              />
            </n-form-item-gi>
          </n-grid>

          <n-space justify="end">
            <n-button @click="resetForm">重置</n-button>
            <n-button
              type="primary"
              :loading="submitting || streaming"
              :disabled="!canSubmit || streaming"
              @click="submit"
            >
              <template #icon>
                <n-icon><Icon icon="mdi:play-circle-outline" /></n-icon>
              </template>
              {{ streaming ? '分析进行中…' : '开始分析' }}
            </n-button>
          </n-space>
        </n-form>
      </n-card>

      <!-- ============ 进度条 ============ -->
      <n-card v-if="streaming || streamMessages.length" size="small" title="分析进度（SSE）">
        <template #header-extra>
          <n-space size="small">
            <n-tag v-if="streaming" type="info">运行中</n-tag>
            <n-tag v-else-if="streamFinal?.message_type === 'success'" type="success">已完成</n-tag>
            <n-tag v-else-if="streamFinal?.message_type === 'error'" type="error">失败</n-tag>
            <n-button v-if="!streaming" size="tiny" text @click="clearStream">清空</n-button>
          </n-space>
        </template>
        <n-scrollbar style="max-height: 260px" ref="streamScrollRef">
          <div v-for="(msg, idx) in streamMessages" :key="idx" class="stream-line">
            <n-tag :type="msgTypeMap[msg.message_type] || 'default'" size="tiny" round>
              {{ msg.region || msg.message_type }}
            </n-tag>
            <span class="stream-text">{{ msg.content }}</span>
          </div>
        </n-scrollbar>
      </n-card>

      <!-- ============ 历史列表 ============ -->
      <n-card title="历史分析记录" size="small">
        <template #header-extra>
          <n-space>
            <n-input
              v-model:value="listKeyword"
              placeholder="按页面类型/描述搜索"
              clearable
              style="width: 220px"
              @keyup.enter="loadAnalyses"
            >
              <template #prefix>
                <n-icon><Icon icon="mdi:magnify" /></n-icon>
              </template>
            </n-input>
            <n-button @click="loadAnalyses">刷新</n-button>
          </n-space>
        </template>
        <n-data-table
          remote
          :columns="columns"
          :data="analysisList"
          :pagination="pagination"
          :loading="loadingList"
          :row-key="(row) => row.analysis_id"
          @update:page="onPageChange"
        />
      </n-card>
    </n-space>

    <!-- ============ 详情抽屉 ============ -->
    <n-drawer v-model:show="detailVisible" :width="720" placement="right">
      <n-drawer-content :title="`分析详情：${detail?.analysis_id || ''}`" closable>
        <n-spin :show="detailLoading">
          <n-tabs v-if="detail" type="line" animated>
            <n-tab-pane name="summary" tab="摘要">
              <n-descriptions :column="1" bordered label-placement="left">
                <n-descriptions-item label="analysis_id">{{ detail.analysis_id }}</n-descriptions-item>
                <n-descriptions-item label="session_id">{{ detail.session_id || '-' }}</n-descriptions-item>
                <n-descriptions-item label="来源类型">{{ detail.source_type || '-' }}</n-descriptions-item>
                <n-descriptions-item label="页面类型">{{ detail.page_type || '-' }}</n-descriptions-item>
                <n-descriptions-item label="页面概述">{{ detail.page_summary || '-' }}</n-descriptions-item>
                <n-descriptions-item label="用户描述">{{ detail.user_description || '-' }}</n-descriptions-item>
                <n-descriptions-item label="是否兜底">
                  <n-tag :type="detail.from_fallback ? 'warning' : 'success'" size="small">
                    {{ detail.from_fallback ? '是（LLM 不可用走模板）' : '否' }}
                  </n-tag>
                </n-descriptions-item>
                <n-descriptions-item label="状态">{{ detail.status || '-' }}</n-descriptions-item>
              </n-descriptions>
            </n-tab-pane>

            <n-tab-pane name="elements" :tab="`元素清单（${(detail.elements_rows || detail.elements || []).length}）`">
              <n-data-table
                :columns="elementColumns"
                :data="detail.elements_rows || detail.elements || []"
                :pagination="{ pageSize: 8 }"
                size="small"
              />
            </n-tab-pane>

            <n-tab-pane name="steps" :tab="`交互步骤（${(detail.suggested_steps || []).length}）`">
              <n-list bordered>
                <n-list-item v-for="(s, idx) in detail.suggested_steps || []" :key="idx">
                  <n-thing>
                    <template #header>
                      Step {{ s.step }} · {{ s.action }}
                    </template>
                    <template #description>
                      <div>目标：{{ s.target_description || s.target_element_id || '-' }}</div>
                      <div v-if="s.value">参数：{{ s.value }}</div>
                      <div v-if="s.expected">期望：{{ s.expected }}</div>
                    </template>
                  </n-thing>
                </n-list-item>
              </n-list>
            </n-tab-pane>

            <n-tab-pane name="raw" tab="原始响应">
              <n-code :code="JSON.stringify(detail.raw_response || {}, null, 2)" language="json" />
            </n-tab-pane>
          </n-tabs>
        </n-spin>
        <template #footer>
          <n-space justify="end">
            <n-button :disabled="!detail" @click="goGenerateScript">
              <template #icon>
                <n-icon><Icon icon="mdi:script-text-play-outline" /></n-icon>
              </template>
              基于此分析生成脚本
            </n-button>
          </n-space>
        </template>
      </n-drawer-content>
    </n-drawer>

    <!-- ============ 图片库选择 modal ============ -->
    <n-modal
      v-model:show="libraryPickerVisible"
      title="从图片库选择"
      preset="card"
      style="width: 780px"
      :mask-closable="true"
    >
      <n-space vertical>
        <n-space>
          <n-input
            v-model:value="libraryFilter.keyword"
            placeholder="名称/描述"
            clearable
            style="width: 200px"
            @keyup.enter="loadLibrary"
          >
            <template #prefix>
              <n-icon><Icon icon="mdi:magnify" /></n-icon>
            </template>
          </n-input>
          <n-input
            v-model:value="libraryFilter.page_type"
            placeholder="页面类型"
            clearable
            style="width: 140px"
            @keyup.enter="loadLibrary"
          />
          <n-input
            v-model:value="libraryFilter.tag"
            placeholder="标签"
            clearable
            style="width: 140px"
            @keyup.enter="loadLibrary"
          />
          <n-button @click="loadLibrary">刷新</n-button>
        </n-space>
        <n-spin :show="libraryLoading">
          <n-empty
            v-if="!libraryLoading && libraryList.length === 0"
            description="图片库为空，先去「图片库」上传几张"
          />
          <div v-else class="lib-grid">
            <div
              v-for="item in libraryList"
              :key="item.image_id"
              class="lib-card"
              :class="{ active: pendingPick?.image_id === item.image_id }"
              @click="pendingPick = item"
            >
              <div class="lib-thumb">
                <img :src="libraryThumbUrl(item)" :alt="item.title || item.original_name" />
                <div v-if="item.reference_count > 0" class="lib-ref-badge">
                  ×{{ item.reference_count }}
                </div>
              </div>
              <div class="lib-meta">
                <div class="lib-title" :title="item.title || item.original_name">
                  {{ item.title || item.original_name || item.image_id }}
                </div>
                <div class="lib-sub">{{ item.width }}×{{ item.height }}</div>
              </div>
            </div>
          </div>
        </n-spin>
        <n-pagination
          v-if="libraryPagination.itemCount > libraryPagination.pageSize"
          v-model:page="libraryPagination.page"
          :item-count="libraryPagination.itemCount"
          :page-size="libraryPagination.pageSize"
          style="justify-content: flex-end"
          @update:page="onLibraryPageChange"
        />
      </n-space>
      <template #action>
        <n-space justify="end">
          <n-button @click="libraryPickerVisible = false">取消</n-button>
          <n-button type="primary" :disabled="!pendingPick" @click="confirmPickLibrary">
            选择此图片
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </AppPage>
</template>

<script setup>
import { computed, h, nextTick, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { NButton, NSpace, NTag } from 'naive-ui'
import api from '@/api'

const router = useRouter()

// ----------------------------------------------------------------------------
// 表单
// ----------------------------------------------------------------------------
const formRef = ref(null)
const uploadRef = ref(null)
const form = ref({
  analysis_type: 'hybrid',
  page_name: '',
  page_url: '',
  screenshot_path: '',
  image_id: '',
  text_description: '',
  live_url: '',
  storage_state_relpath: '',
})
const uploadedFile = ref(null)
const previewUrl = ref('')
const submitting = ref(false)
const screenshotSourceTab = ref('upload')

const needScreenshot = computed(() => ['image', 'hybrid'].includes(form.value.analysis_type))
const needText = computed(() => ['text', 'hybrid'].includes(form.value.analysis_type))
const needLiveUrl = computed(() => form.value.analysis_type === 'live_url')

const rules = {
  page_name: [{ required: true, message: '请填写页面名称', trigger: 'blur' }],
}

const canSubmit = computed(() => {
  if (!form.value.page_name?.trim()) return false
  if (needScreenshot.value && !form.value.screenshot_path && !form.value.image_id) return false
  if (needText.value && !form.value.text_description?.trim()) return false
  if (needLiveUrl.value && !form.value.live_url?.trim()) return false
  return true
})

function formatBytes(n) {
  if (!n) return '0B'
  if (n < 1024) return `${n}B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`
  return `${(n / 1024 / 1024).toFixed(2)}MB`
}

async function onUploadChange({ file }) {
  if (!file?.file) return
  const rawFile = file.file
  const fileName = rawFile.name || file.name || 'screenshot.png'
  const formData = new FormData()
  formData.append('file', rawFile, fileName)
  // 默认带个 page_type 便于回看;留空也行
  if (form.value.page_name) formData.append('title', form.value.page_name)
  try {
    // 走图片库通道:自动 SHA256 查重 + 拿到 image_id,后续可在图片库复用
    const res = await api.uiUploadLibraryImage(formData)
    const data = res?.data ?? res
    uploadedFile.value = {
      image_id: data.image_id,
      title: data.title,
      original_name: data.original_name,
      file_size: data.file_size,
    }
    form.value.image_id = data.image_id
    form.value.screenshot_path = '' // 后端 image_id 优先
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = URL.createObjectURL(file.file)
    if (data.is_duplicate) {
      window.$message?.info(`命中已有图片(image_id=${data.image_id}),已自动复用`)
    } else {
      window.$message?.success('截图上传成功，已入图片库')
    }
  } catch (e) {
    window.$message?.error('截图上传失败：' + (e?.message || e))
    uploadRef.value?.clear?.()
  }
}

function clearUpload() {
  uploadedFile.value = null
  form.value.screenshot_path = ''
  form.value.image_id = ''
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
  uploadRef.value?.clear?.()
}

function resetForm() {
  form.value = {
    analysis_type: 'hybrid',
    page_name: '',
    page_url: '',
    screenshot_path: '',
    image_id: '',
    text_description: '',
    live_url: '',
    storage_state_relpath: '',
  }
  screenshotSourceTab.value = 'upload'
  clearUpload()
}

// ----------------------------------------------------------------------------
// 图片库选择
// ----------------------------------------------------------------------------
const libraryPickerVisible = ref(false)
const libraryLoading = ref(false)
const libraryList = ref([])
const libraryFilter = ref({ keyword: '', page_type: '', tag: '' })
const libraryPagination = ref({ page: 1, pageSize: 12, itemCount: 0 })
const pendingPick = ref(null)

function libraryThumbUrl(item) {
  return `/static/ui-images/thumbnails/${item.image_id}.jpg`
}

async function loadLibrary() {
  libraryLoading.value = true
  try {
    const res = await api.uiListLibraryImages({
      page: libraryPagination.value.page,
      page_size: libraryPagination.value.pageSize,
      keyword: libraryFilter.value.keyword || undefined,
      page_type: libraryFilter.value.page_type || undefined,
      tag: libraryFilter.value.tag || undefined,
    })
    const data = res?.data ?? res
    libraryList.value = data.items || []
    libraryPagination.value.itemCount = data.total || 0
  } catch (e) {
    window.$message?.error('图片库加载失败：' + (e?.message || e))
  } finally {
    libraryLoading.value = false
  }
}

function onLibraryPageChange(page) {
  libraryPagination.value.page = page
  loadLibrary()
}

function openLibraryPicker() {
  pendingPick.value = null
  libraryPagination.value.page = 1
  libraryPickerVisible.value = true
  loadLibrary()
}

function confirmPickLibrary() {
  if (!pendingPick.value) return
  const item = pendingPick.value
  // 清掉上传链路的状态，只保留 image_id
  uploadRef.value?.clear?.()
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
  form.value.image_id = item.image_id
  form.value.screenshot_path = '' // 后端 image_id 优先,清空 path 避免混淆
  uploadedFile.value = {
    image_id: item.image_id,
    title: item.title,
    original_name: item.original_name,
    file_size: item.file_size,
  }
  previewUrl.value = libraryThumbUrl(item)
  libraryPickerVisible.value = false
  window.$message?.success(`已选择：${item.title || item.original_name || item.image_id}`)
}

// ----------------------------------------------------------------------------
// SSE
// ----------------------------------------------------------------------------
const streaming = ref(false)
const streamMessages = ref([])
const streamFinal = ref(null)
const streamScrollRef = ref(null)
let evtSource = null
const msgTypeMap = {
  info: 'info',
  success: 'success',
  warning: 'warning',
  error: 'error',
}

function clearStream() {
  streamMessages.value = []
  streamFinal.value = null
}

function closeStream() {
  if (evtSource) {
    evtSource.close()
    evtSource = null
  }
  streaming.value = false
}

async function startStream(sessionId) {
  closeStream()
  clearStream()
  streaming.value = true
  evtSource = new EventSource(api.uiAnalysisStreamUrl(sessionId))
  evtSource.onmessage = async (ev) => {
    try {
      const payload = JSON.parse(ev.data)
      streamMessages.value.push(payload)
      await nextTick()
      streamScrollRef.value?.scrollTo?.({ top: 99999 })
      if (payload.is_final) {
        streamFinal.value = payload
        closeStream()
        loadAnalyses()
      }
    } catch (e) {
      console.warn('SSE 解析失败', e)
    }
  }
  evtSource.onerror = () => {
    closeStream()
  }
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    const payload = {
      analysis_type: form.value.analysis_type,
      page_name: form.value.page_name,
      page_url: form.value.page_url || null,
      text_description: form.value.text_description || null,
    }
    // image_id 优先；老链路兼容保留 screenshot_path
    if (form.value.image_id) {
      payload.image_id = form.value.image_id
    } else if (form.value.screenshot_path) {
      payload.screenshot_path = form.value.screenshot_path
    }
    // Live URL 模式专用字段
    if (needLiveUrl.value) {
      payload.live_url = form.value.live_url
      if (form.value.storage_state_relpath?.trim()) {
        payload.storage_state_relpath = form.value.storage_state_relpath.trim()
      }
    }
    const res = await api.uiAnalyzePage(payload)
    const data = res?.data ?? res
    window.$message?.success('已投递分析任务')
    startStream(data.session_id)
  } catch (e) {
    window.$message?.error('提交失败：' + (e?.message || e))
  } finally {
    submitting.value = false
  }
}

// ----------------------------------------------------------------------------
// 历史列表
// ----------------------------------------------------------------------------
const analysisList = ref([])
const loadingList = ref(false)
const listKeyword = ref('')
const pagination = ref({
  page: 1,
  pageSize: 10,
  itemCount: 0,
  showSizePicker: false,
})

const columns = [
  { title: 'analysis_id', key: 'analysis_id', ellipsis: { tooltip: true } },
  { title: '页面类型', key: 'page_type', width: 120 },
  { title: '摘要', key: 'page_summary', ellipsis: { tooltip: true } },
  {
    title: '元素数',
    key: 'elements_count',
    width: 80,
    render: (row) => h(NTag, { size: 'small' }, () => row.elements_count ?? 0),
  },
  {
    title: '兜底',
    key: 'from_fallback',
    width: 80,
    render: (row) => h(
      NTag,
      { size: 'small', type: row.from_fallback ? 'warning' : 'success' },
      () => (row.from_fallback ? '是' : '否')
    ),
  },
  { title: '创建时间', key: 'created_at', width: 170 },
  {
    title: '操作',
    key: 'actions',
    width: 200,
    render: (row) => h(NSpace, { size: 'small' }, () => [
      h(NButton, {
        size: 'tiny',
        onClick: () => openDetail(row.analysis_id),
      }, () => '详情'),
      h(NButton, {
        size: 'tiny',
        type: 'primary',
        secondary: true,
        onClick: () => goGenerateScriptById(row.analysis_id),
      }, () => '生成脚本'),
      h(NButton, {
        size: 'tiny',
        type: 'error',
        secondary: true,
        onClick: () => confirmDelete(row.analysis_id),
      }, () => '删除'),
    ]),
  },
]

async function loadAnalyses() {
  loadingList.value = true
  try {
    const res = await api.uiListAnalyses({
      page: pagination.value.page,
      page_size: pagination.value.pageSize,
      keyword: listKeyword.value || undefined,
    })
    const data = res?.data ?? res
    analysisList.value = data.items || []
    pagination.value.itemCount = data.total || 0
  } catch (e) {
    window.$message?.error('加载失败：' + (e?.message || e))
  } finally {
    loadingList.value = false
  }
}

function onPageChange(page) {
  pagination.value.page = page
  loadAnalyses()
}

function confirmDelete(analysisId) {
  window.$dialog?.warning({
    title: '确认删除',
    content: `删除分析记录 ${analysisId} 及其元素行？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.uiDeleteAnalysis(analysisId)
        window.$message?.success('已删除')
        loadAnalyses()
      } catch (e) {
        window.$message?.error('删除失败：' + (e?.message || e))
      }
    },
  })
}

// ----------------------------------------------------------------------------
// 详情抽屉
// ----------------------------------------------------------------------------
const detailVisible = ref(false)
const detail = ref(null)
const detailLoading = ref(false)

const elementColumns = [
  { title: 'element_id', key: 'element_id', width: 130 },
  { title: '名称', key: 'name', width: 150 },
  { title: '分类', key: 'element_type', width: 100 },
  { title: '文本', key: 'text_content', ellipsis: { tooltip: true } },
  { title: 'selector', key: 'selector', ellipsis: { tooltip: true } },
  {
    title: '置信度',
    key: 'confidence',
    width: 90,
    render: (row) => row.confidence?.toFixed?.(2) ?? '-',
  },
]

async function openDetail(analysisId) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const res = await api.uiGetAnalysis(analysisId)
    detail.value = res?.data ?? res
  } catch (e) {
    window.$message?.error('加载详情失败：' + (e?.message || e))
  } finally {
    detailLoading.value = false
  }
}

function goGenerateScript() {
  if (!detail.value) return
  goGenerateScriptById(detail.value.analysis_id)
}

function goGenerateScriptById(analysisId) {
  router.push({
    path: '/ui-automation/script-management',
    query: { analysis_id: analysisId },
  })
}

// ----------------------------------------------------------------------------
loadAnalyses()
onBeforeUnmount(() => {
  closeStream()
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<style scoped>
.upload-tip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 18px 0;
  color: #888;
}
.upload-meta {
  color: #888;
  font-size: 12px;
}
.stream-line {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
  line-height: 1.5;
}
.stream-text {
  white-space: pre-wrap;
  word-break: break-all;
}
.lib-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
  max-height: 380px;
  overflow-y: auto;
  padding: 4px;
}
.lib-card {
  border: 2px solid transparent;
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  background: #fafafa;
  transition: border-color 0.15s, transform 0.15s;
}
.lib-card:hover {
  border-color: rgba(24, 160, 88, 0.4);
  transform: translateY(-1px);
}
.lib-card.active {
  border-color: #18a058;
  box-shadow: 0 0 0 2px rgba(24, 160, 88, 0.18);
}
.lib-thumb {
  position: relative;
  width: 100%;
  height: 96px;
  background: #f0f0f0;
}
.lib-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.lib-ref-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  background: rgba(24, 160, 88, 0.92);
  color: #fff;
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 10px;
}
.lib-meta {
  padding: 4px 6px;
}
.lib-title {
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.lib-sub {
  font-size: 10px;
  color: rgba(0, 0, 0, 0.45);
}
</style>

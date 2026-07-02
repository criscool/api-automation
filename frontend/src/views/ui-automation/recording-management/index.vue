<template>
  <AppPage>
    <n-space vertical size="large">
      <!-- ============ 顶部:新建录制按钮 + 状态过滤 ============ -->
      <n-card size="small">
        <n-space justify="space-between" align="center">
          <n-space>
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
          <n-space>
            <n-button type="primary" @click="openCreateModal">
              <template #icon><n-icon><Icon icon="mdi:record-rec" /></n-icon></template>
              开始录制
            </n-button>
          </n-space>
        </n-space>
      </n-card>

      <!-- ============ 录制会话列表 ============ -->
      <n-card title="录制会话" size="small">
        <n-data-table
          remote
          :columns="columns"
          :data="list"
          :pagination="pagination"
          :loading="loading"
          :row-key="(row) => row.session_id"
          @update:page="onPageChange"
        />
      </n-card>
    </n-space>

    <!-- ============ 新建录制弹窗 ============ -->
    <n-modal
      v-model:show="createVisible"
      title="新建录制会话"
      preset="card"
      style="width: 720px; max-width: 96vw"
      :mask-closable="false"
    >
      <n-form ref="createFormRef" :model="createForm" :rules="createRules" label-placement="top">
        <n-form-item label="录制名称" path="name">
          <n-input v-model:value="createForm.name"
                   placeholder="如:资产管理-添加资产" maxlength="80" />
        </n-form-item>
        <n-form-item label="目标 URL" path="target_url">
          <n-input v-model:value="createForm.target_url"
                   placeholder="如:http://localhost:8080/" />
        </n-form-item>
        <n-form-item label="登录态文件相对路径(可选)" path="storage_state_relpath">
          <n-input v-model:value="createForm.storage_state_relpath"
                   placeholder="留空默认走 .auth/user.json" />
        </n-form-item>
        <n-form-item label="超时秒数(可选)" path="timeout_seconds">
          <n-input-number v-model:value="createForm.timeout_seconds"
                          :min="60" :max="7200"
                          placeholder="默认 1800(30 分钟)"
                          style="width: 100%" />
        </n-form-item>
        <n-form-item label="脚本风格" path="script_style">
          <n-radio-group v-model:value="createForm.script_style">
            <n-radio value="playwright">纯 Playwright(保留 getByRole,推荐)</n-radio>
            <n-radio value="midscene">MidScene(AI 改写为 aiTap,极简页面备选)</n-radio>
          </n-radio-group>
        </n-form-item>
        <n-form-item label="预抓页面语义" path="prefetch_page_semantics">
          <n-space vertical size="small">
            <n-checkbox v-model:checked="createForm.prefetch_page_semantics">
              录制开始前用 crawl4ai 抓一次 target_url 的真实 DOM(辅助 LLM 改写更稳定 selector)
            </n-checkbox>
            <n-text depth="3" style="font-size: 12px">
              失败不阻塞录制,page_dict 会随会话落盘到 page_dicts/&lt;session&gt;.json,
              重新优化时可复用。crawl4ai 关闭/未安装时即使勾选也会被强制忽略。
            </n-text>
          </n-space>
        </n-form-item>
        <n-alert type="info" style="margin-top: 8px">
          点击"开始录制"后,浏览器会在后端机器上弹出。请完成操作后<b>关闭浏览器窗口</b>即可结束录制,
          系统会自动跑 AI 后处理。<br>
          <b>纯 Playwright</b>(默认):保留 getByRole 等原生 selector,稳定性最高,资产管理-添加资产-搜索-删除等实战脚本均能跑通;
          <b>MidScene</b>:把 click 改成 aiTap("按钮文案"),仅在原生 selector 完全失效时考虑——VLM 视觉识别会被高亮态/重叠元素干扰。
        </n-alert>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="createVisible = false">取消</n-button>
          <n-button type="primary" :loading="creating" @click="submitCreate">开始录制</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- ============ 实时进度抽屉 ============ -->
    <n-drawer v-model:show="liveVisible" :width="640" placement="right" :mask-closable="false">
      <n-drawer-content :title="`录制进度 - ${liveSession?.name || ''}`" closable>
        <n-space vertical>
          <n-descriptions :column="2" size="small" bordered>
            <n-descriptions-item label="状态">
              <n-tag :type="statusTagType(liveSession?.status)">{{ statusLabel(liveSession?.status) }}</n-tag>
            </n-descriptions-item>
            <n-descriptions-item label="耗时(ms)">{{ liveSession?.duration_ms || 0 }}</n-descriptions-item>
            <n-descriptions-item label="目标 URL" :span="2">
              <n-ellipsis>{{ liveSession?.target_url }}</n-ellipsis>
            </n-descriptions-item>
            <n-descriptions-item label="原始脚本路径" :span="2">
              <n-text code>{{ liveSession?.raw_script_path || '(尚未生成)' }}</n-text>
            </n-descriptions-item>
            <n-descriptions-item label="终态脚本 ID" :span="2">
              <n-text code>{{ liveSession?.final_script_id || '(尚未生成)' }}</n-text>
            </n-descriptions-item>
            <n-descriptions-item v-if="liveSession?.error_message" label="错误信息" :span="2">
              <n-text type="error">{{ liveSession.error_message }}</n-text>
            </n-descriptions-item>
          </n-descriptions>

          <n-card title="SSE 实时日志" size="small">
            <div ref="liveLogRef" class="live-log">
              <div v-for="(item, idx) in liveLogs" :key="idx" :class="`log-line log-${item.region || 'process'}`">
                <span class="log-ts">{{ formatTs(item.timestamp) }}</span>
                <span class="log-type">[{{ item.message_type || 'info' }}]</span>
                <span class="log-content">{{ item.content }}</span>
              </div>
              <div v-if="liveLogs.length === 0" class="empty">暂无日志</div>
            </div>
          </n-card>

          <n-space v-if="liveSession?.final_script_id">
            <n-button type="primary" @click="goToScript(liveSession.final_script_id)">
              <template #icon><n-icon><Icon icon="mdi:file-eye" /></n-icon></template>
              查看终态脚本
            </n-button>
          </n-space>
        </n-space>

        <template #footer>
          <n-space justify="end">
            <n-button v-if="liveActive" @click="onCancelLive">取消录制</n-button>
            <n-button @click="closeLive">关闭</n-button>
          </n-space>
        </template>
      </n-drawer-content>
    </n-drawer>

    <!-- ============ 详情/最终脚本预览抽屉 ============ -->
    <n-drawer v-model:show="detailVisible" :width="800" placement="right">
      <n-drawer-content :title="`录制详情 - ${detail?.name || ''}`" closable>
        <n-space vertical>
          <n-descriptions :column="2" size="small" bordered v-if="detail">
            <n-descriptions-item label="session_id" :span="2">
              <n-text code>{{ detail.session_id }}</n-text>
            </n-descriptions-item>
            <n-descriptions-item label="状态">
              <n-tag :type="statusTagType(detail.status)">{{ statusLabel(detail.status) }}</n-tag>
            </n-descriptions-item>
            <n-descriptions-item label="耗时(ms)">{{ detail.duration_ms }}</n-descriptions-item>
            <n-descriptions-item label="目标 URL" :span="2">{{ detail.target_url }}</n-descriptions-item>
            <n-descriptions-item label="登录态文件" :span="2">{{ detail.storage_state_path || '(未指定)' }}</n-descriptions-item>
            <n-descriptions-item label="原始脚本路径" :span="2">
              <n-text code>{{ detail.raw_script_path || '(无)' }}</n-text>
            </n-descriptions-item>
            <n-descriptions-item label="终态脚本" :span="2">
              <span v-if="detail.final_script">
                <n-button text type="primary" @click="goToScript(detail.final_script.script_id)">
                  {{ detail.final_script.name }} ({{ detail.final_script.file_path }})
                </n-button>
              </span>
              <span v-else>(无)</span>
            </n-descriptions-item>
            <n-descriptions-item v-if="detail.error_message" label="错误信息" :span="2">
              <n-text type="error">{{ detail.error_message }}</n-text>
            </n-descriptions-item>
            <n-descriptions-item label="脚本风格">
              <n-tag :type="detail.script_style === 'playwright' ? 'warning' : 'info'" size="small">
                {{ detail.script_style === 'playwright' ? '纯 Playwright' : 'MidScene' }}
              </n-tag>
            </n-descriptions-item>
            <n-descriptions-item label="创建人">{{ detail.created_by }}</n-descriptions-item>
            <n-descriptions-item label="创建时间">{{ detail.created_at }}</n-descriptions-item>
          </n-descriptions>

          <n-card v-if="detail" title="重新优化(可选切换风格)" size="small">
            <n-radio-group v-model:value="repolishStyle">
              <n-radio value="playwright">纯 Playwright</n-radio>
              <n-radio value="midscene">MidScene</n-radio>
            </n-radio-group>
          </n-card>

          <n-card v-if="detail?.final_script?.content" title="终态脚本预览" size="small">
            <n-input
              :value="detail.final_script.content"
              type="textarea"
              readonly
              :autosize="{ minRows: 12, maxRows: 28 }"
              class="code-area"
            />
          </n-card>
        </n-space>

        <template #footer>
          <n-space justify="end">
            <n-button v-if="detail?.raw_script_path && detail.status !== 'recording'"
                      type="warning"
                      :loading="repolishing"
                      @click="onRepolish(detail.session_id)">
              <template #icon><n-icon><Icon icon="mdi:auto-fix" /></n-icon></template>
              重新跑 AI 优化
            </n-button>
            <n-button v-if="detail && ['ready', 'failed', 'timeout', 'cancelled', 'interrupted'].includes(detail.status)"
                      type="primary"
                      :loading="reRecording"
                      @click="onReRecord(detail)">
              <template #icon><n-icon><Icon icon="mdi:record-rec" /></n-icon></template>
              重新录制
            </n-button>
            <n-button @click="detailVisible = false">关闭</n-button>
          </n-space>
        </template>
      </n-drawer-content>
    </n-drawer>
  </AppPage>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, h, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { NButton, NTag, NSpace, NRadio, NRadioGroup, useDialog } from 'naive-ui'
import AppPage from '@/components/page/AppPage.vue'
import api from '@/api'
import { useUserStore } from '@/store'

const userStore = useUserStore()

const router = useRouter()
const dialog = useDialog()

// ============ 列表 ============
const loading = ref(false)
const list = ref([])
const filter = reactive({ status: null })
const pagination = reactive({
  page: 1,
  pageSize: 20,
  itemCount: 0,
  showSizePicker: false,
})

const statusOptions = [
  { label: '空闲', value: 'idle' },
  { label: '启动中', value: 'launching' },
  { label: '录制中', value: 'recording' },
  { label: 'AI 优化中', value: 'postprocessing' },
  { label: '完成', value: 'ready' },
  { label: '失败', value: 'failed' },
  { label: '取消', value: 'cancelled' },
  { label: '超时', value: 'timeout' },
]

function statusTagType(status) {
  if (status === 'ready') return 'success'
  if (status === 'failed' || status === 'timeout') return 'error'
  if (status === 'cancelled') return 'warning'
  if (status === 'recording' || status === 'postprocessing' || status === 'launching') return 'info'
  return 'default'
}

function statusLabel(status) {
  const map = {
    ready: '成功',
    failed: '失败',
    timeout: '失败(超时)',
    cancelled: '已取消',
    recording: '进行中',
    launching: '进行中',
    postprocessing: '进行中',
    idle: '空闲',
    interrupted: '已中断',
  }
  return map[status] || status || '-'
}

const columns = [
  { title: '名称', key: 'name', minWidth: 180, ellipsis: { tooltip: true } },
  {
    title: '状态', key: 'status', width: 110,
    render: (row) => h(NTag, { type: statusTagType(row.status), size: 'small' }, { default: () => statusLabel(row.status) }),
  },
  {
    title: '风格', key: 'script_style', width: 110,
    render: (row) => h(
      NTag,
      { type: row.script_style === 'playwright' ? 'warning' : 'info', size: 'small' },
      { default: () => row.script_style === 'playwright' ? 'Playwright' : 'MidScene' },
    ),
  },
  { title: '目标 URL', key: 'target_url', minWidth: 220, ellipsis: { tooltip: true } },
  { title: '终态脚本 ID', key: 'final_script_id', width: 130,
    render: (row) => row.final_script_id ? row.final_script_id.slice(0, 8) : '-' },
  { title: '耗时(ms)', key: 'duration_ms', width: 100 },
  { title: '创建人', key: 'created_by', width: 110 },
  { title: '创建时间', key: 'created_at', width: 170, ellipsis: { tooltip: true } },
  {
    title: '操作', key: 'actions', width: 280, fixed: 'right',
    render: (row) => h(NSpace, { size: 'small' }, () => [
      h(NButton, { size: 'small', onClick: () => openDetail(row.session_id) }, () => '详情'),
      row.status === 'recording' || row.status === 'launching'
        ? h(NButton, { size: 'small', type: 'warning', onClick: () => onCancel(row.session_id) }, () => '取消')
        : null,
      row.status === 'ready' && row.final_script_id
        ? h(NButton, { size: 'small', type: 'primary', onClick: () => goToScript(row.final_script_id) }, () => '查看脚本')
        : null,
      row.status !== 'recording' && row.status !== 'launching' && row.status !== 'postprocessing'
        ? h(NButton, { size: 'small', type: 'error', onClick: () => onDelete(row) }, () => '删除')
        : null,
    ]),
  },
]

async function loadList() {
  loading.value = true
  try {
    const params = {
      page: pagination.page,
      page_size: pagination.pageSize,
    }
    if (filter.status) params.status = filter.status
    const res = await api.uiListRecordings(params)
    list.value = res.data?.items || []
    pagination.itemCount = res.data?.total || 0
  } catch (e) {
    window.$message?.error('加载录制列表失败:' + (e.message || e))
  } finally {
    loading.value = false
  }
}

function onPageChange(page) {
  pagination.page = page
  loadList()
}

// ============ 新建 ============
const createVisible = ref(false)
const createFormRef = ref(null)
const creating = ref(false)
const createForm = reactive({
  name: '',
  target_url: '',
  storage_state_relpath: '',
  timeout_seconds: 1800,
  script_style: 'playwright',
  prefetch_page_semantics: false,
})
const createRules = {
  name: { required: true, message: '请填写录制名称', trigger: 'blur' },
  target_url: { required: true, message: '请填写目标 URL', trigger: 'blur' },
}

function openCreateModal() {
  createForm.name = ''
  createForm.target_url = ''
  createForm.storage_state_relpath = ''
  createForm.timeout_seconds = 1800
  createForm.script_style = 'playwright'
  createForm.prefetch_page_semantics = false
  createVisible.value = true
}

async function submitCreate() {
  try {
    await createFormRef.value?.validate()
  } catch {
    return
  }
  creating.value = true
  try {
    const res = await api.uiCreateRecording({
      name: createForm.name,
      target_url: createForm.target_url,
      storage_state_relpath: createForm.storage_state_relpath || '',
      timeout_seconds: createForm.timeout_seconds || null,
      created_by: userStore.name || 'manual',
      script_style: createForm.script_style || 'playwright',
      prefetch_page_semantics: !!createForm.prefetch_page_semantics,
    })
    const sessionId = res.data?.session_id
    if (!sessionId) {
      throw new Error('后端未返回 session_id')
    }
    createVisible.value = false
    window.$message?.success('已创建录制会话,等待浏览器弹出...')
    await loadList()
    openLive({ session_id: sessionId, name: createForm.name, target_url: createForm.target_url, status: 'idle' })
  } catch (e) {
    window.$message?.error('创建录制失败:' + (e.message || e))
  } finally {
    creating.value = false
  }
}

// ============ 实时进度(SSE) ============
const liveVisible = ref(false)
const liveSession = ref(null)
const liveLogs = ref([])
const liveActive = ref(false)
const liveLogRef = ref(null)
let sse = null

function openLive(session) {
  liveSession.value = { ...session }
  liveLogs.value = []
  liveVisible.value = true
  startSse(session.session_id)
}

function startSse(sessionId) {
  closeSse()
  const url = api.uiRecordingStreamUrl(sessionId)
  try {
    sse = new EventSource(url)
    liveActive.value = true
    sse.addEventListener('ready', () => {
      liveLogs.value.push({
        content: 'SSE 已连接,等待录制进度...',
        region: 'system',
        message_type: 'info',
        timestamp: new Date().toISOString(),
      })
    })
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
        // 同步终态信息到 liveSession 卡片
        const result = payload.result || {}
        if (result.session_id) {
          liveSession.value = {
            ...liveSession.value,
            status: result.status || liveSession.value?.status,
            raw_script_path: result.raw_script_path || liveSession.value?.raw_script_path,
            final_script_id: result.final_script_id || liveSession.value?.final_script_id,
            duration_ms: result.duration_ms || liveSession.value?.duration_ms,
            error_message: result.error_message || liveSession.value?.error_message,
          }
        }
        if (payload.is_final) {
          liveActive.value = false
          closeSse()
          loadList()
        }
      } catch (parseErr) {
        console.warn('SSE 解析失败', parseErr)
      }
    })
    sse.onerror = () => {
      liveActive.value = false
    }
  } catch (e) {
    window.$message?.error('SSE 订阅失败:' + e.message)
  }
}

function closeSse() {
  if (sse) {
    try { sse.close() } catch { /* ignore */ }
    sse = null
  }
}

function closeLive() {
  closeSse()
  liveVisible.value = false
}

async function onCancelLive() {
  if (!liveSession.value?.session_id) return
  dialog.warning({
    title: '确认取消',
    content: '取消后,浏览器窗口会被强制关闭,已捕获的步骤仍会落库。继续吗?',
    positiveText: '确认取消',
    negativeText: '继续录制',
    onPositiveClick: async () => {
      await onCancel(liveSession.value.session_id, true)
    },
  })
}

async function onCancel(sessionId, fromLive = false) {
  try {
    const res = await api.uiCancelRecording(sessionId)
    // 用后端返回的精确消息（"已取消（子进程已终止 + DB 状态已更新）"等）
    const msg = res?.msg || '已发送取消信号'
    window.$message?.success(msg)

    // 无论从哪里发起，都刷新列表让状态实时反映
    await loadList()

    // 如果是从实时进度抽屉发起的取消：
    // 1) 同步刷新抽屉里的 liveSession 状态（避免显示"启动中"僵尸）
    // 2) 状态确认为终态后自动关闭抽屉
    if (fromLive && liveSession.value?.session_id === sessionId) {
      try {
        const detailRes = await api.uiGetRecording(sessionId)
        const latest = detailRes?.data ?? detailRes
        if (latest) {
          liveSession.value = { ...liveSession.value, ...latest }
        }
        // 已进入终态 → 自动关抽屉
        const terminal = ['cancelled', 'failed', 'timeout', 'ready', 'interrupted']
        if (latest && terminal.includes(latest.status)) {
          setTimeout(() => { liveVisible.value = false }, 800)  // 让用户看清最终状态一秒钟
        }
      } catch {
        // 刷新失败不影响主流程
      }
    }
  } catch (e) {
    window.$message?.error('取消失败:' + (e?.response?.data?.detail || e.message || e))
  }
}

function onDelete(row) {
  dialog.warning({
    title: '确认删除录制会话',
    content: `将删除会话「${row.name || row.session_id}」及其原始录制脚本文件(如存在)。终态脚本(如已生成)不会被删除,仍保留在脚本管理中。确定继续?`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.uiDeleteRecording(row.session_id, true)
        window.$message?.success('已删除')
        loadList()
      } catch (e) {
        window.$message?.error('删除失败:' + (e.message || e))
      }
    },
  })
}

// ============ 详情 ============
const detailVisible = ref(false)
const detail = ref(null)
const repolishing = ref(false)
const repolishStyle = ref('playwright')
const reRecording = ref(false)

async function openDetail(sessionId) {
  try {
    const res = await api.uiGetRecording(sessionId)
    detail.value = res.data
    repolishStyle.value = res.data?.script_style || 'playwright'
    detailVisible.value = true
  } catch (e) {
    window.$message?.error('加载详情失败:' + (e.message || e))
  }
}

async function onRepolish(sessionId) {
  repolishing.value = true
  try {
    await api.uiRepolishRecording(sessionId, { script_style: repolishStyle.value })
    window.$message?.success('已触发重新优化,请在抽屉中查看进度')
    detailVisible.value = false
    openLive({ session_id: sessionId, name: detail.value?.name, target_url: detail.value?.target_url, status: 'postprocessing' })
  } catch (e) {
    window.$message?.error('重新优化失败:' + (e.message || e))
  } finally {
    repolishing.value = false
  }
}

async function onReRecord(oldDetail) {
  if (!oldDetail?.session_id) return
  const sessionId = oldDetail.session_id
  reRecording.value = true
  try {
    // 后端会复用 session_id 重置状态为 idle，保留 final_script_id 让脚本走 UPDATE
    const res = await api.uiReRecord(sessionId)
    const data = res?.data ?? res
    window.$message?.success('已触发重新录制，本地录制助手将启动浏览器')

    // 关掉详情抽屉，打开实时进度抽屉
    detailVisible.value = false
    openLive({
      session_id: sessionId,
      name: data?.name || oldDetail.name,
      target_url: data?.target_url || oldDetail.target_url,
      status: 'launching',
    })
  } catch (e) {
    const detail = e?.response?.data?.detail || e?.message || e
    window.$message?.error('重新录制失败：' + detail)
  } finally {
    reRecording.value = false
  }
}

function goToScript(scriptId) {
  router.push({ path: '/ui-automation/script-management', query: { script_id: scriptId } })
}

function formatTs(ts) {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleTimeString()
  } catch {
    return ts
  }
}

onMounted(loadList)
onBeforeUnmount(closeSse)
</script>

<style scoped>
.live-log {
  max-height: 400px;
  overflow-y: auto;
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 8px 12px;
  border-radius: 4px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  line-height: 1.6;
}
.log-line {
  white-space: pre-wrap;
  word-break: break-word;
}
.log-ts {
  color: #888;
  margin-right: 6px;
}
.log-type {
  color: #9cdcfe;
  margin-right: 6px;
}
.log-error .log-content {
  color: #f48771;
}
.log-warning .log-content {
  color: #dcdcaa;
}
.log-success .log-content {
  color: #b5cea8;
}
.empty {
  color: #888;
  text-align: center;
  padding: 16px;
}
.code-area :deep(.n-input__textarea-el) {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
}
</style>

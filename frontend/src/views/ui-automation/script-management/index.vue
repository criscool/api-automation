<template>
  <AppPage>
    <n-space vertical size="large">
      <!-- ============ 顶部：筛选 + 新建 ============ -->
      <n-card size="small">
        <n-space justify="space-between" align="center">
          <n-space>
            <n-input
              v-model:value="filter.keyword"
              placeholder="按名称/描述搜索"
              clearable
              style="width: 220px"
              @keyup.enter="loadList"
            >
              <template #prefix>
                <n-icon><Icon icon="mdi:magnify" /></n-icon>
              </template>
            </n-input>
            <n-select
              v-model:value="filter.script_type"
              placeholder="脚本类型"
              clearable
              :options="scriptTypeOptions"
              style="width: 200px"
              @update:value="loadList"
            />
            <n-select
              v-model:value="filter.source_type"
              placeholder="来源"
              clearable
              :options="sourceOptions"
              style="width: 140px"
              @update:value="loadList"
            />
            <n-button @click="loadList">刷新</n-button>
          </n-space>
          <n-space>
            <n-button type="warning" :disabled="checkedScriptIds.length === 0" @click="runBatch">
              <template #icon><n-icon><Icon icon="mdi:playlist-play" /></n-icon></template>
              批量运行 ({{ checkedScriptIds.length }})
            </n-button>
            <n-button type="primary" secondary @click="openGenerateModal">
              <template #icon><n-icon><Icon icon="mdi:auto-fix" /></n-icon></template>
              基于分析生成
            </n-button>
            <n-button type="primary" @click="openManualModal">
              <template #icon><n-icon><Icon icon="mdi:plus" /></n-icon></template>
              新建脚本
            </n-button>
          </n-space>
        </n-space>
      </n-card>

      <!-- ============ 列表 ============ -->
      <n-card title="脚本列表" size="small">
        <n-data-table
          remote
          v-model:checked-row-keys="checkedScriptIds"
          :columns="columns"
          :data="list"
          :pagination="pagination"
          :loading="loading"
          :row-key="(row) => row.script_id"
          @update:page="onPageChange"
        />
      </n-card>
    </n-space>

    <!-- ============ 新建（手动）弹窗 ============ -->
    <n-modal
      v-model:show="manualVisible"
      :title="manualForm.script_id ? '编辑脚本' : '新建脚本（手动）'"
      preset="card"
      style="width: 880px; max-width: 96vw"
      :mask-closable="false"
    >
      <n-form ref="manualFormRef" :model="manualForm" :rules="manualRules" label-placement="top">
        <n-grid :cols="2" :x-gap="16">
          <n-form-item-gi label="脚本名称" path="name">
            <n-input v-model:value="manualForm.name" placeholder="登录页测试" maxlength="80" />
          </n-form-item-gi>
          <n-form-item-gi label="脚本类型" path="script_type">
            <n-select
              v-model:value="manualForm.script_type"
              :options="scriptTypeOptions"
              :disabled="!!manualForm.script_id"
            />
          </n-form-item-gi>
          <n-form-item-gi label="描述">
            <n-input v-model:value="manualForm.description" placeholder="可选" maxlength="200" />
          </n-form-item-gi>
          <n-form-item-gi label="base_url">
            <n-input v-model:value="manualForm.base_url" placeholder="可选，覆盖默认 UI_BASE_URL" />
          </n-form-item-gi>
          <n-form-item-gi :span="2" label="脚本内容" path="content">
            <n-input
              v-model:value="manualForm.content"
              type="textarea"
              placeholder="粘贴脚本内容（.spec.ts / .yaml）"
              :autosize="{ minRows: 12, maxRows: 24 }"
              class="code-area"
            />
          </n-form-item-gi>
          <n-form-item-gi
            v-if="manualForm.script_type === 'playwright_midscene' && !manualForm.script_id"
            :span="2"
            label="附属文件 fixture.ts（可选，不填将自动使用官方模板）"
          >
            <n-input
              v-model:value="manualForm.fixture_ts"
              type="textarea"
              placeholder="留空使用平台官方 fixture.ts"
              :autosize="{ minRows: 4, maxRows: 8 }"
              class="code-area"
            />
          </n-form-item-gi>
        </n-grid>
      </n-form>
      <template #action>
        <n-space justify="end">
          <n-button @click="manualVisible = false">取消</n-button>
          <n-button type="primary" :loading="manualSubmitting" @click="submitManual">
            保存
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- ============ AI 生成弹窗 ============ -->
    <n-modal
      v-model:show="generateVisible"
      title="基于分析结果生成脚本"
      preset="card"
      style="width: 600px"
      :mask-closable="false"
    >
      <n-form ref="genFormRef" :model="genForm" :rules="genRules" label-placement="top">
        <n-alert type="info" :show-icon="false" style="margin-bottom: 12px">
          脚本默认从 <code>baseURL</code>(首页)开始,且已处于"已登录态"——
          登录由 <code>auth.setup.ts</code> 自动完成,业务用例无需写 URL/登录步骤,
          通过菜单导航进入即可。<code>baseURL</code> 由后端 <code>UI_BASE_URL</code> 注入。
        </n-alert>
        <n-form-item label="关联分析 ID" path="page_analysis_id">
          <n-input v-model:value="genForm.page_analysis_id" placeholder="ui_analysis_xxx" />
        </n-form-item>
        <n-form-item label="脚本名称" path="script_name">
          <n-input v-model:value="genForm.script_name" placeholder="如:登录页_ai生成" />
        </n-form-item>
        <n-form-item label="脚本类型" path="script_type">
          <n-select v-model:value="genForm.script_type" :options="scriptTypeOptions" />
        </n-form-item>
        <n-form-item label="补充测试意图">
          <n-input
            v-model:value="genForm.user_intent"
            type="textarea"
            placeholder="可选,补充未在分析中体现的测试侧重点"
            :autosize="{ minRows: 3, maxRows: 6 }"
            maxlength="500"
            show-count
          />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space justify="end">
          <n-button @click="generateVisible = false">取消</n-button>
          <n-button type="primary" :loading="generating" @click="submitGenerate">
            投递生成任务
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- ============ 详情抽屉 ============ -->
    <n-drawer v-model:show="detailVisible" :width="880" placement="right">
      <n-drawer-content :title="editName || detail?.name || '脚本详情'" closable>
        <n-spin :show="detailLoading">
          <n-space v-if="detail" vertical size="large">
            <!-- 用例名称编辑（脚本管理列表里展示的名字，同步写 DB.name） -->
            <n-card embedded title="用例名称" size="small">
              <n-input
                v-model:value="editName"
                placeholder="给这个脚本起个易记的名字（列表展示用）"
                :maxlength="200"
                show-count
                clearable
              />
            </n-card>

            <n-descriptions :column="2" bordered label-placement="left" size="small">
              <n-descriptions-item label="script_id">{{ detail.script_id }}</n-descriptions-item>
              <n-descriptions-item label="类型">
                <n-tag size="small">{{ detail.script_type }}</n-tag>
              </n-descriptions-item>
              <n-descriptions-item label="来源">
                <n-tag size="small" :type="detail.source_type === 'AI' || detail.source_type === 'ai' ? 'info' : 'default'">
                  {{ detail.source_type }}
                </n-tag>
              </n-descriptions-item>
              <n-descriptions-item label="状态">{{ detail.status }}</n-descriptions-item>
              <n-descriptions-item label="文件路径">{{ detail.file_path || '-' }}</n-descriptions-item>
              <n-descriptions-item label="base_url">{{ detail.base_url || '-' }}</n-descriptions-item>
              <n-descriptions-item label="分析关联">{{ detail.analysis_id || '-' }}</n-descriptions-item>
              <n-descriptions-item label="更新时间">{{ detail.updated_at || '-' }}</n-descriptions-item>
            </n-descriptions>
            <n-card embedded title="脚本内容" size="small">
              <template #header-extra>
                <n-button size="tiny" @click="copyContent">
                  <template #icon><n-icon><Icon icon="mdi:content-copy" /></n-icon></template>
                  复制
                </n-button>
              </template>
              <n-input
                v-model:value="editContent"
                type="textarea"
                class="code-area"
                :autosize="{ minRows: 18, maxRows: 30 }"
              />
            </n-card>
            <n-space justify="end">
              <n-button @click="detailVisible = false">关闭</n-button>
              <n-button type="primary" :loading="savingContent" @click="saveContent">
                保存修改
              </n-button>
            </n-space>
          </n-space>
        </n-spin>
      </n-drawer-content>
    </n-drawer>
  </AppPage>
</template>

<script setup>
import { h, onActivated, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { NButton, NSpace, NTag } from 'naive-ui'
import api from '@/api'

const route = useRoute()
const router = useRouter()

// ----------------------------------------------------------------------------
// 常量
// ----------------------------------------------------------------------------
const scriptTypeOptions = [
  { label: 'Playwright + MidScene（推荐）', value: 'playwright_midscene' },
  { label: 'Playwright Classic（纯 Playwright）', value: 'playwright_classic' },
  { label: 'MidScene YAML', value: 'yaml_midscene' },
]
const sourceOptions = [
  { label: 'AI 生成', value: 'ai' },
  { label: '手动新建', value: 'manual' },
]

// ----------------------------------------------------------------------------
// 列表
// ----------------------------------------------------------------------------
const list = ref([])
const checkedScriptIds = ref([])
const loading = ref(false)
const filter = ref({ keyword: '', script_type: null, source_type: null })
const pagination = ref({
  page: 1,
  pageSize: 10,
  itemCount: 0,
  showSizePicker: false,
})

const columns = [
  { type: 'selection', width: 40 },
  { title: '名称', key: 'name', ellipsis: { tooltip: true } },
  {
    title: '类型',
    key: 'script_type',
    width: 200,
    render: (row) => h(NTag, { size: 'small' }, () => row.script_type),
  },
  {
    title: '来源',
    key: 'source_type',
    width: 100,
    render: (row) => h(
      NTag,
      {
        size: 'small',
        type: (row.source_type || '').toLowerCase() === 'ai' ? 'info' : 'default',
      },
      () => row.source_type,
    ),
  },
  { title: '描述', key: 'description', ellipsis: { tooltip: true } },
  { title: '更新时间', key: 'updated_at', width: 170 },
  {
    title: '操作',
    key: 'actions',
    width: 240,
    render: (row) => h(NSpace, { size: 'small' }, () => [
      h(NButton, {
        size: 'tiny',
        type: 'primary',
        onClick: () => runScript(row),
      }, () => '运行'),
      h(NButton, {
        size: 'tiny',
        onClick: () => openDetail(row.script_id),
      }, () => '详情'),
      h(NButton, {
        size: 'tiny',
        type: 'error',
        secondary: true,
        onClick: () => confirmDelete(row.script_id),
      }, () => '删除'),
    ]),
  },
]

async function loadList() {
  loading.value = true
  try {
    const res = await api.uiListScripts({
      page: pagination.value.page,
      page_size: pagination.value.pageSize,
      keyword: filter.value.keyword || undefined,
      script_type: filter.value.script_type || undefined,
      source_type: filter.value.source_type || undefined,
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

function confirmDelete(scriptId) {
  window.$dialog?.warning({
    title: '确认删除',
    content: `删除脚本 ${scriptId}？工作目录中的文件会一并清理。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.uiDeleteScript(scriptId)
        window.$message?.success('已删除')
        loadList()
      } catch (e) {
        window.$message?.error('删除失败：' + (e?.message || e))
      }
    },
  })
}

async function runScript(row) {
  try {
    const res = await api.uiTriggerExecution({
      script_id: row.script_id,
      triggered_by: 'frontend',
    })
    const data = res?.data ?? res
    window.$message?.success(`已触发执行 ${data?.execution_id?.slice(0, 8) || ''}`)
    // 跳到执行报告详情页,带 query 自动订阅 SSE
    router.push({
      path: '/ui-automation/execution-reports',
      query: { execution_id: data.execution_id, session_id: data.session_id },
    })
  } catch (e) {
    window.$message?.error('运行失败：' + (e?.message || e))
  }
}

async function runBatch() {
  if (checkedScriptIds.value.length === 0) return
  try {
    const res = await api.uiTriggerBatchExecution({
      script_ids: [...checkedScriptIds.value],
      name: `批量执行 ${new Date().toLocaleString()}`,
      triggered_by: 'frontend',
    })
    const data = res?.data ?? res
    if (data.invalid_script_ids?.length) {
      window.$message?.warning(`跳过了 ${data.invalid_script_ids.length} 个无效脚本`)
    }
    window.$message?.success(`已触发批量执行 ${data?.batch_id?.slice(0, 8)}`)
    checkedScriptIds.value = []
    router.push({
      path: '/ui-automation/execution-reports',
      query: { batch_id: data.batch_id },
    })
  } catch (e) {
    window.$message?.error('批量执行失败：' + (e?.message || e))
  }
}

// ----------------------------------------------------------------------------
// 手动新建 / 编辑
// ----------------------------------------------------------------------------
const manualVisible = ref(false)
const manualFormRef = ref(null)
const manualSubmitting = ref(false)
const manualForm = ref({
  script_id: null,
  name: '',
  script_type: 'playwright_midscene',
  description: '',
  base_url: '',
  content: '',
  fixture_ts: '',
})
const manualRules = {
  name: [{ required: true, message: '请填写脚本名称', trigger: 'blur' }],
  script_type: [{ required: true, message: '请选择脚本类型', trigger: 'change' }],
  content: [{ required: true, message: '脚本内容不能为空', trigger: 'blur' }],
}

function openManualModal() {
  manualForm.value = {
    script_id: null,
    name: '',
    script_type: 'playwright_midscene',
    description: '',
    base_url: '',
    content: '',
    fixture_ts: '',
  }
  manualVisible.value = true
}

async function submitManual() {
  try {
    await manualFormRef.value?.validate()
  } catch {
    return
  }
  manualSubmitting.value = true
  try {
    const auxiliaryFiles = {}
    if (manualForm.value.script_type === 'playwright_midscene' && manualForm.value.fixture_ts?.trim()) {
      auxiliaryFiles['fixture.ts'] = manualForm.value.fixture_ts
    }
    await api.uiCreateManualScript({
      name: manualForm.value.name,
      script_type: manualForm.value.script_type,
      content: manualForm.value.content,
      auxiliary_files: auxiliaryFiles,
      description: manualForm.value.description || '',
      base_url: manualForm.value.base_url || '',
    })
    window.$message?.success('创建成功')
    manualVisible.value = false
    loadList()
  } catch (e) {
    window.$message?.error('保存失败：' + (e?.message || e))
  } finally {
    manualSubmitting.value = false
  }
}

// ----------------------------------------------------------------------------
// AI 生成
// ----------------------------------------------------------------------------
const generateVisible = ref(false)
const genFormRef = ref(null)
const generating = ref(false)
const genForm = ref({
  page_analysis_id: '',
  script_name: '',
  script_type: 'playwright_midscene',
  user_intent: '',
})
const genRules = {
  page_analysis_id: [{ required: true, message: '请填写关联的分析 ID', trigger: 'blur' }],
  script_name: [{ required: true, message: '请填写脚本名称', trigger: 'blur' }],
  script_type: [{ required: true, message: '请选择脚本类型', trigger: 'change' }],
}

function openGenerateModal(prefillAnalysisId) {
  genForm.value = {
    page_analysis_id: typeof prefillAnalysisId === 'string' ? prefillAnalysisId : '',
    script_name: '',
    script_type: 'playwright_midscene',
    user_intent: '',
  }
  generateVisible.value = true
}

async function submitGenerate() {
  try {
    await genFormRef.value?.validate()
  } catch {
    return
  }
  generating.value = true

  // 提交前记录现有 script_id 集合,用于轮询时判断"新增脚本是否出现"
  const beforeIds = new Set(list.value.map((s) => s.script_id))

  try {
    await api.uiGenerateScript({
      page_analysis_id: genForm.value.page_analysis_id,
      script_name: genForm.value.script_name,
      script_type: genForm.value.script_type,
      user_intent: genForm.value.user_intent || '',
    })

    // 1) 关弹窗
    generateVisible.value = false

    // 2) 用 history.replaceState 擦掉 URL 上的 ?analysis_id=xxx
    //    不能用 router.replace —— 那会触发组件重挂载,且 tags-view 里的 tag 还会留旧 fullPath
    //    history.replaceState 直接改地址栏,不经过 Vue Router,不触发任何重渲染
    if (window.history?.replaceState) {
      window.history.replaceState({}, '', route.path)
    }

    // 3) 持久 loading toast（用 loadingMessage 持续显示,直到检测到新脚本或超时）
    const loadingMsg = window.$message?.loading('AI 脚本生成中,通常需要 10–30 秒,完成后列表会自动刷新...', {
      duration: 0,  // 不自动消失
    })

    // 4) 轮询列表,最长 60 秒
    let elapsed = 0
    const interval = 3000
    const maxWait = 60000
    const timer = setInterval(async () => {
      elapsed += interval
      await loadList()
      const found = list.value.some((s) => !beforeIds.has(s.script_id))
      if (found) {
        clearInterval(timer)
        loadingMsg?.destroy?.()
        window.$message?.success('脚本生成完成,已刷新列表')
      } else if (elapsed >= maxWait) {
        clearInterval(timer)
        loadingMsg?.destroy?.()
        window.$message?.warning('生成耗时较长,请稍后手动点"刷新"查看结果')
      }
    }, interval)
  } catch (e) {
    window.$message?.error('投递失败:' + (e?.message || e))
  } finally {
    generating.value = false
  }
}

// ----------------------------------------------------------------------------
// 详情 / 编辑
// ----------------------------------------------------------------------------
const detailVisible = ref(false)
const detail = ref(null)
const detailLoading = ref(false)
const editContent = ref('')
const editName = ref('')
const savingContent = ref(false)

async function openDetail(scriptId) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  editContent.value = ''
  editName.value = ''
  try {
    const res = await api.uiGetScript(scriptId)
    detail.value = res?.data ?? res
    editContent.value = detail.value?.content || ''
    editName.value = detail.value?.name || ''
  } catch (e) {
    window.$message?.error('加载失败：' + (e?.message || e))
  } finally {
    detailLoading.value = false
  }
}

function copyContent() {
  if (!editContent.value) return
  navigator.clipboard?.writeText(editContent.value).then(
    () => window.$message?.success('已复制'),
    () => window.$message?.warning('复制失败，请手动选择文本'),
  )
}

async function saveContent() {
  if (!detail.value) return
  const trimmedName = (editName.value || '').trim()
  if (!trimmedName) {
    window.$message?.warning('用例名称不能为空')
    return
  }
  if (!editContent.value || !editContent.value.trim()) {
    window.$message?.warning('脚本内容不能为空')
    return
  }
  savingContent.value = true
  try {
    // 后端 PUT /scripts/{id} 同时支持 name + content 更新（会同步写磁盘）
    await api.uiUpdateScript(detail.value.script_id, {
      name: trimmedName,
      content: editContent.value,
    })
    // 本地也刷新一下，避免用户看不到更新
    if (detail.value) {
      detail.value.name = trimmedName
      detail.value.content = editContent.value
    }
    window.$message?.success('已保存（DB + 磁盘已同步）')
    loadList()
  } catch (e) {
    window.$message?.error('保存失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    savingContent.value = false
  }
}

// ----------------------------------------------------------------------------
// ----------------------------------------------------------------------------
// 从 query 触发"基于分析生成"弹窗:
// 1) 用 watch 监听 route.query.analysis_id 而不是只在 onMounted 里读一次,
//    因为 tags-view 已缓存本页时 onMounted 不会再触发,需要响应式监听。
// 2) immediate: true 保证首次进入有 query 时也能触发。
// 3) onActivated 兜底 keep-alive 场景。
// 4) 不能在打开弹窗后立刻 router.replace 清 query —— AppMain 用 route.fullPath
//    当 :key,URL 一变就会强制重挂载,弹窗会瞬间消失。让 query 留在地址栏即可。
// 5) sidebar 同路径点击会触发 appStore.reloadPage() 强制重挂载,
//    而 history.replaceState 不改 Vue Router 的 currentRoute → reload 后 query 还在 → 又弹窗。
//    所以用 sessionStorage 持久化"已消费的 analysis_id",跨重挂载也能记住。
const CONSUMED_KEY = 'ui_auto_consumed_analysis_ids'

function isAnalysisConsumed(id) {
  try {
    const arr = JSON.parse(sessionStorage.getItem(CONSUMED_KEY) || '[]')
    return Array.isArray(arr) && arr.includes(id)
  } catch {
    return false
  }
}

function markAnalysisConsumed(id) {
  try {
    const arr = JSON.parse(sessionStorage.getItem(CONSUMED_KEY) || '[]')
    const set = new Set(Array.isArray(arr) ? arr : [])
    set.add(id)
    // 最多保留最近 20 个,避免无限增长
    const list = Array.from(set).slice(-20)
    sessionStorage.setItem(CONSUMED_KEY, JSON.stringify(list))
  } catch {
    /* ignore */
  }
}

function removeAnalysisConsumed(id) {
  try {
    const arr = JSON.parse(sessionStorage.getItem(CONSUMED_KEY) || '[]')
    if (!Array.isArray(arr)) return
    const list = arr.filter((x) => x !== id)
    sessionStorage.setItem(CONSUMED_KEY, JSON.stringify(list))
  } catch {
    /* ignore */
  }
}

async function triggerFromQuery() {
  const analysisId = route.query.analysis_id
  if (!analysisId) return
  const id = String(analysisId)
  // 已消费过的 id 不能直接 return —— 用户可能先生成、后删除脚本再来重生成,
  // sessionStorage 是脏状态。先问后端实际情况,只有真的还有脚本或正在生成才尊重。
  if (isAnalysisConsumed(id)) {
    try {
      const res = await api.uiCheckScriptStatus(id)
      const status = res?.data?.status
      if (status === 'completed' || status === 'processing') {
        // 后端确实有活跃脚本或正在生成 —— 不重复弹窗
        return
      }
      // 后端说没脚本也不在生成中 → CONSUMED 状态过期,清掉重弹
      removeAnalysisConsumed(id)
    } catch {
      // 查询失败保守清一次让用户能继续操作,后端真有脚本时 generate 接口会再去重
      removeAnalysisConsumed(id)
    }
  }
  markAnalysisConsumed(id)
  openGenerateModal(id)
}

watch(() => route.query.analysis_id, (val) => {
  if (val) triggerFromQuery()
})

onActivated(() => {
  triggerFromQuery()
})

onMounted(() => {
  triggerFromQuery()
  loadList()
})
</script>

<style scoped>
.code-area :deep(textarea) {
  font-family: 'Fira Code', 'Cascadia Code', Consolas, monospace;
  font-size: 13px;
}
</style>

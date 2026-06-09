<template>
  <n-drawer v-model:show="visible" :width="720" placement="right" :on-after-leave="reset">
    <n-drawer-content closable>
      <template #header>
        <div class="flex items-center gap-2">
          <n-icon size="18" color="#2080f0"><Icon icon="mdi:robot-outline" /></n-icon>
          <span>AI 诊断</span>
          <n-tag v-if="scriptName" size="small" :bordered="false">{{ scriptName }}</n-tag>
        </div>
      </template>

      <!-- 状态条 -->
      <div class="status-bar">
        <n-tag :type="statusTagType" :bordered="false" round>
          <template #icon>
            <n-icon><Icon :icon="statusIcon" /></n-icon>
          </template>
          {{ statusLabel }}
        </n-tag>
        <span v-if="sessionId" class="session-id">session: {{ sessionId.slice(0, 8) }}</span>
        <span class="grow" />
        <n-button
          v-if="canRestart"
          size="small"
          tertiary
          @click="startDiagnose"
        >
          <template #icon>
            <n-icon><Icon icon="mdi:refresh" /></n-icon>
          </template>
          重新诊断
        </n-button>
      </div>

      <!-- 进度时间线 -->
      <n-card title="诊断流程" size="small" class="mt-4">
        <n-timeline>
          <n-timeline-item
            v-for="(evt, idx) in events"
            :key="idx"
            :type="timelineType(evt)"
            :title="timelineTitle(evt)"
            :content="timelineContent(evt)"
            :time="formatLocalTime(evt._receivedAt)"
          />
          <n-timeline-item
            v-if="events.length === 0"
            type="info"
            title="等待诊断启动..."
            content="点击右上角『重新诊断』可以重新触发，否则将自动进行。"
          />
        </n-timeline>
      </n-card>

      <!-- 结论 -->
      <n-card v-if="result" title="结论" size="small" class="mt-4">
        <div class="flex items-center gap-3 mb-3">
          <n-tag :type="verdictTagType" size="large" :bordered="false">
            {{ verdictLabel }}
          </n-tag>
          <span class="text-gray-500 text-sm">
            置信度：{{ formatConfidence(result.analysis?.confidence) }}
          </span>
          <n-tag v-if="result.analysis?.from_fallback" type="warning" size="small" :bordered="false">
            LLM 不可用 · fallback
          </n-tag>
        </div>
        <n-alert
          :type="verdictAlertType"
          :title="result.analysis?.summary || ''"
          :show-icon="false"
          class="mb-3"
        >
          <div v-if="matchedPatterns.length" class="mt-2">
            <div class="text-xs text-gray-500 mb-1">匹配到的已知反模式：</div>
            <n-space size="small">
              <n-tag
                v-for="p in matchedPatterns"
                :key="p.id"
                size="small"
                type="info"
                :bordered="false"
              >
                {{ p.id }}
              </n-tag>
            </n-space>
          </div>
        </n-alert>

        <n-collapse v-if="result.analysis?.report_md">
          <n-collapse-item title="详细诊断报告（Markdown）" name="report">
            <n-code :code="result.analysis.report_md" language="markdown" />
          </n-collapse-item>
        </n-collapse>
      </n-card>

      <!-- 补丁 -->
      <n-card
        v-if="hasPatch"
        title="修复补丁（unified diff）"
        size="small"
        class="mt-4"
      >
        <template #header-extra>
          <n-space>
            <n-tag
              v-for="tag in patchRiskTags"
              :key="tag"
              size="small"
              :type="riskTagType(tag)"
              :bordered="false"
            >
              {{ tag }}
            </n-tag>
            <n-button size="small" type="primary" @click="copyPatch">
              <template #icon>
                <n-icon><Icon icon="mdi:content-copy" /></n-icon>
              </template>
              复制
            </n-button>
            <n-button size="small" @click="downloadPatch">
              <template #icon>
                <n-icon><Icon icon="mdi:download" /></n-icon>
              </template>
              下载 .patch
            </n-button>
          </n-space>
        </template>

        <div v-if="result.patch?.rationale" class="text-sm text-gray-600 mb-2">
          <strong>修复思路：</strong>{{ result.patch.rationale }}
        </div>

        <div class="diff-code">
          <n-code :code="result.patch.patch" language="diff" />
        </div>

        <n-alert type="info" :show-icon="false" class="mt-3">
          Phase 1 仅展示补丁，不会自动写回脚本。请人工 review 后用
          <n-text code>git apply heal_xxxxxxxx.patch</n-text> 或编辑器手动应用。
        </n-alert>
      </n-card>

      <!-- 产品 bug 的提示 -->
      <n-card v-if="result && verdict === 'PRODUCT_BUG'" size="small" class="mt-4">
        <n-alert type="error" :show-icon="false">
          AI 判断这次失败更像是<strong>被测产品的 bug</strong>，请联系研发同学确认。脚本本次不做修改。
        </n-alert>
      </n-card>

      <!-- 失败兜底 -->
      <n-card v-if="errorMsg" size="small" class="mt-4">
        <n-alert type="error" title="诊断失败">
          {{ errorMsg }}
        </n-alert>
      </n-card>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { Icon } from '@iconify/vue'
import { useMessage } from 'naive-ui'
import api from '@/api'

const props = defineProps({
  show: { type: Boolean, default: false },
  scriptId: { type: String, default: '' },
  scriptName: { type: String, default: '' },
  testCaseId: { type: String, default: '' },
})

const emit = defineEmits(['update:show'])

const message = useMessage()

const visible = computed({
  get: () => props.show,
  set: (v) => emit('update:show', v),
})

const sessionId = ref('')
const status = ref('IDLE') // IDLE / PENDING / RUNNING / DONE / ERROR
const events = ref([])
const result = ref(null)
const errorMsg = ref('')
let eventSource = null
let pollingTimer = null

// ---------- lifecycle ----------
watch(visible, (v) => {
  if (v && props.scriptId) {
    startDiagnose()
  } else if (!v) {
    closeStream()
  }
})

onBeforeUnmount(() => {
  closeStream()
})

const reset = () => {
  closeStream()
  sessionId.value = ''
  status.value = 'IDLE'
  events.value = []
  result.value = null
  errorMsg.value = ''
}

const closeStream = () => {
  if (eventSource) {
    try { eventSource.close() } catch (e) {}
    eventSource = null
  }
  if (pollingTimer) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }
}

// ---------- main flow ----------
const startDiagnose = async () => {
  reset()
  if (!props.scriptId) {
    errorMsg.value = '缺少 scriptId'
    return
  }
  status.value = 'PENDING'
  try {
    const resp = await api.healDiagnose({
      script_id: props.scriptId,
      test_case_id: props.testCaseId || null,
    })
    if (!resp?.success || !resp.data?.session_id) {
      errorMsg.value = resp?.msg || '启动诊断失败'
      status.value = 'ERROR'
      return
    }
    sessionId.value = resp.data.session_id
    status.value = 'RUNNING'
    openStream(sessionId.value)
  } catch (e) {
    console.error(e)
    errorMsg.value = e?.message || '启动诊断失败'
    status.value = 'ERROR'
  }
}

const openStream = (sid) => {
  const url = api.healStreamUrl(sid)
  try {
    eventSource = new EventSource(url)
  } catch (e) {
    console.warn('EventSource 不可用，回退轮询', e)
    pollResult(sid)
    return
  }

  const knownEvents = [
    'diag.connected', 'diag.started', 'diag.heartbeat',
    'diag.evidence_collecting', 'diag.evidence_collected',
    'diag.analyzing', 'diag.verdict',
    'heal.proposing_patch', 'heal.patch_ready', 'heal.done',
    'diag.error', 'diag.closed',
  ]
  knownEvents.forEach((evName) => {
    eventSource.addEventListener(evName, (ev) => handleSseEvent(evName, ev))
  })
  eventSource.onerror = () => {
    // SSE 异常时回退到轮询，避免卡住
    console.warn('SSE 异常，回退轮询')
    closeStream()
    pollResult(sid)
  }
}

const handleSseEvent = (name, ev) => {
  let data = {}
  try { data = ev.data ? JSON.parse(ev.data) : {} } catch (e) {}
  if (name === 'diag.heartbeat') return

  events.value.push({ event: name, data, _receivedAt: Date.now() })

  if (name === 'heal.done' || name === 'diag.closed') {
    if (status.value !== 'ERROR') status.value = 'DONE'
    fetchResult(sessionId.value)
  } else if (name === 'diag.error') {
    status.value = 'ERROR'
    errorMsg.value = data?.message || '诊断异常'
    fetchResult(sessionId.value)
  }
}

const pollResult = (sid) => {
  pollingTimer = setInterval(async () => {
    try {
      const resp = await api.healGetResult(sid)
      if (!resp?.success) return
      const s = resp.data?.status
      if (s === 'DONE' || s === 'ERROR') {
        clearInterval(pollingTimer); pollingTimer = null
        status.value = s
        errorMsg.value = resp.data?.error || ''
        result.value = resp.data?.result || null
      }
    } catch (e) {
      console.warn('轮询失败', e)
    }
  }, 2000)
}

const fetchResult = async (sid) => {
  try {
    const resp = await api.healGetResult(sid)
    if (resp?.success) {
      result.value = resp.data?.result || null
      if (!errorMsg.value) errorMsg.value = resp.data?.error || ''
    }
  } catch (e) {
    console.warn('拉取最终结果失败', e)
  }
}

// ---------- computed ----------
const canRestart = computed(() => status.value === 'DONE' || status.value === 'ERROR')

const statusTagType = computed(() => {
  return {
    IDLE: 'default',
    PENDING: 'info',
    RUNNING: 'info',
    DONE: 'success',
    ERROR: 'error',
  }[status.value] || 'default'
})

const statusIcon = computed(() => {
  return {
    IDLE: 'mdi:circle-outline',
    PENDING: 'mdi:dots-horizontal-circle',
    RUNNING: 'mdi:loading',
    DONE: 'mdi:check-circle',
    ERROR: 'mdi:alert-circle',
  }[status.value] || 'mdi:help-circle'
})

const statusLabel = computed(() => {
  return {
    IDLE: '未开始',
    PENDING: '排队中',
    RUNNING: '诊断中',
    DONE: '已完成',
    ERROR: '失败',
  }[status.value] || status.value
})

const verdict = computed(() => result.value?.verdict || result.value?.analysis?.verdict || '')

const verdictLabel = computed(() => {
  return {
    SCRIPT_FIX: '判定：脚本错误（可生成补丁）',
    PRODUCT_BUG: '判定：疑似产品 bug',
    UNCERTAIN: '判定：不确定',
  }[verdict.value] || verdict.value || '未判定'
})

const verdictTagType = computed(() => {
  return {
    SCRIPT_FIX: 'warning',
    PRODUCT_BUG: 'error',
    UNCERTAIN: 'default',
  }[verdict.value] || 'default'
})

const verdictAlertType = computed(() => {
  return {
    SCRIPT_FIX: 'warning',
    PRODUCT_BUG: 'error',
    UNCERTAIN: 'info',
  }[verdict.value] || 'info'
})

const matchedPatterns = computed(() => {
  return result.value?.analysis?.matched_patterns || []
})

const hasPatch = computed(() => {
  return verdict.value === 'SCRIPT_FIX' && !!result.value?.patch?.patch
})

const patchRiskTags = computed(() => {
  return result.value?.patch?.risk_tags || []
})

const riskTagType = (tag) => {
  if (tag === 'touches_assert') return 'error'
  if (tag === 'introduces_delete') return 'error'
  if (tag === 'fallback') return 'warning'
  return 'info'
}

const formatConfidence = (v) => {
  if (v == null) return '—'
  if (typeof v === 'number') return `${Math.round(v * 100)}%`
  return v
}

const formatLocalTime = (ts) => {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString()
}

const timelineType = (evt) => {
  if (evt.event === 'diag.error') return 'error'
  if (evt.event === 'heal.done') return 'success'
  if (evt.event === 'diag.verdict') return 'info'
  if (evt.event === 'heal.patch_ready') return 'success'
  return 'default'
}

const timelineTitle = (evt) => {
  const titles = {
    'diag.connected': 'SSE 已连接',
    'diag.started': '诊断启动',
    'diag.evidence_collecting': '正在收集失败证据',
    'diag.evidence_collected': '失败证据收集完成',
    'diag.analyzing': '正在调用分析智能体',
    'diag.verdict': '分析结论已得出',
    'heal.proposing_patch': '正在生成修复补丁',
    'heal.patch_ready': '修复补丁已生成',
    'heal.done': '诊断流程完成',
    'diag.error': '诊断出错',
    'diag.closed': '会话关闭',
  }
  return titles[evt.event] || evt.event
}

const timelineContent = (evt) => {
  const d = evt.data || {}
  if (evt.event === 'diag.verdict') {
    return `verdict=${d.verdict || ''}，置信度 ${formatConfidence(d.confidence)}${d.from_fallback ? '（fallback）' : ''}`
  }
  if (evt.event === 'diag.evidence_collected') {
    return `有效信号：${d.has_useful_signal ? '是' : '否'}；Allure：${d.has_allure ? '有' : '无'}；用例：${d.test_case_name || '未指定'}`
  }
  if (evt.event === 'heal.patch_ready') {
    return `修复方法：${d.fixed_method || '—'}；风险标签：${(d.risk_tags || []).join(', ') || '—'}`
  }
  if (evt.event === 'diag.error') {
    return d.message || '未知错误'
  }
  return ''
}

// ---------- actions ----------
const copyPatch = async () => {
  if (!result.value?.patch?.patch) return
  try {
    await navigator.clipboard.writeText(result.value.patch.patch)
    message.success('补丁已复制到剪贴板')
  } catch (e) {
    message.error('复制失败')
  }
}

const downloadPatch = () => {
  if (!sessionId.value) return
  const url = api.healDownloadPatchUrl(sessionId.value)
  const link = document.createElement('a')
  link.href = url
  link.download = `heal_${sessionId.value.slice(0, 8)}.patch`
  link.click()
}
</script>

<style scoped>
.status-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
}

.session-id {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
  color: #999;
}

.grow {
  flex: 1;
}

.diff-code :deep(.n-code) {
  max-height: 360px;
  overflow: auto;
}
</style>

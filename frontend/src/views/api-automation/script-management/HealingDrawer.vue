<template>
  <n-drawer
    :show="show"
    :width="720"
    placement="right"
    :mask-closable="false"
    @update:show="(v) => emit('update:show', v)"
  >
    <n-drawer-content closable>
      <template #header>
        <div style="display: flex; align-items: center; gap: 8px;">
          <Icon icon="mdi:robot-confused-outline" style="font-size: 22px; color: #2080f0;" />
          <span style="font-size: 16px; font-weight: 600;">AI 智能诊断</span>
          <n-tag v-if="scriptName" size="small" type="info" style="margin-left: 4px;">
            {{ scriptName }}
          </n-tag>
        </div>
      </template>

      <!-- 步骤指示器 -->
      <n-steps :current="currentStep" :status="stepStatus" size="small" style="margin-bottom: 16px;">
        <n-step title="提取证据" description="收集失败上下文" />
        <n-step title="失败分析" description="判定 verdict" />
        <n-step title="补丁生成" description="仅 SCRIPT_FIX 触发" />
        <n-step title="完成" />
      </n-steps>

      <!-- 实时事件流 -->
      <n-card title="实时进度" size="small" embedded style="margin-bottom: 12px;">
        <div ref="eventListEl" style="max-height: 180px; overflow-y: auto; font-family: ui-monospace, SFMono-Regular, monospace; font-size: 12px;">
          <div v-if="events.length === 0" style="color: #999;">等待启动...</div>
          <div
            v-for="(evt, idx) in events"
            :key="idx"
            :style="{
              padding: '4px 0',
              borderBottom: idx < events.length - 1 ? '1px dashed #f0f0f0' : 'none',
              color: evt.event === 'diag.error' ? '#d03050' : (evt.event === 'heal.done' ? '#18a058' : '#444'),
            }"
          >
            <span style="color: #999;">{{ evt.tsLabel }}</span>
            <span style="font-weight: 600; margin: 0 6px;">{{ evt.event }}</span>
            <span style="color: #666;">{{ evt.label }}</span>
          </div>
        </div>
      </n-card>

      <!-- verdict 卡片 -->
      <n-card v-if="verdict" title="诊断结论" size="small" embedded style="margin-bottom: 12px;">
        <n-space vertical :size="8">
          <n-space align="center">
            <n-tag :type="verdictColor" :bordered="false" round size="medium">
              {{ verdict }}
            </n-tag>
            <span v-if="confidence !== null" style="color: #666; font-size: 12px;">
              置信度 {{ (confidence * 100).toFixed(0) }}%
            </span>
            <n-tag v-if="fromFallback.analysis" size="tiny" type="warning">分析回退</n-tag>
          </n-space>
          <div v-if="summary" style="color: #444; font-size: 13px; line-height: 1.6;">
            {{ summary }}
          </div>
        </n-space>
      </n-card>

      <!-- 补丁预览 -->
      <n-card v-if="hasPatch" size="small" embedded style="margin-bottom: 12px;">
        <template #header>
          <span style="font-size: 14px;">补丁预览</span>
          <n-tag v-if="fixedMethod" size="tiny" type="info" style="margin-left: 8px;">
            {{ fixedMethod }}
          </n-tag>
          <n-tag
            v-for="tag in riskTags"
            :key="tag"
            size="tiny"
            type="warning"
            style="margin-left: 4px;"
          >
            {{ tag }}
          </n-tag>
          <n-tag v-if="fromFallback.patch" size="tiny" type="warning" style="margin-left: 4px;">
            补丁回退
          </n-tag>
        </template>
        <pre style="margin: 0; max-height: 320px; overflow: auto; background: #f7f7f7; padding: 12px; border-radius: 4px; font-size: 12px; font-family: ui-monospace, SFMono-Regular, monospace; line-height: 1.5;"><span
          v-for="(line, i) in patchLines"
          :key="i"
          :style="diffLineStyle(line)"
        >{{ line }}
</span></pre>
      </n-card>

      <!-- 无补丁说明 -->
      <n-alert
        v-else-if="phase === 'done' && verdict && verdict !== 'SCRIPT_FIX'"
        type="info"
        size="small"
        style="margin-bottom: 12px;"
      >
        verdict={{ verdict }} —— 非脚本错误，未生成补丁。
        <template v-if="verdict === 'NEED_INFO'">建议补充失败上下文（stderr/截图）后重试。</template>
        <template v-else-if="verdict === 'DATA_FIX'">建议检查测试数据。</template>
        <template v-else-if="verdict === 'FLAKY'">建议重试或加重试机制。</template>
      </n-alert>

      <!-- 错误 -->
      <n-alert v-if="errorMsg" type="error" size="small" :title="'诊断失败'">
        {{ errorMsg }}
      </n-alert>

      <!-- 应用结果 -->
      <n-card
        v-if="applyResult"
        size="small"
        embedded
        style="margin-top: 12px;"
      >
        <template #header>
          <span style="font-size: 14px;">应用结果</span>
          <n-tag
            :type="applyResultTagType"
            size="tiny"
            style="margin-left: 8px;"
            :bordered="false"
          >
            {{ applyResult.status }}
          </n-tag>
        </template>
        <n-space vertical :size="6">
          <div style="font-size: 13px; color: #333;">{{ applyResult.message }}</div>
          <n-space size="small" v-if="applyResult.verified || applyResult.passed || applyResult.failed">
            <n-tag size="tiny" type="success">通过 {{ applyResult.passed || 0 }}</n-tag>
            <n-tag size="tiny" type="error">失败 {{ applyResult.failed || 0 }}</n-tag>
          </n-space>
          <n-collapse v-if="applyResult.log_tail" :default-expanded-names="[]">
            <n-collapse-item title="重跑日志末尾" name="log">
              <pre style="margin: 0; max-height: 220px; overflow: auto; background: #f7f7f7; padding: 8px; border-radius: 4px; font-size: 12px; font-family: ui-monospace, SFMono-Regular, monospace; line-height: 1.5;">{{ applyResult.log_tail }}</pre>
            </n-collapse-item>
          </n-collapse>
          <div
            v-if="applyResult.heal_failed_count !== undefined && applyResult.heal_failed_count > 0"
            style="font-size: 12px; color: #d03050;"
          >
            连续修复失败次数：{{ applyResult.heal_failed_count }} / 3（≥3 将熔断）
          </div>
        </n-space>
      </n-card>

      <template #footer>
        <n-space justify="end">
          <n-button @click="emit('update:show', false)" size="small">关闭</n-button>
          <n-button
            v-if="hasPatch"
            type="primary"
            size="small"
            @click="downloadPatch"
          >
            下载补丁 .patch
          </n-button>
          <n-popconfirm
            v-if="hasPatch && !applyResult"
            :positive-button-props="{ type: 'warning' }"
            @positive-click="onConfirmApply"
          >
            <template #trigger>
              <n-button type="warning" size="small" :loading="applying">
                应用并验证
              </n-button>
            </template>
            <div style="max-width: 320px;">
              即将把补丁写回脚本文件并触发 pytest 重跑该用例。
              <br />
              <strong>失败将自动回滚</strong>，但仍可能影响脚本最新版本，确认继续？
            </div>
          </n-popconfirm>
          <n-button
            v-if="phase === 'done' || phase === 'error'"
            type="info"
            size="small"
            ghost
            @click="startDiagnose"
          >
            重新诊断
          </n-button>
        </n-space>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup>
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import {
  NDrawer, NDrawerContent, NSteps, NStep, NCard, NTag, NSpace,
  NButton, NAlert, NPopconfirm, NCollapse, NCollapseItem, useMessage,
} from 'naive-ui'
import { Icon } from '@iconify/vue'
import api from '@/api'

const props = defineProps({
  show: { type: Boolean, default: false },
  scriptId: { type: String, default: '' },
  scriptName: { type: String, default: '' },
  testCaseId: { type: String, default: '' },
})

const emit = defineEmits(['update:show'])

const message = useMessage()

const sessionId = ref('')
const events = ref([])
const phase = ref('idle')  // idle / running / done / error
const errorMsg = ref('')
const verdict = ref('')
const confidence = ref(null)
const summary = ref('')
const patchText = ref('')
const fixedMethod = ref('')
const riskTags = ref([])
const fromFallback = ref({ analysis: false, patch: false })

const applying = ref(false)
const applyResult = ref(null)

const applyResultTagType = computed(() => {
  const s = applyResult.value?.status
  if (s === 'VERIFIED_PASS') return 'success'
  if (s === 'APPLIED') return 'info'
  if (s === 'ROLLED_BACK' || s === 'RERUN_ERROR') return 'error'
  if (s === 'PATCH_INVALID') return 'error'
  if (s === 'CIRCUIT_OPEN') return 'warning'
  return 'default'
})

const eventListEl = ref(null)
let eventSource = null

const EVENT_LABELS = {
  'diag.connected': '已连接到诊断会话',
  'diag.started': '诊断启动',
  'diag.evidence_collecting': '正在提取失败证据...',
  'diag.evidence_collected': '证据收集完成',
  'diag.analyzing': '正在调用 AI 分析失败原因...',
  'diag.verdict': '已得出 verdict',
  'heal.proposing_patch': '正在生成修复补丁...',
  'heal.patch_ready': '补丁已生成',
  'heal.done': '诊断完成',
  'diag.error': '诊断失败',
  'diag.heartbeat': '心跳',
  'diag.closed': '会话已关闭',
}

const PHASE_FOR_EVENT = {
  'diag.evidence_collecting': 0,
  'diag.evidence_collected': 1,
  'diag.analyzing': 1,
  'diag.verdict': 2,
  'heal.proposing_patch': 2,
  'heal.patch_ready': 3,
  'heal.done': 3,
}

const currentStep = computed(() => {
  if (phase.value === 'idle') return 0
  let step = 0
  for (const e of events.value) {
    const s = PHASE_FOR_EVENT[e.event]
    if (s !== undefined && s > step) step = s
  }
  // SCRIPT_FIX 才走到第 3 步（补丁），否则停在第 2 步
  if (phase.value === 'done' && verdict.value && verdict.value !== 'SCRIPT_FIX') {
    return Math.min(step, 2)
  }
  return step
})

const stepStatus = computed(() => {
  if (phase.value === 'error') return 'error'
  if (phase.value === 'done') return 'finish'
  if (phase.value === 'running') return 'process'
  return 'wait'
})

const verdictColor = computed(() => {
  const map = {
    SCRIPT_FIX: 'info',
    NEED_INFO: 'default',
    DATA_FIX: 'warning',
    FLAKY: 'warning',
    UNCERTAIN: 'default',
  }
  return map[verdict.value] || 'default'
})

const hasPatch = computed(() => phase.value === 'done' && verdict.value === 'SCRIPT_FIX' && patchText.value)

const patchLines = computed(() => (patchText.value || '').split('\n'))

const diffLineStyle = (line) => {
  if (line.startsWith('+++') || line.startsWith('---')) {
    return { display: 'block', color: '#666', fontWeight: 600 }
  }
  if (line.startsWith('@@')) {
    return { display: 'block', color: '#2080f0', fontWeight: 600 }
  }
  if (line.startsWith('+')) {
    return { display: 'block', backgroundColor: '#e6ffec', color: '#18a058' }
  }
  if (line.startsWith('-')) {
    return { display: 'block', backgroundColor: '#ffeef0', color: '#d03050' }
  }
  return { display: 'block', color: '#666' }
}

const pushEvent = (event, data) => {
  if (event === 'diag.heartbeat') return  // 心跳不展示
  const ts = new Date()
  const tsLabel = `${ts.getHours().toString().padStart(2,'0')}:${ts.getMinutes().toString().padStart(2,'0')}:${ts.getSeconds().toString().padStart(2,'0')}`
  let label = EVENT_LABELS[event] || ''
  if (event === 'diag.verdict' && data) {
    label = `${label}：${data.verdict || ''}${data.confidence !== undefined ? ` (置信度 ${(data.confidence*100).toFixed(0)}%)` : ''}`
  } else if (event === 'heal.patch_ready' && data) {
    label = `${label}：fixed_method=${data.fixed_method || '-'} risk=${(data.risk_tags||[]).join(',')||'-'}`
  } else if (event === 'diag.evidence_collected' && data) {
    label = `${label}（has_useful_signal=${data.has_useful_signal}, has_allure=${data.has_allure}）`
  } else if (event === 'diag.error' && data) {
    label = `${label}：${data.message || ''}`
  }
  events.value.push({ event, data, tsLabel, label })
  nextTick(() => {
    if (eventListEl.value) {
      eventListEl.value.scrollTop = eventListEl.value.scrollHeight
    }
  })
}

const reset = () => {
  closeSSE()
  events.value = []
  phase.value = 'idle'
  errorMsg.value = ''
  verdict.value = ''
  confidence.value = null
  summary.value = ''
  patchText.value = ''
  fixedMethod.value = ''
  riskTags.value = []
  fromFallback.value = { analysis: false, patch: false }
  sessionId.value = ''
  applyResult.value = null
  applying.value = false
}

const closeSSE = () => {
  if (eventSource) {
    try { eventSource.close() } catch (e) {}
    eventSource = null
  }
}

const startDiagnose = async () => {
  if (!props.scriptId) {
    message.error('缺少 script_id，无法发起诊断')
    return
  }
  reset()
  phase.value = 'running'
  try {
    const payload = { script_id: props.scriptId }
    if (props.testCaseId) payload.test_case_id = props.testCaseId
    const resp = await api.healDiagnose(payload)
    const sid = resp?.data?.session_id
    if (!sid) {
      throw new Error('后端未返回 session_id')
    }
    sessionId.value = sid
    openSSE(sid)
  } catch (e) {
    phase.value = 'error'
    errorMsg.value = e?.message || '启动诊断失败'
    message.error(errorMsg.value)
  }
}

const openSSE = (sid) => {
  closeSSE()
  const url = api.healStreamUrl(sid)
  eventSource = new EventSource(url)

  const handlers = [
    'diag.connected', 'diag.started',
    'diag.evidence_collecting', 'diag.evidence_collected',
    'diag.analyzing', 'diag.verdict',
    'heal.proposing_patch', 'heal.patch_ready',
    'heal.done', 'diag.error', 'diag.heartbeat', 'diag.closed',
  ]
  for (const evt of handlers) {
    eventSource.addEventListener(evt, (e) => {
      let data = {}
      try { data = JSON.parse(e.data) } catch {}
      pushEvent(evt, data)
      if (evt === 'diag.verdict') {
        verdict.value = data.verdict || ''
        confidence.value = data.confidence !== undefined ? Number(data.confidence) : null
        summary.value = data.summary || ''
        fromFallback.value.analysis = !!data.from_fallback
      } else if (evt === 'heal.patch_ready') {
        fixedMethod.value = data.fixed_method || ''
        riskTags.value = data.risk_tags || []
        fromFallback.value.patch = !!data.from_fallback
      } else if (evt === 'heal.done' || evt === 'diag.closed') {
        // 拿最终结果（含完整 patch 文本）
        finalizeResult()
      } else if (evt === 'diag.error') {
        phase.value = 'error'
        errorMsg.value = data.message || '诊断异常终止'
        closeSSE()
      }
    })
  }
  eventSource.onerror = () => {
    // 后端 SSE 关闭后浏览器会触发 error，这里不直接判错——交给 heal.done / closed 事件
  }
}

const finalizeResult = async () => {
  try {
    const resp = await api.healGetResult(sessionId.value)
    const data = resp?.data || {}
    if (data.status === 'ERROR') {
      phase.value = 'error'
      errorMsg.value = data.error || '诊断失败'
      return
    }
    const result = data.result || {}
    if (result.analysis) {
      verdict.value = result.verdict || verdict.value
      confidence.value = result.analysis.confidence !== undefined
        ? Number(result.analysis.confidence) : confidence.value
      summary.value = result.analysis.summary || summary.value
    }
    if (result.patch) {
      patchText.value = result.patch.patch || ''
      fixedMethod.value = result.patch.fixed_method || fixedMethod.value
      riskTags.value = result.patch.risk_tags || riskTags.value
    }
    phase.value = 'done'
    closeSSE()
  } catch (e) {
    phase.value = 'error'
    errorMsg.value = e?.message || '拉取诊断结果失败'
  }
}

const downloadPatch = () => {
  if (!sessionId.value) return
  const url = api.healDownloadPatchUrl(sessionId.value)
  window.open(url, '_blank')
}

const onConfirmApply = async () => {
  if (!sessionId.value) {
    message.error('当前没有有效的诊断会话')
    return
  }
  if (applying.value) return
  applying.value = true
  applyResult.value = null
  try {
    const resp = await api.healApplyPatch(sessionId.value, {
      rerun: true,
      environment: 'test',
    })
    const data = resp?.data || {}
    applyResult.value = data
    if (data.status === 'VERIFIED_PASS') {
      message.success('补丁已应用并验证通过')
    } else if (data.status === 'APPLIED') {
      message.success('补丁已应用（未触发验证）')
    } else if (data.status === 'CIRCUIT_OPEN') {
      message.warning(data.message || '已达熔断阈值')
    } else if (data.status === 'ROLLED_BACK') {
      message.warning('补丁验证失败，已自动回滚')
    } else if (data.status === 'RERUN_ERROR') {
      message.error('重跑异常，已回滚')
    } else if (data.status === 'PATCH_INVALID') {
      message.error('AI 补丁存在语法错误，已拒绝应用')
    } else {
      message.info(data.message || '已返回结果')
    }
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '应用补丁失败'
    message.error(msg)
    applyResult.value = {
      status: 'ERROR',
      message: msg,
      applied: false,
      verified: false,
    }
  } finally {
    applying.value = false
  }
}

// 抽屉打开时自动启动诊断；关闭时清理
watch(() => props.show, (v) => {
  if (v) {
    startDiagnose()
  } else {
    closeSSE()
  }
})

onUnmounted(() => closeSSE())
</script>

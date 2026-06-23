<template>
  <AppPage>
    <n-card title="UI 自动化（阶段二完成）">
      <n-space vertical size="large">
        <n-alert type="success" :show-icon="true">
          UI 自动化模块<strong>阶段二（多模态页面分析 + 脚本生成）已完成</strong>，可在左侧菜单进入"页面分析 / 脚本管理"使用。阶段三（脚本执行 + Playwright/MidScene runtime）规划中。
        </n-alert>

        <div>
          <h3>模块健康检查</h3>
          <n-space>
            <n-button type="primary" :loading="loading" @click="checkHealth">
              检测运行时依赖
            </n-button>
            <n-tag v-if="health" :type="statusType">
              {{ statusText }}
            </n-tag>
          </n-space>
        </div>

        <n-card v-if="health" embedded title="自检结果" size="small">
          <n-descriptions :column="1" bordered label-placement="left">
            <n-descriptions-item label="模块启用">
              {{ health.enabled ? '是' : '否' }}
            </n-descriptions-item>
            <n-descriptions-item label="整体状态">
              {{ health.status }}
            </n-descriptions-item>
            <n-descriptions-item v-for="(value, key) in health.checks" :key="key" :label="key">
              <pre class="check-pre">{{ JSON.stringify(value, null, 2) }}</pre>
            </n-descriptions-item>
          </n-descriptions>
        </n-card>

        <n-card embedded title="阶段路线" size="small">
          <n-timeline>
            <n-timeline-item type="success" title="阶段一：骨架与隔离 ✓" content="后端模块骨架、数据模型、UI_AUTOMATION 配置、generated_ui_tests 目录、菜单注册、健康检查接口" />
            <n-timeline-item type="success" title="阶段二：多模态页面分析 + 脚本生成 ✓" content="豆包视觉模型集成、PageAnalyzerAgent（识别/交互/用例三段）、UiScriptGeneratorAgent（Playwright/MidScene 三模板）、SSE 流式进度、降级模板兜底、前端页面分析 + 脚本管理上线" />
            <n-timeline-item type="info" title="阶段三：脚本执行" content="MidScene CLI + Playwright Node Worker、generated_ui_tests Node 工程骨架、执行队列、产物归档" />
            <n-timeline-item type="info" title="阶段四：报告与回溯" content="HTML 报告归档、失败视频/截图、AI 失败诊断（可选）" />
          </n-timeline>
        </n-card>
      </n-space>
    </n-card>
  </AppPage>
</template>

<script setup>
import { computed, ref } from 'vue'
import { request } from '@/utils'

const loading = ref(false)
const health = ref(null)

const statusType = computed(() => {
  if (!health.value) return 'default'
  if (health.value.status === 'ok') return 'success'
  if (health.value.status === 'degraded') return 'warning'
  return 'error'
})

const statusText = computed(() => {
  if (!health.value) return ''
  return `状态：${health.value.status}`
})

async function checkHealth() {
  loading.value = true
  try {
    const res = await request.get('/ui-automation/health')
    health.value = res?.data ?? res
    window.$message?.success('健康检查完成')
  } catch (err) {
    window.$message?.error('健康检查失败：' + (err?.message || err))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.check-pre {
  margin: 0;
  font-size: 12px;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>

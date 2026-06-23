<template>
  <AppPage>
    <n-card>
      <n-result
        status="info"
        :title="title"
        :description="description"
      >
        <template #icon>
          <n-icon size="80" :color="iconColor">
            <Icon :icon="icon" />
          </n-icon>
        </template>
        <template #footer>
          <n-space vertical align="center">
            <n-tag :type="tagType" round>阶段 {{ phase }} 上线</n-tag>
            <p class="phase-note">
              该模块作为 UI 自动化菜单的占位项目预留，将在对应阶段上线对应功能。
            </p>
          </n-space>
        </template>
      </n-result>
    </n-card>
  </AppPage>
</template>

<script setup>
import { Icon } from '@iconify/vue'

const props = defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
  icon: { type: String, default: 'mdi:construction' },
  iconColor: { type: String, default: '#3b82f6' },
  phase: { type: String, default: '二' },
  tagType: { type: String, default: 'info' },
})
</script>

<style scoped>
.phase-note {
  color: #888;
  font-size: 13px;
  margin: 0;
}
</style>

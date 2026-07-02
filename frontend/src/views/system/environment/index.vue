<template>
  <div class="env-management">
    <n-card class="mb-4">
      <div class="flex justify-between items-center">
        <div class="flex items-center gap-3">
          <n-input
            v-model:value="keyword"
            placeholder="按标识/中文名搜索..."
            clearable
            style="width: 260px"
            @keyup.enter="loadList"
          >
            <template #prefix><n-icon><Icon icon="mdi:magnify" /></n-icon></template>
          </n-input>
          <n-button @click="loadList">
            <template #icon><n-icon><Icon icon="mdi:refresh" /></n-icon></template>
            刷新
          </n-button>
        </div>
        <n-space>
          <n-button
            v-if="hasActiveEnv"
            type="warning"
            @click="onDeactivateAll"
          >
            <template #icon><n-icon><Icon icon="mdi:power-off" /></n-icon></template>
            停用所有（回退 .env）
          </n-button>
          <n-button type="primary" @click="openCreateModal">
            <template #icon><n-icon><Icon icon="mdi:plus" /></n-icon></template>
            新建环境
          </n-button>
        </n-space>
      </div>
    </n-card>

    <n-card>
      <n-alert v-if="!hasActiveEnv" type="warning" :bordered="false" class="mb-3">
        当前**没有激活环境**，API/UI 自动化会走 `.env` + YAML 兜底（现状不变）。
      </n-alert>
      <n-alert v-else type="success" :bordered="false" class="mb-3">
        当前激活：<strong>{{ activeEnv.label }}</strong>（{{ activeEnv.name }}）
      </n-alert>

      <n-data-table
        :columns="columns"
        :data="list"
        :loading="loading"
        :row-key="(row) => row.env_id"
        :max-height="600"
      />
    </n-card>

    <!-- 新建/编辑 Modal -->
    <n-modal v-model:show="modalShow" title="环境配置" style="width: 640px">
      <n-card>
        <n-form :model="form" label-placement="left" label-width="120px" :rules="rules" ref="formRef">
          <n-form-item label="环境标识" path="name" required>
            <n-input
              v-model:value="form.name"
              placeholder="test / staging / prod / 自定义（对应 pytest --env 参数）"
              :disabled="modalEditing && form.is_active"
            />
          </n-form-item>
          <n-form-item label="中文名" path="label" required>
            <n-input v-model:value="form.label" placeholder="如: 测试环境" />
          </n-form-item>
          <n-form-item label="API base URL">
            <n-input v-model:value="form.api_base_url" placeholder="https://api.example.com" />
          </n-form-item>
          <n-form-item label="UI base URL">
            <n-input v-model:value="form.ui_base_url" placeholder="https://ui.example.com" />
          </n-form-item>
          <n-form-item label="UI 登录页 URL">
            <n-input v-model:value="form.ui_login_url" placeholder="https://ui.example.com/login" />
          </n-form-item>
          <n-form-item label="登录账号">
            <n-input v-model:value="form.username" placeholder="superadmin" />
          </n-form-item>
          <n-form-item label="登录密码">
            <n-input
              v-model:value="form.password"
              type="password"
              show-password-on="click"
              :placeholder="modalEditing ? '不填则保留原密码' : '****'"
            />
          </n-form-item>
          <n-form-item label="备注">
            <n-input v-model:value="form.notes" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
          </n-form-item>
        </n-form>
        <n-space justify="end" class="mt-4">
          <n-button @click="modalShow = false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="onSave">保存</n-button>
        </n-space>
      </n-card>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted } from 'vue'
import { NButton, NTag, NSpace, useMessage, useDialog } from 'naive-ui'
import { Icon } from '@iconify/vue'
import api from '@/api'

defineOptions({ name: '环境管理' })

const message = useMessage()
const dialog = useDialog()

const keyword = ref('')
const list = ref([])
const loading = ref(false)

const activeEnv = computed(() => list.value.find(e => e.is_active) || null)
const hasActiveEnv = computed(() => !!activeEnv.value)

const modalShow = ref(false)
const modalEditing = ref(false)
const saving = ref(false)
const formRef = ref(null)
const form = ref({
  env_id: '',
  name: '',
  label: '',
  api_base_url: '',
  ui_base_url: '',
  ui_login_url: '',
  username: '',
  password: '',
  notes: '',
  is_active: false,
})

const rules = {
  name: [{ required: true, message: '请填写环境标识', trigger: ['blur', 'input'] }],
  label: [{ required: true, message: '请填写中文名', trigger: ['blur', 'input'] }],
}

const columns = [
  {
    title: '状态',
    key: 'is_active',
    width: 80,
    render: (row) => row.is_active
      ? h(NTag, { type: 'success', size: 'small' }, () => '✓ 激活')
      : h('span', { style: 'color: #999;' }, '—'),
  },
  { title: '标识', key: 'name', width: 120 },
  { title: '中文名', key: 'label', width: 160 },
  {
    title: 'API base URL',
    key: 'api_base_url',
    ellipsis: { tooltip: true },
    render: (row) => row.api_base_url || h('span', { style: 'color: #ccc;' }, '-'),
  },
  {
    title: 'UI base URL',
    key: 'ui_base_url',
    ellipsis: { tooltip: true },
    render: (row) => row.ui_base_url || h('span', { style: 'color: #ccc;' }, '-'),
  },
  {
    title: '账号',
    key: 'username',
    width: 120,
    render: (row) => row.username || h('span', { style: 'color: #ccc;' }, '-'),
  },
  { title: '更新时间', key: 'updated_at', width: 170,
    render: (row) => row.updated_at ? String(row.updated_at).replace('T', ' ').slice(0, 19) : '-' },
  {
    title: '操作',
    key: 'actions',
    width: 240,
    fixed: 'right',
    render: (row) => h(NSpace, { size: 'small' }, () => [
      !row.is_active
        ? h(NButton, {
          size: 'small',
          type: 'primary',
          onClick: () => onActivate(row),
        }, () => '激活')
        : null,
      h(NButton, {
        size: 'small',
        onClick: () => openEditModal(row),
      }, () => '编辑'),
      h(NButton, {
        size: 'small',
        type: 'error',
        disabled: row.is_active,
        onClick: () => onDelete(row),
      }, () => '删除'),
    ].filter(Boolean)),
  },
]

async function loadList() {
  loading.value = true
  try {
    const res = await api.listEnvironments(keyword.value ? { keyword: keyword.value } : {})
    const data = res?.data ?? res
    list.value = data?.items || []
  } catch (e) {
    message.error('加载失败：' + (e?.response?.data?.detail || e.message || e))
  } finally {
    loading.value = false
  }
}

function openCreateModal() {
  modalEditing.value = false
  form.value = {
    env_id: '',
    name: '',
    label: '',
    api_base_url: '',
    ui_base_url: '',
    ui_login_url: '',
    username: '',
    password: '',
    notes: '',
    is_active: false,
  }
  modalShow.value = true
}

function openEditModal(row) {
  modalEditing.value = true
  form.value = {
    env_id: row.env_id,
    name: row.name,
    label: row.label,
    api_base_url: row.api_base_url || '',
    ui_base_url: row.ui_base_url || '',
    ui_login_url: row.ui_login_url || '',
    username: row.username || '',
    password: '',          // 编辑时不回填明文密码（后端也不返回），空表示保留原值
    notes: row.notes || '',
    is_active: row.is_active,
  }
  modalShow.value = true
}

async function onSave() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    const payload = { ...form.value }
    delete payload.env_id
    delete payload.is_active

    // 编辑时空密码不下发（后端 update 会保留原密码）
    if (modalEditing.value && !payload.password) {
      delete payload.password
    }

    if (modalEditing.value) {
      await api.updateEnvironment(form.value.env_id, payload)
      message.success('已更新')
    } else {
      await api.createEnvironment(payload)
      message.success('已新建')
    }
    modalShow.value = false
    loadList()
  } catch (e) {
    message.error('保存失败：' + (e?.response?.data?.detail || e.message || e))
  } finally {
    saving.value = false
  }
}

async function onActivate(row) {
  dialog.warning({
    title: '激活环境',
    content: `确认激活「${row.label}」？API/UI 自动化下次执行会用这个环境的 URL/账号。`,
    positiveText: '激活',
    onPositiveClick: async () => {
      try {
        await api.activateEnvironment(row.env_id)
        message.success(`已激活: ${row.label}`)
        loadList()
      } catch (e) {
        message.error('激活失败：' + (e?.response?.data?.detail || e.message || e))
      }
    },
  })
}

async function onDelete(row) {
  dialog.warning({
    title: '删除环境',
    content: `确认删除「${row.label}」？此操作不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.deleteEnvironment(row.env_id)
        message.success('已删除')
        loadList()
      } catch (e) {
        message.error('删除失败：' + (e?.response?.data?.detail || e.message || e))
      }
    },
  })
}

async function onDeactivateAll() {
  dialog.warning({
    title: '停用所有激活环境',
    content: '停用后 API/UI 自动化会回退到 .env + YAML 兜底配置。确认吗？',
    positiveText: '停用',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.deactivateAllEnvironments()
        message.success('已停用所有环境')
        loadList()
      } catch (e) {
        message.error('停用失败：' + (e?.response?.data?.detail || e.message || e))
      }
    },
  })
}

onMounted(loadList)
</script>

<style scoped>
.env-management {
  padding: 20px;
}
.mb-4 { margin-bottom: 16px; }
.mb-3 { margin-bottom: 12px; }
.mt-4 { margin-top: 16px; }
.flex { display: flex; }
.justify-between { justify-content: space-between; }
.items-center { align-items: center; }
.gap-3 { gap: 12px; }
</style>

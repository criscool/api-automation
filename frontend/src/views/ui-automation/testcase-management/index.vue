<template>
  <div class="ui-testcase-management">
    <!-- 工具栏 -->
    <n-card class="mb-4">
      <div class="flex justify-between items-center">
        <div class="flex items-center gap-3">
          <n-input
            v-model:value="searchKeyword"
            placeholder="搜索脚本..."
            clearable
            style="width: 260px"
            @keyup.enter="loadScripts"
          >
            <template #prefix><n-icon><Icon icon="mdi:magnify" /></n-icon></template>
          </n-input>
          <n-select
            v-model:value="filterScriptType"
            :options="scriptTypeOptions"
            placeholder="脚本类型"
            clearable
            style="width: 160px"
            @update:value="loadScripts"
          />
          <n-select
            v-model:value="filterSourceType"
            :options="sourceTypeOptions"
            placeholder="来源"
            clearable
            style="width: 120px"
            @update:value="loadScripts"
          />
        </div>
        <n-space>
          <n-button @click="showAutoExtract = true">
            <template #icon><n-icon><Icon icon="mdi:auto-fix" /></n-icon></template>
            自动提取
          </n-button>
          <n-button @click="treeEditMode = !treeEditMode" :type="treeEditMode ? 'warning' : 'default'">
            <template #icon><n-icon><Icon icon="mdi:pencil" /></n-icon></template>
            {{ treeEditMode ? '退出编辑' : '编辑分类' }}
          </n-button>
          <n-button v-if="treeEditMode" type="info" @click="addRootCategory">
            <template #icon><n-icon><Icon icon="mdi:plus-box-outline" /></n-icon></template>
            新建根分类
          </n-button>
          <n-button @click="refreshAll">
            <template #icon><n-icon><Icon icon="mdi:refresh" /></n-icon></template>
            刷新
          </n-button>
        </n-space>
      </div>
    </n-card>

    <!-- 主体：左右分栏 -->
    <div class="main-layout">
      <!-- 左侧：分类树 -->
      <div class="tree-panel">
        <n-card size="small" :content-style="{ padding: '8px' }">
          <template #header>
            <div class="flex items-center gap-2">
              <span>脚本分类</span>
              <n-tag :bordered="false" type="info" size="small" round>
                {{ totalScriptCount }}
              </n-tag>
            </div>
          </template>
          <div v-if="categoryTree.length === 0 && !treeLoading" class="text-center text-gray-400 py-8">
            暂无分类，点击"自动提取"或"编辑分类"新建
          </div>
          <n-spin :show="treeLoading">
            <n-tree
              :data="categoryTree"
              :selected-keys="[selectedCategoryId]"
              :render-label="renderTreeLabel"
              :render-prefix="renderTreePrefix"
              :node-props="treeNodeProps"
              key-field="category_id"
              children-field="children"
              block-line
              selectable
              @update:selected-keys="onTreeSelect"
            />
          </n-spin>
          <!-- 未分类 -->
          <div
            class="uncategorized-node"
            :class="{ active: selectedCategoryId === '__uncategorized__' }"
            @click="selectUncategorized"
          >
            <Icon icon="mdi:folder-open-outline" class="mr-2" />
            <span>未分类</span>
            <n-tag size="tiny" class="ml-auto">{{ uncategorizedCount }}</n-tag>
          </div>
        </n-card>
      </div>

      <!-- 右侧：脚本列表 -->
      <div class="table-panel">
        <n-card size="small" :content-style="{ padding: '12px' }">
          <template #header>
            <div class="flex justify-between items-center">
              <span>{{ currentCategoryName }}</span>
              <n-space v-if="selectedIds.length > 0">
                <n-text depth="3">已选 {{ selectedIds.length }} 条</n-text>
                <n-popover trigger="click" placement="bottom-end" :show-arrow="false" raw
                  style="border-radius: 6px; box-shadow: 0 4px 16px rgba(0,0,0,0.12); background: var(--n-color);">
                  <template #trigger>
                    <n-button size="small">移动到...</n-button>
                  </template>
                  <div style="width: 260px; padding: 8px;">
                    <div class="move-option-uncategorized" @click="onBatchMoveSelect('__uncategorized__')">
                      <Icon icon="mdi:folder-open-outline" style="margin-right: 6px" />
                      未分类
                    </div>
                    <div style="max-height: 50vh; overflow-y: auto; margin-top: 4px">
                      <n-tree
                        :data="categoryTree"
                        key-field="category_id"
                        label-field="name"
                        children-field="children"
                        block-line
                        :node-props="moveTreeNodeProps"
                        default-expand-all
                      />
                    </div>
                  </div>
                </n-popover>
              </n-space>
            </div>
          </template>

          <n-data-table
            :columns="scriptColumns"
            :data="scripts"
            :loading="tableLoading"
            :row-key="(row) => row.script_id"
            :scroll-x="1000"
            :max-height="500"
            v-model:checked-row-keys="selectedIds"
          />

          <div class="pagination-wrapper">
            <n-pagination
              v-model:page="pagination.page"
              v-model:page-size="pagination.pageSize"
              :item-count="pagination.itemCount"
              :page-sizes="[15, 30, 50]"
              show-size-picker
              show-quick-jumper
              @update:page="loadScripts"
              @update:page-size="loadScripts"
            />
          </div>
        </n-card>
      </div>
    </div>

    <!-- 自动提取弹窗 -->
    <n-modal v-model:show="showAutoExtract" title="自动提取分类" style="width: 500px">
      <n-card>
        <p class="mb-4 text-gray-500">根据脚本的 base_url 域名自动建议分类树</p>
        <div v-if="suggestedTree.length > 0">
          <div v-for="node in suggestedTree" :key="node.key" class="flex items-center gap-2 py-1">
            <Icon icon="mdi:folder-outline" />
            <span>{{ node.name }}</span>
            <n-tag size="tiny">{{ node.script_count }} 个脚本</n-tag>
          </div>
        </div>
        <div v-else class="text-center text-gray-400 py-4">无法提取分类，请手动创建</div>
        <template #footer>
          <n-button @click="showAutoExtract = false">关闭</n-button>
          <n-button type="primary" @click="applyAutoExtract" :loading="applying">一键创建</n-button>
        </template>
      </n-card>
    </n-modal>

    <!-- 编辑分类弹窗 -->
    <n-modal v-model:show="editModal.show" title="编辑分类">
      <n-card style="width: 420px">
        <n-form :model="editModal.form" label-placement="left" label-width="80px">
          <n-form-item label="分类名称">
            <n-input v-model:value="editModal.form.name" />
          </n-form-item>
          <n-form-item label="匹配规则">
            <n-input v-model:value="editModal.form.match_rule" placeholder="glob 规则，如 *172.16.8.190*" />
          </n-form-item>
          <n-form-item label="描述">
            <n-input v-model:value="editModal.form.description" type="textarea" :rows="2" />
          </n-form-item>
        </n-form>
        <template #footer>
          <n-space>
            <n-button @click="editModal.show = false">取消</n-button>
            <n-button type="primary" @click="saveEditCategory">保存</n-button>
          </n-space>
        </template>
      </n-card>
    </n-modal>

    <!-- 新建分类弹窗 -->
    <n-modal v-model:show="createModal.show" title="新建分类">
      <n-card style="width: 380px">
        <n-form :model="createModal.form" label-placement="left" label-width="80px">
          <n-form-item label="分类名称">
            <n-input v-model:value="createModal.form.name" />
          </n-form-item>
          <n-form-item label="描述">
            <n-input v-model:value="createModal.form.description" type="textarea" :rows="2" />
          </n-form-item>
        </n-form>
        <template #footer>
          <n-space>
            <n-button @click="createModal.show = false">取消</n-button>
            <n-button type="primary" @click="doCreateCategory">创建</n-button>
          </n-space>
        </template>
      </n-card>
    </n-modal>

    <!-- 脚本详情弹窗 -->
    <n-modal v-model:show="detailModal.show" title="脚本详情" preset="card" style="width: 800px; max-width: 96vw" :mask-closable="false">
      <n-form v-if="detailModal.data" label-placement="left" label-width="80px">
        <n-grid :cols="2" :x-gap="16">
          <n-form-item-gi label="脚本名称">
            <n-text>{{ detailModal.data.name }}</n-text>
          </n-form-item-gi>
          <n-form-item-gi label="脚本类型">
            <n-tag size="small" :bordered="false">{{ detailModal.data.script_type }}</n-tag>
          </n-form-item-gi>
          <n-form-item-gi label="来源">
            <n-tag size="small" :bordered="false" type="info">{{ detailModal.data.source_type }}</n-tag>
          </n-form-item-gi>
          <n-form-item-gi label="状态">
            <n-tag size="small" :type="detailModal.data.status === 'active' ? 'success' : 'default'">{{ detailModal.data.status }}</n-tag>
          </n-form-item-gi>
          <n-form-item-gi label="Base URL" :span="2">
            <n-text depth="2">{{ detailModal.data.base_url || '-' }}</n-text>
          </n-form-item-gi>
          <n-form-item-gi label="文件路径" :span="2">
            <n-text depth="3" class="text-xs">{{ detailModal.data.file_path || '-' }}</n-text>
          </n-form-item-gi>
          <n-form-item-gi label="描述" :span="2">
            <n-text depth="2">{{ detailModal.data.description || '-' }}</n-text>
          </n-form-item-gi>
          <n-form-item-gi :span="2" label="脚本内容">
            <n-input
              :value="detailModal.data.content || ''"
              type="textarea"
              readonly
              :autosize="{ minRows: 10, maxRows: 20 }"
              class="code-area"
            />
          </n-form-item-gi>
        </n-grid>
      </n-form>
      <template #action>
        <n-button @click="detailModal.show = false">关闭</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, reactive, h, onMounted } from 'vue'
import { useMessage, NTag, NButton, NIcon, NText, NInput, NSpace } from 'naive-ui'
import { Icon } from '@iconify/vue'
import api from '@/api'

const message = useMessage()

// ==================== 状态 ====================
const searchKeyword = ref('')
const filterScriptType = ref(null)
const filterSourceType = ref(null)
const selectedCategoryId = ref(null)
const selectedIds = ref([])
const treeEditMode = ref(false)
const showAutoExtract = ref(false)
const treeLoading = ref(false)
const tableLoading = ref(false)
const applying = ref(false)
const tableKey = ref(0)

// 分类树
const categoryTree = ref([])
const uncategorizedCount = ref(0)
const totalScriptCount = ref(0)
const currentCategoryName = ref('全部脚本')

// 脚本列表
const scripts = ref([])
const pagination = reactive({ page: 1, pageSize: 20, itemCount: 0 })

// 自动提取
const suggestedTree = ref([])

// 编辑弹窗
const editModal = reactive({
  show: false,
  form: { name: '', match_rule: '', description: '' },
  categoryId: '',
})

// 新建弹窗
const createModal = reactive({
  show: false,
  form: { name: '', description: '' },
  parentId: null,
})

// 详情弹窗
const detailModal = reactive({
  show: false,
  data: null,
})

// ==================== 选项 ====================
const scriptTypeOptions = [
  { label: 'Playwright', value: 'playwright' },
  { label: 'Playwright MidScene', value: 'playwright_midscene' },
  { label: 'YAML MidScene', value: 'yaml_midscene' },
]

const sourceTypeOptions = [
  { label: 'AI 生成', value: 'ai' },
  { label: '手动', value: 'manual' },
  { label: '录制', value: 'recorded' },
]

// ==================== 表格列定义 ====================
const scriptColumns = [
  { type: 'selection' },
  {
    title: '脚本名称', key: 'name', width: 200,
    render(row) {
      return h(NText, { depth: 1 }, { default: () => row.name })
    },
  },
  {
    title: '脚本类型', key: 'script_type', width: 100,
    render(row) {
      const map = { playwright: 'Playwright', playwright_midscene: 'MidScene', yaml_midscene: 'YAML' }
      const label = map[row.script_type] || row.script_type
      return h(NTag, { size: 'small', bordered: false }, { default: () => label })
    },
  },
  {
    title: '来源', key: 'source_type', width: 80,
    render(row) {
      const map = { ai: 'AI', manual: '手动', recorded: '录制' }
      const typeMap = { ai: 'info', manual: 'default', recorded: 'success' }
      return h(NTag, { size: 'small', bordered: false, type: typeMap[row.source_type] || 'default' }, { default: () => map[row.source_type] || row.source_type })
    },
  },
  { title: 'Base URL', key: 'base_url', width: 180, ellipsis: { tooltip: true } },
  {
    title: '状态', key: 'status', width: 80,
    render(row) {
      const map = { active: '启用', draft: '草稿', disabled: '禁用', archived: '归档' }
      const colorMap = { active: 'success', draft: 'warning', disabled: 'error', archived: 'default' }
      return h(NTag, { size: 'small', type: colorMap[row.status] || 'default' }, { default: () => map[row.status] || row.status })
    },
  },
  {
    title: '分类', key: 'category_name', width: 120,
    render(row) {
      return row.category_name
        ? h(NTag, { size: 'small', bordered: false, type: 'info' }, { default: () => row.category_name })
        : h(NText, { depth: 3 }, { default: () => '未分类' })
    },
  },
  {
    title: '创建人', key: 'created_by', width: 80,
  },
  {
    title: '操作', key: 'actions', width: 140, fixed: 'right',
    render(row) {
      return h(NSpace, { size: 'small' }, {
        default: () => [
          h(NButton, { size: 'tiny', onClick: () => showScriptDetail(row) }, { default: () => '详情' }),
          h(NButton, { size: 'tiny', type: 'primary', onClick: () => runScript(row) }, { default: () => '执行' }),
        ]
      })
    },
  },
]

// ==================== 分类树渲染 ====================
function renderTreeLabel({ option }) {
  if (treeEditMode.value) {
    return h('div', { class: 'tree-label-editing flex items-center' }, [
      h('span', option.name),
      h(NTag, { size: 'tiny', class: 'ml-1' }, { default: () => String(option.script_count) }),
      h(NSpace, { size: 2, class: 'ml-2' }, [
        h(NButton, {
          size: 'tiny', text: true,
          onClick: (e) => { e.stopPropagation(); openEditCategory(option) },
        }, { icon: () => h(Icon, { icon: 'mdi:pencil' }) }),
        h(NButton, {
          size: 'tiny', text: true,
          onClick: (e) => { e.stopPropagation(); openAddChildCategory(option) },
        }, { icon: () => h(Icon, { icon: 'mdi:plus-circle-outline' }) }),
        h(NButton, {
          size: 'tiny', text: true, type: 'error',
          onClick: (e) => { e.stopPropagation(); confirmDeleteCategory(option) },
        }, { icon: () => h(Icon, { icon: 'mdi:delete-outline' }) }),
      ]),
    ])
  }
  return h('div', { class: 'tree-label flex items-center' }, [
    h('span', option.name),
    h(NTag, { size: 'tiny', class: 'ml-2' }, { default: () => String(option.script_count || 0) }),
  ])
}

function openEditCategory(node) {
  editModal.show = true
  editModal.categoryId = node.category_id
  editModal.form = {
    name: node.name,
    match_rule: node.match_rule || '',
    description: node.description || '',
  }
}

function openAddChildCategory(node) {
  createModal.show = true
  createModal.form = { name: '', description: '' }
  createModal.parentId = node.category_id
}

function confirmDeleteCategory(node) {
  if (!confirm(`确定删除分类"${node.name}"？子节点将上移，脚本变未分类。`)) return
  deleteCategory(node.category_id)
}

function renderTreePrefix({ option }) {
  const icons = ['mdi:folder', 'mdi:folder-outline', 'mdi:file-document-outline']
  const lvl = Math.min(option.level || 0, 2)
  return h(Icon, { icon: icons[lvl], style: 'color: var(--n-color-target)' })
}

function treeNodeProps({ option }) {
  return {
    onClick() {
      treeEditMode.value = false
      selectedCategoryId.value = option.category_id
      currentCategoryName.value = option.name
      pagination.page = 1
      loadScripts()
    },
  }
}

function moveTreeNodeProps({ option }) {
  return {
    onClick() {
      onBatchMoveSelect(option.category_id)
    },
  }
}

async function showScriptDetail(row) {
  try {
    const res = await api.uiGetScript(row.script_id)
    if (res.success) {
      detailModal.data = res.data
      detailModal.show = true
    }
  } catch (e) {
    message.error('加载脚本详情失败')
  }
}

async function runScript(row) {
  try {
    const res = await api.uiTriggerExecution({
      script_id: row.script_id,
      triggered_by: 'frontend',
    })
    if (!res.success) {
      message.error('触发执行失败')
      return
    }
    const { execution_id, session_id, sse_endpoint } = res.data
    message.success('正在执行...请到「执行报告」查看结果')

    // 后台连 SSE 触发实际执行（不阻塞页面）
    const evtSource = new EventSource(sse_endpoint)
    evtSource.addEventListener('message', (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.is_final) {
          evtSource.close()
        }
      } catch {}
    })
    evtSource.addEventListener('error', () => evtSource.close())
  } catch (e) {
    message.error('执行失败')
  }
}

// ==================== 数据加载 ====================
async function loadCategoryTree() {
  treeLoading.value = true
  try {
    const res = await api.uiGetCategoryTree()
    if (res.success) {
      categoryTree.value = res.data.tree || []
      uncategorizedCount.value = res.data.uncategorized_count || 0
      totalScriptCount.value = res.data.total_count || 0
    }
  } catch (e) {
    message.error('加载分类树失败')
  } finally {
    treeLoading.value = false
  }
}

async function loadScripts() {
  tableLoading.value = true
  try {
    const params = {
      page: pagination.page,
      page_size: pagination.pageSize,
      keyword: searchKeyword.value || undefined,
      script_type: filterScriptType.value || undefined,
      source_type: filterSourceType.value || undefined,
    }
    if (selectedCategoryId.value === '__uncategorized__') {
      params.uncategorized = true
    } else if (selectedCategoryId.value) {
      params.category_id = selectedCategoryId.value
    }

    const res = await api.uiListScripts(params)
    if (res.success) {
      scripts.value = res.data.items || []
      pagination.itemCount = res.data.total || 0
    }
  } catch (e) {
    message.error('加载脚本列表失败')
  } finally {
    tableLoading.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadCategoryTree(), loadScripts()])
}

function onTreeSelect(keys) {
  if (keys.length > 0) {
    selectedCategoryId.value = keys[0]
    // 找到节点名称
    const findNode = (tree, id) => {
      for (const n of tree) {
        if (n.category_id === id) return n
        if (n.children) {
          const r = findNode(n.children, id)
          if (r) return r
        }
      }
      return null
    }
    const node = findNode(categoryTree.value, keys[0])
    currentCategoryName.value = node?.name || '分类'
    pagination.page = 1
    loadScripts()
  }
}

function selectUncategorized() {
  selectedCategoryId.value = '__uncategorized__'
  currentCategoryName.value = '未分类'
  pagination.page = 1
  loadScripts()
}

// ==================== 分类操作 ====================
function addRootCategory() {
  createModal.show = true
  createModal.form = { name: '', description: '' }
  createModal.parentId = null
}

async function doCreateCategory() {
  if (!createModal.form.name.trim()) {
    message.warning('请输入分类名称')
    return
  }
  try {
    await api.uiCreateCategory({
      name: createModal.form.name,
      parent_id: createModal.parentId,
      description: createModal.form.description,
    })
    message.success('创建成功')
    createModal.show = false
    loadCategoryTree()
  } catch (e) {
    message.error('创建失败')
  }
}

async function saveEditCategory() {
  try {
    await api.uiUpdateCategory(editModal.categoryId, {
      name: editModal.form.name,
      match_rule: editModal.form.match_rule || null,
      description: editModal.form.description,
    })
    message.success('保存成功')
    editModal.show = false
    loadCategoryTree()
  } catch (e) {
    message.error('保存失败')
  }
}

async function deleteCategory(categoryId) {
  if (!confirm('确定删除此分类？子节点会上移，脚本变未分类。')) return
  try {
    await api.uiDeleteCategory(categoryId)
    message.success('已删除')
    loadCategoryTree()
    loadScripts()
  } catch (e) {
    message.error('删除失败')
  }
}

// ==================== 批量移动 ====================
async function onBatchMoveSelect(categoryId) {
  if (selectedIds.value.length === 0) return
  try {
    const body = { script_ids: selectedIds.value }
    if (categoryId !== '__uncategorized__') {
      body.category_id = categoryId
    }
    await api.uiBatchMoveScripts(body)
    message.success(`已移动 ${selectedIds.value.length} 个脚本`)
    selectedIds.value = []
    loadScripts()
    loadCategoryTree()
  } catch (e) {
    message.error('移动失败')
  }
}

// ==================== 自动提取 ====================
async function loadSuggestedTree() {
  try {
    const res = await api.uiAutoExtractCategories()
    if (res.success) {
      suggestedTree.value = res.data.suggested_tree || []
    }
  } catch (e) {
    message.error('自动提取失败')
  }
}

async function applyAutoExtract() {
  applying.value = true
  try {
    for (const node of suggestedTree.value) {
      await api.uiCreateCategory({
        name: node.name,
        description: `自动提取: ${node.domain || node.name}`,
      })
    }
    message.success('分类创建完成')
    showAutoExtract.value = false
    loadCategoryTree()
  } catch (e) {
    message.error('创建失败')
  } finally {
    applying.value = false
  }
}

// 监听自动提取弹窗打开，预加载建议
import { watch } from 'vue'
watch(showAutoExtract, (val) => {
  if (val) loadSuggestedTree()
})

// ==================== 初始化 ====================
onMounted(() => {
  refreshAll()
})
</script>

<style scoped>
.ui-testcase-management {
  height: 100%;
}

.main-layout {
  display: flex;
  gap: 12px;
}

.tree-panel {
  width: 260px;
  flex-shrink: 0;
  overflow-y: auto;
}

.table-panel {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.uncategorized-node {
  display: flex;
  align-items: center;
  padding: 6px 10px;
  margin-top: 4px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s;
  font-size: 14px;
}

.uncategorized-node:hover {
  background: var(--n-color-target);
}

.uncategorized-node.active {
  background: var(--n-color-target);
  color: var(--n-color-checked);
}

.pagination-wrapper {
  display: flex;
  justify-content: center;
  padding-top: 12px;
}

.move-option-uncategorized {
  display: flex;
  align-items: center;
  padding: 6px 8px;
  cursor: pointer;
  border-radius: 4px;
  margin-bottom: 4px;
  font-size: 14px;
}

.move-option-uncategorized:hover {
  background: var(--n-color-target);
}

.code-area :deep(textarea) {
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
}
</style>

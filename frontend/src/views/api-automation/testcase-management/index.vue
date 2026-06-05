<template>
  <div class="testcase-management">
    <!-- 工具栏 -->
    <n-card class="mb-4">
      <div class="flex justify-between items-center">
        <div class="flex items-center gap-3">
          <n-input
            v-model:value="searchKeyword"
            placeholder="搜索用例..."
            clearable
            style="width: 260px"
            @keyup.enter="loadTestCases"
          >
            <template #prefix><n-icon><Icon icon="mdi:magnify" /></n-icon></template>
          </n-input>
          <n-select
            v-model:value="filterTestType"
            :options="testTypeOptions"
            placeholder="测试类型"
            clearable
            style="width: 140px"
            @update:value="loadTestCases"
          />
          <n-select
            v-model:value="filterDocument"
            :options="documentOptions"
            placeholder="文档筛选"
            clearable
            style="width: 180px"
            @update:value="loadTestCases"
          />
        </div>
        <n-space>
          <n-button type="primary" @click="showAutoExtract = true">
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
          <n-dropdown trigger="click" :options="classifyActionOptions" @select="onClassifyAction">
            <n-button type="warning">
              <template #icon><n-icon><Icon icon="mdi:magic" /></n-icon></template>
              智能分类 ▾
            </n-button>
          </n-dropdown>
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
              <span>用例分类</span>
              <n-tag :bordered="false" type="info" size="small" round>
                {{ totalTestcaseCount }}
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

      <!-- 右侧：用例列表 -->
      <div class="table-panel">
        <n-card size="small" :content-style="{ padding: '12px', display: 'flex', flexDirection: 'column', minHeight: 0 }">
          <template #header>
            <div class="flex justify-between items-center">
              <span>{{ currentCategoryName }}</span>
              <n-space v-if="selectedIds.length > 0">
                <n-text depth="3">已选 {{ selectedIds.length }} 条</n-text>
                <n-dropdown trigger="click" :options="batchMoveOptions" @select="onBatchMoveSelect">
                  <n-button size="small">移动到...</n-button>
                </n-dropdown>
                <n-button size="small" type="primary" @click="batchExecute" :disabled="batchExecuting" :loading="batchExecuting">批量执行</n-button>
              </n-space>
            </div>
          </template>

          <n-data-table
            :key="tableKey"
            class="flex-1"
            :columns="caseColumns"
            :data="testCases"
            :loading="tableLoading"
            :row-key="(row) => row.test_id"
            :scroll-x="1100"
            :max-height="500"
            v-model:checked-row-keys="selectedIds"
            @update:checked-row-keys="onSelectionChange"
          />

          <div class="pagination-wrapper">
            <n-pagination
              v-model:page="pagination.page"
              v-model:page-size="pagination.pageSize"
              :item-count="pagination.itemCount"
              :page-sizes="[15, 30, 50]"
              show-size-picker
              show-quick-jumper
              @update:page="loadTestCases"
              @update:page-size="loadTestCases"
            />
          </div>
        </n-card>
      </div>
    </div>

    <!-- 树节点右键菜单 -->
    <n-dropdown
      :show="contextMenu.show"
      :x="contextMenu.x"
      :y="contextMenu.y"
      :options="contextMenuOptions"
      placement="bottom-start"
      @clickoutside="contextMenu.show = false"
      @select="onContextMenuSelect"
    />

    <!-- 编辑分类弹窗 -->
    <n-modal v-model:show="editModal.show" title="编辑分类">
      <n-card style="width: 420px">
        <n-form :model="editModal.form" label-placement="left" label-width="80px">
          <n-form-item label="名称">
            <n-input v-model:value="editModal.form.name" />
          </n-form-item>
          <n-form-item v-if="!editModal.isNew" label="父节点">
            <n-tree-select
              v-model:value="editModal.form.parent_id"
              :options="categoryTree"
              key-field="category_id"
              label-field="name"
              children-field="children"
              placeholder="不选则为根节点"
              clearable
            />
          </n-form-item>
          <n-form-item label="匹配规则">
            <n-input
              v-model:value="editModal.form.match_rule"
              placeholder='如 /**/assetbase/knowasset/**'
            />
            <n-text depth="3" style="font-size: 12px">
              接口 path 命中此规则自动归类到此节点。留空则不自动匹配
            </n-text>
          </n-form-item>
        </n-form>
        <n-space justify="end" class="mt-4">
          <n-button @click="editModal.show = false">取消</n-button>
          <n-button type="primary" @click="saveCategory">保存</n-button>
        </n-space>
      </n-card>
    </n-modal>

    <!-- 自动提取弹窗 -->
    <n-modal v-model:show="showAutoExtract" title="自动提取分类结构" style="width: 640px">
      <n-card>
        <div class="mb-3">
          <n-select
            v-model:value="autoExtractDocId"
            :options="documentOptions"
            placeholder="按文档筛选（不选则全量）"
            clearable
            style="width: 240px"
          />
        </div>
        <n-button :loading="autoExtracting" @click="doAutoExtract">开始提取</n-button>

        <div v-if="autoExtractTree.length > 0" class="mt-4">
          <n-divider />
          <div class="flex justify-between items-center mb-2">
            <n-text strong>提取结果预览（可微调后应用）</n-text>
            <n-space>
              <n-button size="small" @click="addAutoNode(null)">+ 根节点</n-button>
              <n-button size="small" type="primary" @click="applyAutoExtract">应用</n-button>
            </n-space>
          </div>
          <n-tree
            :data="autoExtractTree"
            :render-label="renderAutoTreeLabel"
            key-field="key"
            children-field="children"
            block-line
          />
        </div>
      </n-card>
    </n-modal>

    <!-- 智能推荐规则弹窗 -->
    <n-modal v-model:show="showRecommendModal" title="智能推荐分类规则" style="width: 800px">
      <n-card>
        <div class="mb-3">
          <n-select
            v-model:value="recommendDocId"
            :options="documentOptions"
            placeholder="按文档筛选（不选则全量）"
            clearable
            style="width: 240px"
          />
        </div>
        <n-button :loading="recommending" @click="doRecommend">开始推荐</n-button>

        <div v-if="recommendResults.length > 0" class="mt-4">
          <n-divider />
          <div class="flex justify-between items-center mb-2">
            <n-text strong>推荐结果（可修改规则后应用）</n-text>
            <n-button size="small" type="primary" :loading="applying" @click="applyRecommendations">应用全部</n-button>
          </div>
          <n-data-table
            :columns="recommendColumns"
            :data="recommendResults"
            :row-key="(r) => r.category_id"
            size="small"
            :max-height="400"
          />
        </div>
      </n-card>
    </n-modal>

    <!-- 用例详情弹窗 -->
    <n-modal v-model:show="detailModal.show" title="用例详情" style="width: 720px">
      <n-card v-if="detailModal.data">
        <n-descriptions bordered :column="2" size="small">
          <n-descriptions-item label="用例名称">{{ detailModal.data.name }}</n-descriptions-item>
          <n-descriptions-item label="测试类型">{{ detailModal.data.test_type }}</n-descriptions-item>
          <n-descriptions-item label="接口">{{ detailModal.data.interface_info?.method }} {{ detailModal.data.interface_info?.path }}</n-descriptions-item>
          <n-descriptions-item label="脚本">{{ detailModal.data.script_file_name }}</n-descriptions-item>
          <n-descriptions-item label="描述" :span="2">{{ detailModal.data.description || '无' }}</n-descriptions-item>
          <n-descriptions-item label="分类">{{ detailModal.data.category_info?.name || '未分类' }}</n-descriptions-item>
          <n-descriptions-item label="状态">
            <n-tag :type="detailModal.data.last_execution_status === 'PASSED' ? 'success' : detailModal.data.last_execution_status ? 'error' : 'default'" size="small">
              {{ detailModal.data.last_execution_status || '未执行' }}
            </n-tag>
          </n-descriptions-item>
        </n-descriptions>
        <n-space justify="end" class="mt-4">
          <n-button type="primary" @click="runSingle(detailModal.data.test_id)">执行</n-button>
          <n-button @click="detailModal.show = false">关闭</n-button>
        </n-space>
      </n-card>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, h, onMounted } from 'vue'
import { NButton, NTag, NSpace, NDropdown, NTree, NTreeSelect, NTooltip, useMessage, useDialog } from 'naive-ui'
import { Icon } from '@iconify/vue'
import api from '@/api'
import { formatTime } from '@/utils'

const message = useMessage()
const dialog = useDialog()

// ==================== 状态 ====================
const searchKeyword = ref('')
const filterTestType = ref(null)
const filterDocument = ref(null)
const documentOptions = ref([])

const selectedCategoryId = ref(null)
const currentCategoryName = ref('全部用例')
const categoryTree = ref([])
const treeLoading = ref(false)
const treeEditMode = ref(false)
const uncategorizedCount = ref(0)
const totalTestcaseCount = ref(0)

const testCases = ref([])
const tableKey = ref(0)
const tableLoading = ref(false)
const selectedIds = ref([])
const pagination = reactive({ page: 1, pageSize: 20, itemCount: 0 })

// 右键菜单
const contextMenu = reactive({ show: false, x: 0, y: 0, node: null })
const contextMenuOptions = ref([])

// 编辑弹窗
const editModal = reactive({
  show: false,
  form: { name: '', parent_id: null, match_rule: '' },
  node: null,
  isNew: false,
})

// 智能推荐
const showRecommendModal = ref(false)
const recommendDocId = ref(null)
const recommending = ref(false)
const applying = ref(false)
const recommendResults = ref([])

// 一键归类
const classifyingAction = ref(false)

// 自动提取
const showAutoExtract = ref(false)
const autoExtractDocId = ref(null)
const autoExtracting = ref(false)
const autoExtractTree = ref([])

// 详情弹窗
const detailModal = reactive({ show: false, data: null })

// 移动下拉选项（动态生成）
const batchMoveOptions = computed(() => {
  const options = [{ label: '未分类', key: '__uncategorized__' }]
  function walk(nodes, prefix) {
    for (const n of nodes) {
      options.push({ label: prefix + n.name, key: n.category_id })
      if (n.children?.length) walk(n.children, prefix + '  ')
    }
  }
  walk(categoryTree.value, '')
  return options
})

const testTypeOptions = [
  { label: '功能测试', value: 'functional' },
  { label: '安全测试', value: 'security' },
  { label: '性能测试', value: 'performance' },
  { label: '边界测试', value: 'boundary' },
  { label: '负向测试', value: 'negative' },
]

// ==================== 数据加载 ====================

const loadDocumentOptions = async () => {
  try {
    const res = await api.getApiDocuments({ page: 1, page_size: 100 })
    documentOptions.value = (res.data || []).map(d => ({ label: d.file_name, value: d.doc_id }))
  } catch { /* ignore */ }
}

const loadCategoryTree = async () => {
  treeLoading.value = true
  try {
    const res = await api.getCategoryTree()
    categoryTree.value = res.data?.tree || []
    uncategorizedCount.value = res.data?.uncategorized_count || 0
    totalTestcaseCount.value = res.data?.total_count || 0
  } catch {
    message.error('加载分类树失败')
  } finally {
    treeLoading.value = false
  }
}

const loadTestCases = async () => {
  tableLoading.value = true
  try {
    const params = {
      page: pagination.page,
      page_size: pagination.pageSize,
      search: searchKeyword.value || undefined,
      test_type: filterTestType.value || undefined,
      document_id: filterDocument.value || undefined,
    }
    if (selectedCategoryId.value === '__uncategorized__') {
      params.uncategorized = true
    } else if (selectedCategoryId.value) {
      params.category_id = selectedCategoryId.value
    }
    const res = await api.getAllTestCases(params)
    const data = res.data || {}
    const rawItems = data.items || []
    const items = rawItems.map(item => ({ ...item, _catName: item.category_info?.name || '' }))
    console.log('[LOAD] items count:', items.length, 'first _catName:', items[0]?._catName, 'first category_info:', JSON.stringify(items[0]?.category_info))
    testCases.value = items
    tableKey.value++
    pagination.itemCount = data.total || 0
  } catch {
    message.error('加载用例列表失败')
  } finally {
    tableLoading.value = false
  }
}

const refreshAll = () => {
  loadCategoryTree()
  loadTestCases()
}

// ==================== 树交互 ====================

const onTreeSelect = (keys) => {
  selectedCategoryId.value = keys[0] || null
  currentCategoryName.value = '全部用例'
  pagination.page = 1
  // 从树中找节点名
  function find(nodes, id) {
    for (const n of nodes) {
      if (n.category_id === id) return n
      if (n.children?.length) {
        const f = find(n.children, id)
        if (f) return f
      }
    }
    return null
  }
  const node = find(categoryTree.value, selectedCategoryId.value)
  if (node) currentCategoryName.value = `${node.name} (${node.testcase_count})`
  loadTestCases()
}

const selectUncategorized = () => {
  selectedCategoryId.value = '__uncategorized__'
  currentCategoryName.value = `未分类 (${uncategorizedCount.value})`
  pagination.page = 1
  loadTestCases()
}

// 树节点渲染
const renderTreePrefix = ({ option }) => {
  const icons = { 0: 'mdi:folder', 1: 'mdi:folder-outline', 2: 'mdi:file-document-outline' }
  return h(Icon, { icon: icons[option.level] || 'mdi:file-outline', style: 'margin-right: 4px;' })
}
const renderTreeLabel = ({ option }) => {
  if (treeEditMode.value) {
    return h('div', { class: 'tree-label-editing' }, [
      h('span', option.name),
      h(NTag, { size: 'tiny', class: 'ml-1' }, { default: () => String(option.testcase_count) }),
      h(NSpace, { size: 2, class: 'ml-2' }, [
        h(NButton, {
          size: 'tiny', text: true,
          onClick: (e) => { e.stopPropagation(); openEditModal(option) },
        }, { icon: () => h(Icon, { icon: 'mdi:pencil' }) }),
        h(NButton, {
          size: 'tiny', text: true,
          onClick: (e) => { e.stopPropagation(); openAddChildModal(option) },
        }, { icon: () => h(Icon, { icon: 'mdi:plus-circle-outline' }) }),
        h(NButton, {
          size: 'tiny', text: true, type: 'error',
          onClick: (e) => { e.stopPropagation(); confirmDeleteNode(option) },
        }, { icon: () => h(Icon, { icon: 'mdi:delete-outline' }) }),
      ]),
    ])
  }
  return h('div', { class: 'tree-label' }, [
    h('span', option.name),
    h(NTag, { size: 'tiny', class: 'ml-2' }, { default: () => String(option.testcase_count) }),
  ])
}

const openEditModal = (node) => {
  editModal.isNew = false
  editModal.node = node
  editModal.form = { name: node.name, parent_id: node.parent_category_id || null, match_rule: node.match_rule || '' }
  editModal.show = true
}

const openAddChildModal = (node) => {
  editModal.isNew = true
  editModal.form = { name: '', parent_id: node.category_id, match_rule: '' }
  editModal.show = true
}

const confirmDeleteNode = (node) => {
  dialog.warning({
    title: '确认删除',
    content: `确定删除分类"${node.name}"吗？子节点将上移，用例变未分类。`,
    positiveText: '删除',
    onPositiveClick: async () => {
      await api.deleteCategory(node.category_id)
      message.success('已删除')
      loadCategoryTree()
    },
  })
}

const addRootCategory = () => {
  editModal.isNew = true
  editModal.form = { name: '', parent_id: null, match_rule: '' }
  editModal.node = null
  editModal.show = true
}

// 右键菜单
const onTreeRightClick = ({ event, node }) => {
  if (!treeEditMode.value) return
  event.preventDefault()
  contextMenu.x = event.clientX
  contextMenu.y = event.clientY
  contextMenu.show = true
  contextMenu.node = node
  contextMenuOptions.value = [
    { label: '新增子节点', key: 'add_child' },
    { label: '重命名', key: 'rename' },
    { label: '上移', key: 'move_up' },
    { label: '下移', key: 'move_down' },
    { label: '删除', key: 'delete' },
  ]
}

const treeNodeProps = ({ option }) => {
  return {
    oncontextmenu: (e) => {
      onTreeRightClick({ event: e, node: option })
    },
  }
}

const onContextMenuSelect = async (key) => {
  contextMenu.show = false
  const node = contextMenu.node
  if (!node) return

  switch (key) {
    case 'add_child':
      editModal.isNew = true
      editModal.form = { name: '', parent_id: node.category_id }
      editModal.show = true
      break
    case 'rename':
      editModal.isNew = false
      editModal.node = node
      editModal.form = { name: node.name, parent_id: node.parent_category_id || null, match_rule: node.match_rule || '' }
      editModal.show = true
      break
    case 'move_up':
      await api.updateCategory(node.category_id, { sort_order: Math.max(0, (node.sort_order || 1) - 1) })
      message.success('已上移')
      loadCategoryTree()
      break
    case 'move_down':
      await api.updateCategory(node.category_id, { sort_order: (node.sort_order || 0) + 1 })
      message.success('已下移')
      loadCategoryTree()
      break
    case 'delete':
      dialog.warning({
        title: '确认删除',
        content: `确定删除分类"${node.name}"吗？子节点将上移，用例变未分类。`,
        positiveText: '删除',
        onPositiveClick: async () => {
          await api.deleteCategory(node.category_id)
          message.success('已删除')
          loadCategoryTree()
        },
      })
      break
  }
}

const saveCategory = async () => {
  try {
    if (editModal.isNew) {
      await api.createCategory({ name: editModal.form.name, parent_id: editModal.form.parent_id || undefined, description: '' })
      message.success('创建成功')
    } else if (editModal.node) {
      const updateData = {
        name: editModal.form.name,
        match_rule: editModal.form.match_rule || '',
      }
      if (editModal.form.parent_id) updateData.parent_id = editModal.form.parent_id
      await api.updateCategory(editModal.node.category_id, updateData)
      message.success('更新成功')
    }
    editModal.show = false
    loadCategoryTree()
  } catch (e) {
    message.error('操作失败')
  }
}

// ==================== 自动提取 ====================

const doAutoExtract = async () => {
  autoExtracting.value = true
  try {
    const params = {}
    if (autoExtractDocId.value) params.doc_id = autoExtractDocId.value
    const res = await api.autoExtractCategories(params)
    autoExtractTree.value = res.data?.suggested_tree || []
    if (autoExtractTree.value.length === 0) {
      message.info('未提取到分类结构')
    } else {
      message.success(`提取到 ${autoExtractTree.value.length} 个分类`)
    }
  } catch {
    message.error('自动提取失败')
  } finally {
    autoExtracting.value = false
  }
}

const addAutoNode = (parentId) => {
  const name = prompt('节点名称:')
  if (!name) return
  const newNode = {
    key: `manual_${Date.now()}`,
    name,
    level: 0,
    children: [],
  }
  if (parentId) {
    function insert(nodes, id) {
      for (const n of nodes) {
        if (n.key === id) {
          n.children = n.children || []
          n.children.push(newNode)
          return true
        }
        if (n.children?.length && insert(n.children, id)) return true
      }
      return false
    }
    if (!insert(autoExtractTree.value, parentId)) {
      autoExtractTree.value.push(newNode)
    }
  } else {
    autoExtractTree.value.push(newNode)
  }
}

const applyAutoExtract = async () => {
  try {
    // 递归创建节点
    async function createNodes(nodes, parentId) {
      for (const n of nodes) {
        const res = await api.createCategory({ name: n.name, parent_id: parentId, description: '' })
        const catId = res.data?.category_id
        if (n.children?.length && catId) {
          await createNodes(n.children, catId)
        }
      }
    }
    await createNodes(autoExtractTree.value, undefined)
    message.success('分类结构已应用')
    showAutoExtract.value = false
    autoExtractTree.value = []
    loadCategoryTree()
  } catch {
    message.error('应用失败')
  }
}

// ==================== 智能推荐 + 一键归类 ====================

const classifyActionOptions = [
  { label: '智能推荐规则', key: 'recommend' },
  { label: '一键归类', key: 'classify' },
]

const onClassifyAction = (key) => {
  if (key === 'recommend') showRecommendModal.value = true
  else if (key === 'classify') doAutoClassify()
}

const doRecommend = async () => {
  recommending.value = true
  try {
    const params = {}
    if (recommendDocId.value) params.doc_id = recommendDocId.value
    const res = await api.recommendCategoryRules(params)
    recommendResults.value = res.data?.recommendations || []
    if (recommendResults.value.length === 0) {
      message.info('未生成推荐规则')
    } else {
      message.success(`已生成 ${recommendResults.value.length} 条推荐规则`)
    }
  } catch {
    message.error('推荐失败')
  } finally {
    recommending.value = false
  }
}

const applyRecommendations = async () => {
  applying.value = true
  try {
    await api.applyCategoryRecommendations({ rules: recommendResults.value })
    message.success('规则已应用')
    showRecommendModal.value = false
    recommendResults.value = []
    loadCategoryTree()
  } catch {
    message.error('应用失败')
  } finally {
    applying.value = false
  }
}

const doAutoClassify = async () => {
  classifyingAction.value = true
  try {
    const res = await api.autoClassifyTestCases()
    const data = res.data || {}
    message.success(`已归类 ${data.classified_count} 条，${data.unmatched_count || 0} 条未匹配`)
    loadCategoryTree()
    loadTestCases()
  } catch {
    message.error('归类失败')
  } finally {
    classifyingAction.value = false
  }
}

const recommendColumns = [
  { title: '分类路径', key: 'category_path', width: 180 },
  {
    title: '推荐规则', key: 'match_rule', width: 260,
    render(row) {
      return h('div', { class: 'flex items-center gap-1' }, [
        h('code', { style: 'font-size:12px' }, row.match_rule || '(空)'),
        h(NButton, { size: 'tiny', text: true, onClick: () => {
          const val = prompt('修改规则:', row.match_rule)
          if (val !== null) row.match_rule = val
        } }, { icon: () => h(Icon, { icon: 'mdi:pencil' }) }),
      ])
    },
  },
  { title: '匹配数', key: 'matched_count', width: 70 },
  {
    title: '示例路径', key: 'sample_paths', ellipsis: { tooltip: true },
    render(row) {
      return (row.sample_paths || []).slice(0, 2).join(', ')
    },
  },
]

const renderAutoTreeLabel = ({ option }) => {
  return h('div', { class: 'flex items-center gap-2' }, [
    h('span', option.name),
    h(NTag, { size: 'tiny', type: 'info' }, { default: () => `${option.api_count || 0} 接口` }),
  ])
}

// ==================== 表格 ====================

const getMethodType = (method) => {
  const map = { GET: 'success', POST: 'info', PUT: 'warning', DELETE: 'error', PATCH: 'warning' }
  return map[(method || '').toUpperCase()] || 'default'
}

const caseColumns = [
  { type: 'selection', width: 36 },
  {
    title: '用例名称', key: 'name', width: 280, ellipsis: { tooltip: true },
  },
  {
    title: '类型', key: 'test_type', width: 90,
    render(row) {
      const typeMap = { functional: '功能', security: '安全', performance: '性能', boundary: '边界', negative: '负向' }
      return typeMap[row.test_type] || row.test_type
    },
  },
  {
    title: '接口', key: 'interface', width: 220, ellipsis: { tooltip: true },
    render(row) {
      const info = row.interface_info
      if (!info || !info.method) return h('span', { style: 'color: #999;' }, '无')
      const fullPath = info.path || ''
      const tooltipContent = h('div', { style: 'max-width: 500px; word-break: break-all; font-size: 12px;' }, [
        h('div', { style: 'font-weight: bold; margin-bottom: 4px;' }, info.name || ''),
        h('div', [
          h('span', { style: 'color: #aaa; margin-right: 6px;' }, '方法:'),
          h('span', info.method),
        ]),
        h('div', [
          h('span', { style: 'color: #aaa; margin-right: 6px;' }, '路径:'),
          h('span', fullPath),
        ]),
      ])
      return h(
        NTooltip,
        { placement: 'top', trigger: 'hover' },
        {
          trigger: () => h('div', { style: 'display: flex; align-items: center; gap: 6px; cursor: default;' }, [
            h(NTag, { size: 'tiny', type: getMethodType(info.method) }, { default: () => info.method }),
            h('span', { style: 'font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 160px;' }, fullPath),
          ]),
          default: () => tooltipContent,
        }
      )
    },
  },
  {
    title: '分类', key: '_catName', width: 100,
    render(row) {
      const name = row._catName || row.category_info?.name || ''
      return name || h('span', { style: 'color: #999;' }, '未分类')
    },
  },
  {
    title: '状态', key: 'status', width: 80,
    render(row) {
      const s = row.last_execution_status
      if (!s) return h(NTag, { size: 'small', type: 'default' }, { default: () => '未执行' })
      const type = s === 'PASSED' ? 'success' : 'error'
      return h(NTag, { size: 'small', type }, { default: () => s })
    },
  },
  {
    title: '操作', key: 'actions', width: 140, fixed: 'right',
    render(row) {
      return h(NSpace, { size: 'small' }, {
        default: () => [
          h(NButton, { size: 'tiny', onClick: () => showDetail(row) }, { default: () => '详情' }),
          h(NButton, { size: 'tiny', type: 'primary', onClick: () => runSingle(row.test_id) },
            { default: () => '执行' }),
        ]
      })
    },
  },
]

const onSelectionChange = (keys) => {
  selectedIds.value = keys
}

const onBatchMoveSelect = async (key) => {
  const target = key === '__uncategorized__' ? null : key
  try {
    await api.batchMoveTestCases({ test_ids: selectedIds.value, category_id: target || null })
    message.success(`已移动 ${selectedIds.value.length} 条用例`)
    selectedIds.value = []
    loadTestCases()
    loadCategoryTree()
  } catch {
    message.error('移动失败')
  }
}

const showDetail = async (row) => {
  try {
    const res = await api.getTestCaseDetail(row.test_id)
    detailModal.data = res.data
    detailModal.show = true
  } catch { message.error('获取详情失败') }
}

const runSingle = async (testId) => {
  try {
    await api.runTestCase(testId)
    message.success('已触发执行')
    loadTestCases()
  } catch { message.error('执行失败') }
}

const batchExecuting = ref(false)

const batchExecute = async () => {
  batchExecuting.value = true
  try {
    await api.executeTestCases({ test_ids: selectedIds.value })
    message.success(`已触发批量执行 ${selectedIds.value.length} 条用例`)
    selectedIds.value = []
  } catch { message.error('批量执行失败') } finally { batchExecuting.value = false }
}

// ==================== 初始化 ====================

onMounted(() => {
  loadDocumentOptions()
  loadCategoryTree()
  loadTestCases()
})
</script>

<style scoped>
.testcase-management { height: calc(100vh - 140px); display: flex; flex-direction: column; }

.main-layout { display: flex; gap: 12px; flex: 1; min-height: 0; }

.tree-panel { width: 280px; flex-shrink: 0; overflow-y: auto; }

.table-panel { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.table-panel :deep(.n-card__content) { flex: 1; display: flex; flex-direction: column; min-height: 0; padding: 12px !important; }

.tree-label { display: flex; align-items: center; }
.tree-label-editing { display: flex; align-items: center; flex: 1; }
.uncategorized-node {
  display: flex; align-items: center; padding: 6px 8px; border-radius: 4px;
  cursor: pointer; margin-top: 8px; border-top: 1px solid var(--n-border-color);
}
.uncategorized-node:hover { background: var(--n-color-hover); }
.uncategorized-node.active { background: var(--n-color-selected); font-weight: 600; }

.pagination-wrapper { display: flex; justify-content: flex-end; margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--n-border-color); }

.flex-1 { flex: 1; min-height: 0; }
</style>

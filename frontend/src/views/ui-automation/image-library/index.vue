<template>
  <AppPage>
    <n-space vertical size="large">
      <!-- ============ 顶部:筛选 + 上传 ============ -->
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
            <n-input
              v-model:value="filter.page_type"
              placeholder="页面类型筛选"
              clearable
              style="width: 160px"
              @keyup.enter="loadList"
            />
            <n-input
              v-model:value="filter.tag"
              placeholder="标签筛选"
              clearable
              style="width: 160px"
              @keyup.enter="loadList"
            />
            <n-button @click="loadList">
              <template #icon><n-icon><Icon icon="mdi:refresh" /></n-icon></template>
              刷新
            </n-button>
          </n-space>
          <n-space>
            <n-button type="primary" @click="openUploadModal">
              <template #icon><n-icon><Icon icon="mdi:upload" /></n-icon></template>
              上传图片
            </n-button>
          </n-space>
        </n-space>
      </n-card>

      <!-- ============ 网格缩略图 ============ -->
      <n-card title="图片库" size="small">
        <template #header-extra>
          <n-text depth="3" style="font-size: 12px">
            共 {{ pagination.itemCount }} 张 · SHA256 自动查重
          </n-text>
        </template>
        <n-spin :show="loading">
          <n-empty v-if="!loading && list.length === 0" description="图片库为空,先上传几张试试" />
          <div v-else class="image-grid">
            <div
              v-for="item in list"
              :key="item.image_id"
              class="image-card"
              @click="openDetail(item)"
            >
              <div class="thumb-wrap">
                <img
                  :src="thumbUrl(item)"
                  :alt="item.title || item.original_name"
                  loading="lazy"
                  @error="onThumbError($event, item)"
                />
                <div v-if="item.reference_count > 0" class="ref-badge">
                  <n-icon size="12"><Icon icon="mdi:link-variant" /></n-icon>
                  {{ item.reference_count }}
                </div>
              </div>
              <div class="meta">
                <div class="title" :title="item.title || item.original_name">
                  {{ item.title || item.original_name || item.image_id }}
                </div>
                <div class="sub">
                  <span>{{ item.width }}×{{ item.height }}</span>
                  <span class="dot">·</span>
                  <span>{{ formatSize(item.file_size) }}</span>
                </div>
                <div v-if="item.tags?.length" class="tags">
                  <n-tag v-for="t in item.tags.slice(0, 3)" :key="t" size="small">{{ t }}</n-tag>
                  <n-text v-if="item.tags.length > 3" depth="3" style="font-size: 11px">
                    +{{ item.tags.length - 3 }}
                  </n-text>
                </div>
              </div>
              <div class="actions" @click.stop>
                <n-button size="tiny" @click="openEditModal(item)">
                  <template #icon><n-icon><Icon icon="mdi:pencil" /></n-icon></template>
                </n-button>
                <n-button size="tiny" @click="copyId(item)">
                  <template #icon><n-icon><Icon icon="mdi:content-copy" /></n-icon></template>
                </n-button>
                <n-button size="tiny" type="error" @click="confirmDelete(item)">
                  <template #icon><n-icon><Icon icon="mdi:delete-outline" /></n-icon></template>
                </n-button>
              </div>
            </div>
          </div>
        </n-spin>
        <n-pagination
          v-if="pagination.itemCount > pagination.pageSize"
          v-model:page="pagination.page"
          :item-count="pagination.itemCount"
          :page-size="pagination.pageSize"
          style="justify-content: flex-end; margin-top: 16px"
          @update:page="onPageChange"
        />
      </n-card>
    </n-space>

    <!-- ============ 上传 modal ============ -->
    <n-modal
      v-model:show="uploadVisible"
      title="上传图片到图片库"
      preset="card"
      style="width: 560px"
      :mask-closable="false"
    >
      <n-form ref="uploadFormRef" :model="uploadForm" label-placement="top">
        <n-form-item label="选择图片" required>
          <n-upload
            ref="uploadRef"
            :max="1"
            :default-upload="false"
            accept="image/png,image/jpeg,image/webp,image/bmp"
            @change="onUploadChange"
          >
            <n-upload-dragger>
              <div style="margin-bottom: 8px">
                <n-icon size="36" depth="3"><Icon icon="mdi:cloud-upload-outline" /></n-icon>
              </div>
              <n-text style="font-size: 14px">点击或拖拽图片到此处</n-text>
              <n-p depth="3" style="margin: 6px 0 0; font-size: 12px">
                支持 PNG / JPG / WEBP / BMP,自动 SHA256 查重
              </n-p>
            </n-upload-dragger>
          </n-upload>
        </n-form-item>
        <n-form-item label="标题(可选)">
          <n-input v-model:value="uploadForm.title" placeholder="如:登录页" maxlength="80" />
        </n-form-item>
        <n-form-item label="描述(可选)">
          <n-input
            v-model:value="uploadForm.description"
            type="textarea"
            placeholder="可选"
            :autosize="{ minRows: 2, maxRows: 4 }"
            maxlength="200"
          />
        </n-form-item>
        <n-form-item label="页面类型(可选)">
          <n-input v-model:value="uploadForm.page_type" placeholder="如:login / list / detail" maxlength="40" />
        </n-form-item>
        <n-form-item label="标签(逗号分隔)">
          <n-input v-model:value="uploadForm.tags" placeholder="如:critical,smoke" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space justify="end">
          <n-button @click="uploadVisible = false">取消</n-button>
          <n-button
            type="primary"
            :loading="uploading"
            :disabled="!uploadFile"
            @click="submitUpload"
          >
            上传
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- ============ 编辑元数据 modal ============ -->
    <n-modal
      v-model:show="editVisible"
      title="编辑图片元数据"
      preset="card"
      style="width: 520px"
      :mask-closable="false"
    >
      <n-form :model="editForm" label-placement="top">
        <n-form-item label="标题">
          <n-input v-model:value="editForm.title" maxlength="80" />
        </n-form-item>
        <n-form-item label="描述">
          <n-input
            v-model:value="editForm.description"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 4 }"
            maxlength="200"
          />
        </n-form-item>
        <n-form-item label="页面类型">
          <n-input v-model:value="editForm.page_type" maxlength="40" />
        </n-form-item>
        <n-form-item label="标签(逗号分隔)">
          <n-input v-model:value="editForm.tagsStr" />
        </n-form-item>
      </n-form>
      <template #action>
        <n-space justify="end">
          <n-button @click="editVisible = false">取消</n-button>
          <n-button type="primary" :loading="editSubmitting" @click="submitEdit">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- ============ 详情抽屉 ============ -->
    <n-drawer v-model:show="detailVisible" :width="720" placement="right">
      <n-drawer-content :title="detail?.title || detail?.original_name || '图片详情'" closable>
        <n-space v-if="detail" vertical size="large">
          <div class="detail-image-wrap">
            <img :src="originalUrl(detail)" :alt="detail.title" @error="onThumbError($event, detail)" />
          </div>
          <n-descriptions :column="1" bordered label-placement="left" size="small">
            <n-descriptions-item label="image_id">{{ detail.image_id }}</n-descriptions-item>
            <n-descriptions-item label="原文件名">{{ detail.original_name || '-' }}</n-descriptions-item>
            <n-descriptions-item label="尺寸">{{ detail.width }} × {{ detail.height }}</n-descriptions-item>
            <n-descriptions-item label="大小">{{ formatSize(detail.file_size) }}</n-descriptions-item>
            <n-descriptions-item label="MIME">{{ detail.mime_type }}</n-descriptions-item>
            <n-descriptions-item label="页面类型">{{ detail.page_type || '-' }}</n-descriptions-item>
            <n-descriptions-item label="标签">
              <n-space v-if="detail.tags?.length">
                <n-tag v-for="t in detail.tags" :key="t" size="small">{{ t }}</n-tag>
              </n-space>
              <span v-else>-</span>
            </n-descriptions-item>
            <n-descriptions-item label="描述">{{ detail.description || '-' }}</n-descriptions-item>
            <n-descriptions-item label="引用次数">
              <n-tag size="small" :type="detail.reference_count > 0 ? 'info' : 'default'">
                {{ detail.reference_count }}
              </n-tag>
            </n-descriptions-item>
            <n-descriptions-item label="最近引用">{{ detail.last_used_at || '从未' }}</n-descriptions-item>
            <n-descriptions-item label="SHA256">
              <n-text style="font-family: monospace; font-size: 11px">{{ detail.sha256 }}</n-text>
            </n-descriptions-item>
            <n-descriptions-item label="上传人">{{ detail.uploaded_by || '-' }}</n-descriptions-item>
            <n-descriptions-item label="上传时间">{{ detail.created_at || '-' }}</n-descriptions-item>
          </n-descriptions>
        </n-space>
      </n-drawer-content>
    </n-drawer>
  </AppPage>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { Icon } from '@iconify/vue'
import api from '@/api'

// ---------- 状态 ----------
const list = ref([])
const loading = ref(false)
const filter = ref({ keyword: '', page_type: '', tag: '' })
const pagination = ref({
  page: 1,
  pageSize: 24,
  itemCount: 0,
})

// ---------- 工具 ----------
function thumbUrl(item) {
  // 静态资源 mount 在 /static/ui-images,缩略图统一在 thumbnails/<image_id>.jpg
  return `/static/ui-images/thumbnails/${item.image_id}.jpg`
}

function originalUrl(item) {
  // 原图按 sha256 前 2 位分桶。后端返回的是磁盘绝对路径,这里靠 sha256 拼相对 URL。
  // 如果 sha256 缺失就回退到缩略图。
  if (!item?.sha256) return thumbUrl(item)
  const sub = item.sha256.slice(0, 2)
  const ext = (item.file_path || '').split('.').pop()?.toLowerCase() || 'png'
  return `/static/ui-images/originals/${sub}/${item.image_id}.${ext}`
}

function onThumbError(e, item) {
  // 缩略图丢失时显示占位
  e.target.style.opacity = '0.3'
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// ---------- 列表 ----------
async function loadList() {
  loading.value = true
  try {
    const res = await api.uiListLibraryImages({
      page: pagination.value.page,
      page_size: pagination.value.pageSize,
      keyword: filter.value.keyword || undefined,
      page_type: filter.value.page_type || undefined,
      tag: filter.value.tag || undefined,
    })
    const data = res?.data ?? res
    list.value = data.items || []
    pagination.value.itemCount = data.total || 0
  } catch (e) {
    window.$message?.error('加载失败:' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function onPageChange(page) {
  pagination.value.page = page
  loadList()
}

// ---------- 上传 ----------
const uploadVisible = ref(false)
const uploading = ref(false)
const uploadFile = ref(null)
const uploadForm = ref({
  title: '',
  description: '',
  page_type: '',
  tags: '',
})

function openUploadModal() {
  uploadFile.value = null
  uploadForm.value = { title: '', description: '', page_type: '', tags: '' }
  uploadVisible.value = true
}

function onUploadChange({ fileList }) {
  uploadFile.value = fileList?.[0]?.file || null
}

async function submitUpload() {
  if (!uploadFile.value) {
    window.$message?.warning('请先选择图片')
    return
  }
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', uploadFile.value)
    if (uploadForm.value.title) fd.append('title', uploadForm.value.title)
    if (uploadForm.value.description) fd.append('description', uploadForm.value.description)
    if (uploadForm.value.page_type) fd.append('page_type', uploadForm.value.page_type)
    if (uploadForm.value.tags) fd.append('tags', uploadForm.value.tags)

    const res = await api.uiUploadLibraryImage(fd)
    const data = res?.data ?? res
    if (data?.is_duplicate) {
      window.$message?.info(`命中 SHA256,已存在: ${data.image_id}`)
    } else {
      window.$message?.success('上传成功')
    }
    uploadVisible.value = false
    loadList()
  } catch (e) {
    window.$message?.error('上传失败:' + (e?.message || e))
  } finally {
    uploading.value = false
  }
}

// ---------- 编辑 ----------
const editVisible = ref(false)
const editSubmitting = ref(false)
const editForm = ref({
  image_id: '',
  title: '',
  description: '',
  page_type: '',
  tagsStr: '',
})

function openEditModal(item) {
  editForm.value = {
    image_id: item.image_id,
    title: item.title || '',
    description: item.description || '',
    page_type: item.page_type || '',
    tagsStr: (item.tags || []).join(','),
  }
  editVisible.value = true
}

async function submitEdit() {
  editSubmitting.value = true
  try {
    const tags = editForm.value.tagsStr
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    await api.uiUpdateLibraryImage(editForm.value.image_id, {
      title: editForm.value.title,
      description: editForm.value.description,
      page_type: editForm.value.page_type,
      tags,
    })
    window.$message?.success('已保存')
    editVisible.value = false
    loadList()
  } catch (e) {
    window.$message?.error('保存失败:' + (e?.message || e))
  } finally {
    editSubmitting.value = false
  }
}

// ---------- 详情 ----------
const detailVisible = ref(false)
const detail = ref(null)

async function openDetail(item) {
  detailVisible.value = true
  detail.value = item
  // 拉一次最新详情(reference_count 可能已变化)
  try {
    const res = await api.uiGetLibraryImage(item.image_id)
    detail.value = res?.data ?? res
  } catch {
    // 兜底用列表数据
  }
}

// ---------- 删除 ----------
function confirmDelete(item) {
  const referenced = (item.reference_count || 0) > 0
  window.$dialog?.warning({
    title: '确认删除',
    content: referenced
      ? `图片被 ${item.reference_count} 个分析任务引用,强删后这些任务的截图路径会失效。确定继续?`
      : `删除 ${item.title || item.original_name || item.image_id}?磁盘文件会一并清理。`,
    positiveText: referenced ? '强制删除' : '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.uiDeleteLibraryImage(item.image_id, referenced)
        window.$message?.success('已删除')
        loadList()
      } catch (e) {
        window.$message?.error('删除失败:' + (e?.message || e))
      }
    },
  })
}

// ---------- 复制 image_id ----------
function copyId(item) {
  navigator.clipboard?.writeText(item.image_id).then(
    () => window.$message?.success(`已复制 ${item.image_id}`),
    () => window.$message?.warning('复制失败'),
  )
}

onMounted(loadList)
</script>

<style scoped>
.image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}
.image-card {
  position: relative;
  border: 1px solid var(--n-border-color, rgba(0, 0, 0, 0.08));
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  transition: box-shadow 0.18s, transform 0.18s;
  background: var(--n-card-color, #fff);
}
.image-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  transform: translateY(-2px);
}
.thumb-wrap {
  position: relative;
  width: 100%;
  height: 140px;
  background: #f5f5f5;
  overflow: hidden;
}
.thumb-wrap img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.ref-badge {
  position: absolute;
  top: 6px;
  right: 6px;
  background: rgba(24, 160, 88, 0.92);
  color: #fff;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.meta {
  padding: 8px 10px;
}
.title {
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sub {
  margin-top: 4px;
  font-size: 11px;
  color: rgba(0, 0, 0, 0.45);
}
.sub .dot {
  margin: 0 6px;
}
.tags {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}
.actions {
  position: absolute;
  top: 6px;
  left: 6px;
  display: none;
  gap: 4px;
}
.image-card:hover .actions {
  display: flex;
}
.detail-image-wrap {
  width: 100%;
  max-height: 420px;
  background: #f5f5f5;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.detail-image-wrap img {
  max-width: 100%;
  max-height: 420px;
  object-fit: contain;
}
</style>

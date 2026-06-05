<template>
  <AppPage :show-footer="false">
    <div flex-1>
      <n-card rounded-10>
        <div flex items-center justify-between>
          <div flex items-center>
            <img rounded-full width="60" :src="userStore.avatar" />
            <div ml-10>
              <p text-20 font-semibold>
                {{ $t('views.workbench.text_hello', { username: userStore.name }) }}
              </p>
              <p mt-5 text-14 op-60>{{ $t('views.workbench.text_welcome') }}</p>
            </div>
          </div>
        </div>
      </n-card>

      <n-card mt-15 rounded-10>
        <template #header>
          <div flex items-center justify-between>
            <span text-16 font-semibold>使用说明</span>
            <n-button size="small" @click="showUpload = true">上传文档</n-button>
          </div>
        </template>

        <n-spin :show="loading">
          <div v-if="docs.length === 0" text-center py-30 op-60>
            暂无文档，请上传 Markdown 文件
          </div>
          <div v-else class="doc-layout">
            <!-- 文档列表 -->
            <div class="doc-list">
              <div
                v-for="doc in docs"
                :key="doc.filename"
                class="doc-item"
                :class="{ active: selectedDoc?.filename === doc.filename }"
                @click="selectDoc(doc)"
              >
                <span class="doc-title">{{ doc.title }}</span>
                <div class="doc-actions">
                  <n-button size="tiny" text @click.stop="handlePin(doc)">
                    {{ doc.pinned ? '取消置顶' : '置顶' }}
                  </n-button>
                  <n-button size="tiny" text @click.stop="handleDownload(doc)">
                    下载
                  </n-button>
                  <n-popconfirm @positive-click="handleDelete(doc.filename)">
                    <template #trigger>
                      <n-button size="tiny" type="error" text @click.stop>
                        删除
                      </n-button>
                    </template>
                    确定删除「{{ doc.title }}」？
                  </n-popconfirm>
                </div>
              </div>
            </div>
            <!-- 文档详情 -->
            <div class="doc-detail">
              <div v-if="selectedDoc" class="doc-content" v-html="renderMarkdown(selectedDoc.content)" />
              <div v-else text-center py-30 op-40>
                请从左侧选择一个文档查看详情
              </div>
            </div>
          </div>
        </n-spin>
      </n-card>

      <!-- 上传对话框 -->
      <n-modal
        v-model:show="showUpload"
        preset="dialog"
        title="上传文档"
        positive-text="上传"
        negative-text="取消"
        :positive-button-props="{ loading: uploading }"
        @positive-click="handleUpload"
      >
        <n-upload
          :default-upload="false"
          accept=".md"
          :max="1"
          @change="onFileChange"
        >
          <n-button>选择 Markdown 文件</n-button>
        </n-upload>
        <p v-if="selectedFile" mt-10 text-14 op-60>
          已选择：{{ selectedFile.name }}
        </p>
      </n-modal>
    </div>
  </AppPage>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { marked } from 'marked'
import { useUserStore } from '@/store'
import api from '@/api'
import { useMessage } from 'naive-ui'

const userStore = useUserStore()
const message = useMessage()

const docs = ref([])
const loading = ref(false)
const selectedDoc = ref(null)
const showUpload = ref(false)
const uploading = ref(false)
const selectedFile = ref(null)

const renderMarkdown = (content) => {
  if (!content) return ''
  return marked.parse(content)
}

const loadDocs = async () => {
  loading.value = true
  try {
    const res = await api.getDocs()
    if (res.success && res.data) {
      const list = res.data
      const detailResults = await Promise.allSettled(
        list.map((d) => api.getDocDetail(d.filename))
      )
      docs.value = detailResults
        .map((r, i) => {
          if (r.status === 'fulfilled' && r.value.success) {
            return {
              filename: r.value.data.filename,
              title: r.value.data.title,
              content: r.value.data.content,
              pinned: list[i]?.pinned || false,
            }
          }
          return null
        })
        .filter(Boolean)
      if (docs.value.length > 0 && !selectedDoc.value) {
        selectedDoc.value = docs.value[0]
      }
    }
  } catch {
    // 加载失败静默处理
  } finally {
    loading.value = false
  }
}

const selectDoc = (doc) => {
  selectedDoc.value = doc
}

const onFileChange = ({ fileList }) => {
  if (fileList.length > 0) {
    selectedFile.value = fileList[0].file
  }
}

const handleUpload = async () => {
  if (!selectedFile.value) {
    message.warning('请先选择文件')
    return false
  }
  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    const res = await api.uploadDoc(formData)
    if (res.success) {
      message.success('上传成功')
      selectedFile.value = null
      await loadDocs()
    } else {
      message.error(res.msg || '上传失败')
      return false
    }
  } catch {
    message.error('上传失败')
    return false
  } finally {
    uploading.value = false
  }
}

const handlePin = async (doc) => {
  try {
    const apiCall = doc.pinned ? api.unpinDoc : api.pinDoc
    const res = await apiCall(doc.filename)
    if (res.success) {
      message.success(doc.pinned ? '已取消置顶' : '已置顶')
      const currentFilename = selectedDoc.value?.filename
      await loadDocs()
      // 恢复选中状态
      if (currentFilename) {
        selectedDoc.value = docs.value.find((d) => d.filename === currentFilename) || docs.value[0]
      }
    }
  } catch {
    message.error('操作失败')
  }
}

const handleDownload = (doc) => {
  const blob = new Blob([doc.content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = doc.filename
  a.click()
  URL.revokeObjectURL(url)
}

const handleDelete = async (filename) => {
  try {
    const res = await api.deleteDoc(filename)
    if (res.success) {
      message.success('已删除')
      const wasSelected = selectedDoc.value?.filename === filename
      selectedDoc.value = null
      await loadDocs()
      if (wasSelected && docs.value.length > 0) {
        selectedDoc.value = docs.value[0]
      }
    } else {
      message.error(res.msg || '删除失败')
    }
  } catch {
    message.error('删除失败')
  }
}

onMounted(() => {
  loadDocs()
})
</script>

<style scoped>
.doc-layout {
  display: flex;
  gap: 28px;
  min-height: 300px;
}
.doc-list {
  width: 320px;
  flex-shrink: 0;
  border-right: 1px solid var(--n-border-color);
  padding-right: 16px;
}
.doc-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
  line-height: 1.5;
}
.doc-item:hover {
  background: var(--n-color-embedded);
}
.doc-item.active {
  background: var(--n-color-pressed);
  font-weight: 500;
}
.doc-item.active .doc-title {
  color: var(--n-color-target);
}
.doc-title {
  flex: 1;
  font-size: 14px;
  word-break: keep-all;
  min-width: 0;
}
.doc-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  margin-left: 8px;
}
.doc-detail {
  flex: 1;
  min-width: 0;
}
.doc-content {
  line-height: 1.8;
  color: var(--n-text-color);
}
.doc-content :deep(p) {
  margin: 8px 0;
}
.doc-content :deep(ul),
.doc-content :deep(ol) {
  padding-left: 20px;
}
.doc-content :deep(li) {
  margin: 4px 0;
}
.doc-content :deep(code) {
  background: var(--n-color-embedded);
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 13px;
}
.doc-content :deep(pre) {
  background: var(--n-color-embedded);
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
}
.doc-content :deep(pre code) {
  background: transparent;
  padding: 0;
}
.doc-content :deep(h2) {
  font-size: 18px;
  margin: 16px 0 8px;
}
.doc-content :deep(h3) {
  font-size: 16px;
  margin: 14px 0 6px;
}
.doc-content :deep(strong) {
  font-weight: 600;
}
</style>

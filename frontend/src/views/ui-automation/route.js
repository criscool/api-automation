import i18n from '~/i18n'
const { t } = i18n.global

const Layout = () => import('@/layout/index.vue')

export default {
  name: 'UI自动化',
  path: '/ui-automation',
  component: Layout,
  redirect: '/ui-automation/dashboard',
  meta: {
    title: 'UI自动化',
    icon: 'material-symbols:web',
    order: 3,
  },
  children: [
    {
      name: 'UI自动化仪表板',
      path: 'dashboard',
      component: () => import('./dashboard/index.vue'),
      meta: {
        title: 'UI自动化仪表板',
        icon: 'carbon:dashboard',
      },
    },
    {
      name: 'UI页面分析',
      path: 'page-analysis',
      component: () => import('./page-analysis/index.vue'),
      meta: {
        title: '页面分析',
        icon: 'mdi:image-search-outline',
        description: '上传页面截图，AI 视觉模型识别可交互元素',
      },
    },
    {
      name: 'UI图片库',
      path: 'image-library',
      component: () => import('./image-library/index.vue'),
      meta: {
        title: '图片库',
        icon: 'mdi:image-multiple-outline',
        description: '页面截图复用资源池 - SHA256 自动查重',
      },
    },
    {
      name: 'UI脚本管理',
      path: 'script-management',
      component: () => import('./script-management/index.vue'),
      meta: {
        title: '脚本管理',
        icon: 'mdi:script-text-outline',
        description: '管理 Playwright UI 测试脚本',
      },
    },
    {
      name: 'UI录制管理',
      path: 'recording-management',
      component: () => import('./recording-management/index.vue'),
      meta: {
        title: '录制管理',
        icon: 'mdi:record-rec',
        description: 'Playwright codegen 录制 + AI 后处理生成脚本',
      },
    },
    {
      name: 'UI用例管理',
      path: 'testcase-management',
      component: () => import('./testcase-management/index.vue'),
      meta: {
        title: '用例管理',
        icon: 'mdi:file-tree',
        description: '按分类管理 UI 自动化脚本',
      },
    },
    {
      name: 'UI执行报告',
      path: 'execution-reports',
      component: () => import('./execution-reports/index.vue'),
      meta: {
        title: '执行报告',
        icon: 'mdi:file-chart',
        description: '查看 UI 脚本执行结果与产物',
      },
    },
  ],
}

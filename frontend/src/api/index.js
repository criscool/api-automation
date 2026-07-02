import { request } from '@/utils'

export default {
  login: (data) => request.post('/base/access_token', data, { noNeedToken: true }),
  getUserInfo: () => request.get('/base/userinfo'),
  getUserMenu: () => request.get('/base/usermenu'),
  getUserApi: () => request.get('/base/userapi'),
  // profile
  updatePassword: (data = {}) => request.post('/base/update_password', data),
  // users
  getUserList: (params = {}) => request.get('/user/list', { params }),
  getUserById: (params = {}) => request.get('/user/get', { params }),
  createUser: (data = {}) => request.post('/user/create', data),
  updateUser: (data = {}) => request.post('/user/update', data),
  deleteUser: (params = {}) => request.delete(`/user/delete`, { params }),
  resetPassword: (data = {}) => request.post(`/user/reset_password`, data),
  // role
  getRoleList: (params = {}) => request.get('/role/list', { params }),
  createRole: (data = {}) => request.post('/role/create', data),
  updateRole: (data = {}) => request.post('/role/update', data),
  deleteRole: (params = {}) => request.delete('/role/delete', { params }),
  updateRoleAuthorized: (data = {}) => request.post('/role/authorized', data),
  getRoleAuthorized: (params = {}) => request.get('/role/authorized', { params }),
  // menus
  getMenus: (params = {}) => request.get('/menu/list', { params }),
  createMenu: (data = {}) => request.post('/menu/create', data),
  updateMenu: (data = {}) => request.post('/menu/update', data),
  deleteMenu: (params = {}) => request.delete('/menu/delete', { params }),
  // apis
  getApis: (params = {}) => request.get('/api/list', { params }),
  createApi: (data = {}) => request.post('/api/create', data),
  updateApi: (data = {}) => request.post('/api/update', data),
  deleteApi: (params = {}) => request.delete('/api/delete', { params }),
  refreshApi: (data = {}) => request.post('/api/refresh', data),
  // depts
  getDepts: (params = {}) => request.get('/dept/list', { params }),
  createDept: (data = {}) => request.post('/dept/create', data),
  updateDept: (data = {}) => request.post('/dept/update', data),
  deleteDept: (params = {}) => request.delete('/dept/delete', { params }),
  // auditlog
  getAuditLogList: (params = {}) => request.get('/auditlog/list', { params }),

  // 环境管理（API + UI 自动化共用的执行环境）
  listEnvironments: (params = {}) => request.get('/environments', { params }),
  createEnvironment: (data = {}) => request.post('/environments', data),
  updateEnvironment: (envId, data = {}) => request.put(`/environments/${envId}`, data),
  deleteEnvironment: (envId) => request.delete(`/environments/${envId}`),
  activateEnvironment: (envId) => request.post(`/environments/${envId}/activate`),
  deactivateAllEnvironments: () => request.post('/environments/deactivate-all'),

  // API自动化相关接口
  // 仪表板统计
  getDashboardStatistics: () => request.get('/api-automation/dashboard/statistics'),
  getRecentActivities: (params = {}) => request.get('/api-automation/dashboard/activities', { params }),
  getExecutionQueue: () => request.get('/api-automation/dashboard/queue'),
  getSystemStatus: () => request.get('/api-automation/dashboard/status'),

  // 文档管理
  uploadDocument: (formData) => request.post('/api-automation/upload-document', formData),
  getApiAutomationParseStatus: (sessionId) => request.get(`/api-automation/parse-status/${sessionId}`),
  triggerDocumentParse: (sessionId, config = {}) => request.post(`/api-automation/parse-document/${sessionId}`, config),
  getParseResult: (params = {}) => request.get('/api-automation/parse-result', { params }),
  getApiAutomationDocuments: (params = {}) => request.get('/api-automation/documents', { params }),
  getDocumentDetail: (params = {}) => request.get('/api-automation/document-detail', { params }),

  // 接口管理
  // 文档管理API
  getApiDocuments: (params = {}) => request.get('/interface/documents', { params }),
  getApiDocumentDetail: (docId) => request.get(`/interface/documents/${docId}`),
  deleteApiDocument: (docId) => request.delete(`/interface/documents/${docId}`),
  uploadApiDocument: (formData) => request.post('/interface/upload-document', formData),
  parseApiDocument: (sessionId, config = {}) => request.post(`/interface/parse-document/${sessionId}`, config),
  getParseStatus: (sessionId) => request.get(`/interface/parse-status/${sessionId}`),

  // 接口管理API
  getApiInterfaces: (params = {}) => request.get('/interface/interfaces', { params }),
  getApiInterfaceDetail: (interfaceId) => request.get(`/interface/interfaces/${interfaceId}`),
  deleteApiInterface: (interfaceId) => request.delete(`/interface/interfaces/${interfaceId}`),
  getInterfaceStatistics: () => request.get('/interface/statistics'),
  generateInterfaceScript: (interfaceId) => request.post(`/interface/interfaces/${interfaceId}/generate-script`),
  resolveDuplicates: (data) => request.post('/interface/resolve-duplicates', data),
  getScriptGenerationStatus: (sessionId) => request.get(`/interface/script-generation/${sessionId}/status`),
  getSessionLogs: (sessionId, params = {}) => request.get(`/interface/session-logs/${sessionId}`, { params }),

  // 脚本管理API（已迁移到新模块）
  getAllScripts: (params = {}) => request.get('/scripts', { params }),
  getInterfaceScripts: (interfaceId, includeInactive = false) => request.get(`/scripts/interfaces/${interfaceId}/scripts`, { params: { include_inactive: includeInactive } }),
  getInterfaceScriptStatistics: (interfaceId) => request.get(`/scripts/interfaces/${interfaceId}/scripts/statistics`),
  getScriptGenerationHistory: (interfaceId, limit = 10) => request.get(`/scripts/interfaces/${interfaceId}/scripts/generation-history`, { params: { limit } }),
  getDocumentScriptOverview: (documentId) => request.get(`/scripts/documents/${documentId}/scripts/overview`),
  getScriptDetail: (scriptId) => request.get(`/scripts/${scriptId}`),
  updateScriptCode: (scriptId, data = {}) => request.put(`/scripts/${scriptId}/content`, data),
  updateScriptStatus: (scriptId, data) => request.put(`/scripts/${scriptId}/status`, data),
  deleteScript: (scriptId, softDelete = true) => request.delete(`/scripts/${scriptId}`, { params: { soft_delete: softDelete } }),
  batchUpdateScriptStatus: (data) => request.put('/scripts/batch-status', data),

  // 脚本执行API（新模块）
  executeScripts: (data) => request.post('/scripts/execute', data),
  executeSingleScript: (scriptId, data = {}) => request.post(`/scripts/${scriptId}/execute`, data),
  runSingleScript: (scriptId, data = {}) => request.post(`/scripts/${scriptId}/run`, data),
  getScriptExecutionResult: (scriptId, executionId) => request.get(`/scripts/${scriptId}/execution/${executionId}`),
  getScriptExecutionHistory: (scriptId, params = {}) => request.get(`/scripts/${scriptId}/executions`, { params }),
  getScriptExecutionDetail: (executionId) => request.get(`/scripts/executions/${executionId}`),
  getScriptExecutionLogs: (executionId, params = {}) => request.get(`/scripts/executions/${executionId}/logs`, { params }),
  stopScriptExecution: (executionId) => request.post(`/scripts/executions/${executionId}/stop`),

  // 用例管理API（脚本管理页面切换到用例维度）
  getAllTestCases: (params = {}) => request.get('/testcases', { params }),
  getTestCaseDetail: (testId) => request.get(`/testcases/${testId}`),
  deleteTestCase: (testId) => request.delete(`/testcases/${testId}`),
  runTestCase: (testId, data = {}) => request.post(`/testcases/${testId}/run`, data),
  updateTestCase: (testId, data) => request.put(`/testcases/${testId}`, data),
  executeTestCases: (data) => request.post('/testcases/execute', data),
  moveTestCase: (testId, data) => request.put(`/testcases/${testId}/move`, data),
  batchMoveTestCases: (data) => request.put('/testcases/batch-move', data),

  // 用例分类管理API
  getCategoryTree: (params = {}) => request.get('/testcase-categories/tree', { params }),
  autoExtractCategories: (params = {}) => request.post('/testcase-categories/auto-extract', null, { params }),
  createCategory: (data) => request.post('/testcase-categories', data),
  updateCategory: (categoryId, data) => request.put(`/testcase-categories/${categoryId}`, data),
  deleteCategory: (categoryId) => request.delete(`/testcase-categories/${categoryId}`),
  recommendCategoryRules: (params) => request.post('/testcase-categories/recommend-rules', null, { params, timeout: 120000 }),
  applyCategoryRecommendations: (data) => request.post('/testcase-categories/apply-recommendations', data),
  autoClassifyTestCases: () => request.post('/testcase-categories/auto-classify'),

  // 原有接口管理（保持兼容）
  getApiEndpoints: (params = {}) => request.get('/api-automation/endpoints', { params }),
  analyzeApiEndpoints: (data = {}) => request.post('/api-automation/analyze-endpoints', data),
  getAnalysisResult: (params = {}) => request.get('/api-automation/analysis-result', { params }),

  // 测试脚本管理
  getTestScripts: (params = {}) => request.get('/api-automation/test-scripts', { params }),
  createTestScript: (data = {}) => request.post('/api-automation/test-scripts', data),
  updateTestScript: (data = {}) => request.put('/api-automation/test-scripts', data),
  deleteTestScript: (params = {}) => request.delete('/api-automation/test-scripts', { params }),
  getScriptContent: (params = {}) => request.get('/api-automation/script-content', { params }),
  updateScriptContent: (data = {}) => request.put('/api-automation/script-content', data),
  executeTestScript: (data = {}) => request.post('/api-automation/execute-script', data),
  debugTestScript: (data = {}) => request.post('/api-automation/debug-script', data),
  getLegacyScriptExecutionHistory: (params = {}) => request.get('/api-automation/script-history', { params }),

  // 测试生成
  generateTestScripts: (data = {}) => request.post('/api-automation/generate-tests', data),
  getGenerationResult: (params = {}) => request.get('/api-automation/generation-result', { params }),
  executeScript: (data = {}) => request.post('/api-automation/execute-script', data),
  executeAllScripts: (data = {}) => request.post('/api-automation/execute-all-scripts', data),

  // 测试执行
  getTestExecutions: (params = {}) => request.get('/api-automation/test-executions', { params }),
  executeTests: (data = {}) => request.post('/api-automation/execute-tests', data),
  getExecutionDetail: (params = {}) => request.get('/api-automation/execution-detail', { params }),
  getTestResults: (params = {}) => request.get('/api-automation/test-results', { params }),
  getExecutionLogsLegacy: (params = {}) => request.get('/api-automation/execution-logs', { params }),
  stopExecution: (data = {}) => request.post('/api-automation/stop-execution', data),

  // 测试报告
  generateTestReport: (data = {}) => request.post('/api-automation/generate-report', data),
  getTestReports: (params = {}) => request.get('/api-automation/test-reports', { params }),
  getReportContent: (params = {}) => request.get('/api-automation/report-content', { params }),
  downloadReport: (params = {}) => request.get('/api-automation/download-report', { params, responseType: 'blob' }),

  // 定时任务管理
  getScheduledTasks: (params = {}) => request.get('/api-automation/scheduled-tasks', { params }),
  createScheduledTask: (data = {}) => request.post('/api-automation/scheduled-tasks', data),
  updateScheduledTask: (data = {}) => request.put('/api-automation/scheduled-tasks', data),
  deleteScheduledTask: (params = {}) => request.delete('/api-automation/scheduled-tasks', { params }),
  updateTaskStatus: (data = {}) => request.put('/api-automation/task-status', data),
  getTaskExecutionHistory: (params = {}) => request.get('/api-automation/task-history', { params }),

  // 系统管理
  getSystemLogs: (params = {}) => request.get('/api-automation/logs', { params }),
  getAgentMetrics: (params = {}) => request.get('/api-automation/metrics', { params }),

  // 依赖 JSON 导入
  importDependencyDoc: (formData) => request.post('/api-automation/dependency-import', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  getDependencyImportResult: (params) => request.get('/api-automation/dependency-import-result', { params }),

  // 执行报告API（新模块）
  getExecutionReports: (params = {}) => request.get('/execution-reports', { params }),
  getExecutionReportDetail: (executionId) => request.get(`/execution-reports/${executionId}`),
  getExecutionStatistics: (params = {}) => request.get('/execution-reports/statistics/summary', { params }),
  generateExecutionReport: (executionId, data) => request.post(`/execution-reports/${executionId}/generate`, data),
  previewReportFile: (executionId, fileName) => request.get(`/execution-reports/${executionId}/preview/${fileName}`, { responseType: 'text' }),
  getReportDownloadUrl: (executionId, fileName) => `/api/v1/execution-reports/${executionId}/download/${fileName}`,
  getExecutionLogs: (executionId, params = {}) => request.get(`/execution-reports/${executionId}/logs`, { params }),
  deleteExecutionReport: (executionId) => request.delete(`/execution-reports/${executionId}`),
  exportExecutionReport: (executionId, format = 'json') => request.get(`/execution-reports/${executionId}/export`, { params: { format } }),
  shareExecutionReport: (executionId) => request.post(`/execution-reports/${executionId}/share`),
  getSharedReport: (shareToken) => request.get(`/execution-reports/shared/${shareToken}`),

  // AI 诊断与自愈（Phase 1：交互式诊断 / Phase 2：应用补丁 + 重跑验证）
  healDiagnose: (data = {}) => request.post('/heal/diagnose', data),
  healGetResult: (sessionId) => request.get(`/heal/sessions/${sessionId}/result`),
  healStreamUrl: (sessionId) => `/api/v1/heal/sessions/${sessionId}/stream`,
  healDownloadPatchUrl: (sessionId) => `/api/v1/heal/sessions/${sessionId}/patch`,
  healApplyPatch: (sessionId, data = {}) => request.post(`/heal/sessions/${sessionId}/apply`, data, { timeout: 300000 }),

  // 平台文档管理（首页说明文档）
  getDocs: (params = {}) => request.get('/docs', { params }),
  getDocDetail: (filename) => request.get(`/docs/${filename}`),
  uploadDoc: (formData) => request.post('/docs/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  deleteDoc: (filename) => request.delete(`/docs/${filename}`),
  pinDoc: (filename) => request.post(`/docs/${filename}/pin`),
  unpinDoc: (filename) => request.post(`/docs/${filename}/unpin`),

  // ========================================================================
  // UI 自动化（阶段二）
  // ========================================================================
  uiHealth: () => request.get('/ui-automation/health'),
  // 截图上传：让浏览器自动带 boundary，不要手动设 Content-Type
  uiUploadScreenshot: (formData) => request.post('/ui-automation/screenshots/upload', formData),
  // 页面分析
  uiAnalyzePage: (data = {}) => request.post('/ui-automation/page-analysis/analyze', data),
  uiListAnalyses: (params = {}) => request.get('/ui-automation/page-analysis', { params }),
  uiGetAnalysis: (analysisId) => request.get(`/ui-automation/page-analysis/${analysisId}`),
  uiDeleteAnalysis: (analysisId) => request.delete(`/ui-automation/page-analysis/${analysisId}`),
  // SSE 流式 URL（前端 EventSource 用，不走 axios）
  uiAnalysisStreamUrl: (sessionId) => `/api/v1/ui-automation/page-analysis/stream/${sessionId}`,
  // 脚本管理
  uiGenerateScript: (data = {}) => request.post('/ui-automation/scripts/generate', data),
  uiCreateManualScript: (data = {}) => request.post('/ui-automation/scripts/manual', data),
  uiListScripts: (params = {}) => request.get('/ui-automation/scripts', { params }),
  uiGetScript: (scriptId) => request.get(`/ui-automation/scripts/${scriptId}`),
  uiUpdateScript: (scriptId, data = {}) => request.put(`/ui-automation/scripts/${scriptId}`, data),
  uiDeleteScript: (scriptId) => request.delete(`/ui-automation/scripts/${scriptId}`),
  uiCheckScriptStatus: (analysisId) => request.get(`/ui-automation/scripts/check/${analysisId}`),

  // ========================================================================
  // UI 自动化（阶段三）—— 执行 + 报告
  // ========================================================================
  uiTriggerExecution: (data = {}) => request.post('/ui-automation/executions', data),
  uiListExecutions: (params = {}) => request.get('/ui-automation/executions', { params }),
  uiGetExecution: (executionId) => request.get(`/ui-automation/executions/${executionId}`),
  uiCancelExecution: (executionId) => request.post(`/ui-automation/executions/${executionId}/cancel`),
  // SSE 执行进度流：前端用 EventSource，sessionId 由 query 传
  uiExecutionStreamUrl: (executionId, sessionId) =>
    `/api/v1/ui-automation/executions/${executionId}/events?session_id=${encodeURIComponent(sessionId)}`,
  uiListReports: (params = {}) => request.get('/ui-automation/reports', { params }),
  uiGetReport: (reportId) => request.get(`/ui-automation/reports/${reportId}`),
  // ---- UI 自动化 - Allure 按需生成（前端按钮触发，异步生成 + 前端轮询）----
  uiGetAllureCliStatus: () => request.get('/ui-automation/executions/allure/cli-status'),
  uiTriggerSingleAllure: (executionId) =>
    request.post(`/ui-automation/executions/${executionId}/allure/generate`),
  uiTriggerBatchAllure: (batchId) =>
    request.post(`/ui-automation/executions/batches/${batchId}/allure/generate`),

  // ---- UI 自动化 - 图片库(阶段四) ----
  uiUploadLibraryImage: (formData) =>
    request.post('/ui-automation/image-library/upload', formData),
  uiListLibraryImages: (params = {}) =>
    request.get('/ui-automation/image-library', { params }),
  uiGetLibraryImage: (imageId) =>
    request.get(`/ui-automation/image-library/${imageId}`),
  uiUpdateLibraryImage: (imageId, data = {}) =>
    request.patch(`/ui-automation/image-library/${imageId}`, data),
  uiDeleteLibraryImage: (imageId, force = false) =>
    request.delete(`/ui-automation/image-library/${imageId}`, { params: { force } }),

  // ---- UI 自动化 - 录制(阶段四) ----
  uiCreateRecording: (data = {}) => request.post('/ui-automation/recordings', data),
  uiListRecordings: (params = {}) => request.get('/ui-automation/recordings', { params }),
  uiGetRecording: (sessionId) => request.get(`/ui-automation/recordings/${sessionId}`),
  uiCancelRecording: (sessionId) =>
    request.post(`/ui-automation/recordings/${sessionId}/cancel`),
  uiDeleteRecording: (sessionId, purgeRaw = true) =>
    request.delete(`/ui-automation/recordings/${sessionId}`, { params: { purge_raw: purgeRaw } }),
  uiRepolishRecording: (sessionId, data = {}) =>
    request.post(`/ui-automation/recordings/${sessionId}/repolish`, data),
  uiReRecord: (sessionId) =>
    request.post(`/ui-automation/recordings/${sessionId}/re-record`),
  // SSE 录制进度流:session_sid 与 path session_id 必须相等
  uiRecordingStreamUrl: (sessionId) =>
    `/api/v1/ui-automation/recordings/${sessionId}/events?session_sid=${encodeURIComponent(sessionId)}`,

  // ---- 批量执行 ----
  uiTriggerBatchExecution: (data = {}) => request.post('/ui-automation/batches', data),
  uiListBatches: (params = {}) => request.get('/ui-automation/batches', { params }),
  uiGetBatch: (batchId) => request.get(`/ui-automation/batches/${batchId}`),
  uiCancelBatch: (batchId) => request.post(`/ui-automation/batches/${batchId}/cancel`),
  uiBatchEventsUrl: (batchId, sessionId) =>
    `/api/v1/ui-automation/batches/${batchId}/events?session_id=${encodeURIComponent(sessionId)}`,

  // ---- UI 自动化 - 用例分类管理 ----
  uiGetCategoryTree: (params = {}) => request.get('/ui-automation/categories/tree', { params }),
  uiCreateCategory: (data = {}) => request.post('/ui-automation/categories', data),
  uiUpdateCategory: (categoryId, data = {}) => request.put(`/ui-automation/categories/${categoryId}`, data),
  uiDeleteCategory: (categoryId) => request.delete(`/ui-automation/categories/${categoryId}`),
  uiAutoExtractCategories: (params = {}) => request.post('/ui-automation/categories/auto-extract', null, { params }),
  uiAutoClassifyScripts: () => request.post('/ui-automation/categories/auto-classify'),

  // ---- UI 自动化 - 脚本分类操作 ----
  uiBatchMoveScripts: (data = {}) => request.put('/ui-automation/scripts/batch-move', data),
  uiMoveScript: (scriptId, data = {}) => request.put(`/ui-automation/scripts/${scriptId}/move`, data),
}

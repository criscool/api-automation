# API Capture — 浏览器录制接口捕获

通过 Playwright MCP 打开可见浏览器，用户手动操作，自动捕获并提取 API 接口信息，去重后保存。

## 参数

$ARGUMENTS — 子命令及参数，格式：`start <url>` | `record` | `stop [模块名]`

---

## 子命令处理

根据 $ARGUMENTS 的第一个词判断子命令并执行对应逻辑。

### 子命令：start

**触发**：`/api-capture start <url>`

**步骤**：
1. 从参数中提取目标 URL
2. 使用 `mcp__playwright__browser_navigate` 导航到目标 URL
3. 使用 `mcp__playwright__browser_network_requests`（参数 `static: false`）获取当前请求列表
4. 记录最大请求编号作为基线（后续 record 只关注大于此编号的请求）
5. 告知用户：
   - 浏览器已打开，可以开始操作
   - 操作完一步后输入 `/api-capture record` 提取接口
   - 全部结束后输入 `/api-capture stop 模块名` 保存

**注意**：如果 URL 使用自签名证书（如内网 HTTPS），Playwright MCP 会自动忽略证书错误。

### 子命令：record

**触发**：`/api-capture record`

**步骤**：
1. 使用 `mcp__playwright__browser_network_requests`（参数 `static: false`）获取最新请求列表
2. 找出编号大于当前基线的所有新请求
3. 对每个新请求的 URL 应用过滤规则（见下方），排除系统噪音
4. 对通过过滤的业务请求，使用 `mcp__playwright__browser_network_request` 分别提取：
   - 请求概要（index 参数获取 method, url, status, duration, headers）
   - 请求体（part="request-body"，仅 POST/PUT/PATCH 请求）
   - 响应体（part="response-body"）
5. 将提取的接口信息以表格形式展示给用户（method、path、status、耗时、请求体摘要、响应体摘要）
6. 将这些接口暂存到内存中（累积所有 record 步骤的结果）
7. 更新基线为当前最大请求编号
8. 提示用户：继续操作后再次 `/api-capture record`，或 `/api-capture stop 模块名` 保存

**并行优化**：对于多个业务请求，尽量并行调用 `browser_network_request` 提取详情，减少等待时间。

### 子命令：stop

**触发**：`/api-capture stop [模块名]`

**步骤**：

#### 1. 确定模块名
- 如果参数中提供了模块名，直接使用
- 如果未提供，使用 `mcp__playwright__browser_snapshot` 获取当前页面 URL，从 path 推断模块名（如 `/AssetManagement` → `asset-management`）

#### 2. 最后一次 record
- 执行一次 record 逻辑，确保用户最后的操作也被捕获

#### 3. 内部去重
对本次捕获的所有 API，按 `method + parameterized_path` 分组：
- 同一接口多次出现 → 只保留最后一次的请求/响应数据
- 路径参数化规则：
  - 24位十六进制字符串（MongoDB ObjectId，如 `69e0a62159e44250c045fa9a`） → `:id`
  - 纯数字路径段（如 `/items/123`） → `:id`
  - UUID 格式（如 `de30af05-8230-40c5-b93c-da345ae1031e`） → `:id`

#### 4. 与已有文件去重
- 使用 Read 工具读取 `api-docs/<模块名>-api.json`（如果文件存在）
- 对于本次捕获的每个接口，在已有文件中查找同 `method + path` 的条目：
  - **找到且结构相同**：跳过。结构对比方法 — 将 request body 和 response body 分别解析为 JSON，递归提取所有 key（一层深度），比较 key 集合是否相同
  - **找到但结构不同**：标记为"更新"，用新数据覆盖旧条目
  - **未找到**：标记为"新增"

#### 5. 生成接口名称
对每个新增/更新的接口，从 path 的最后一段自动生成 name：
- `/knowasset/list` → "资产列表"（通过 path 最后一段推断）
- `/knowasset/add` → "新增资产"
- `/knowasset/delete` → "删除资产"
- 如果无法推断，使用 `METHOD path` 格式作为 name

#### 6. 构建 JSON 并保存
- 使用 Bash 工具创建 `api-docs/` 目录（如不存在）：`mkdir -p api-docs`
- 提取 commonHeaders（从所有请求的公共 headers 中取交集，包括 Authorization、Content-Type、X-Requested-With、X-Requested-By）
- 构建 JSON 对象，格式如下：

```json
{
  "baseUrl": "从 URL 中提取的 origin（如 https://172.16.8.190）",
  "module": "模块名",
  "capturedAt": "当前 ISO 时间戳",
  "commonHeaders": {
    "Authorization": "从请求中提取的认证头",
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "X-Requested-By": "XMLHttpRequest"
  },
  "apis": [
    {
      "name": "自动推断的接口名称",
      "description": "接口描述（从 method + path 推断）",
      "method": "POST",
      "path": "/api/plugins/.../knowasset/list（参数化后的路径）",
      "request": {
        "headers": {},
        "query": {},
        "body": {}
      },
      "response": {
        "status": 200,
        "example": {}
      }
    }
  ]
}
```

- 如果文件已存在，合并新增/更新的接口到已有的 apis 数组中（保持已有未变化的接口不动）
- 使用 Write 工具写入 `api-docs/<模块名>-api.json`

#### 7. 输出报告
告知用户：
- 文件保存路径
- 新增了几个接口
- 更新了几个接口（结构变化）
- 跳过了几个接口（已存在且无变化）
- 列出每个接口的 method + path + 状态（新增/更新/跳过）

---

## 过滤规则

以下 URL 模式的请求视为系统噪音，record 时自动排除。匹配方式为 URL path 包含指定字符串：

| 模式 | 排除原因 |
|---|---|
| `/api/system/` | 系统通知、集群节点、会话、本地化等轮询 |
| `/api/cluster/` | 集群指标心跳 |
| `/api/streams` | 数据流轮询 |
| `/api/views/` | 视图/字段元数据 |
| `/api/search/decorators` | 搜索装饰器配置 |
| `/api/base64/` | Base64 编码的静态资源 |
| `/api/tianxiangMenu/` | 菜单数据 |
| `/api/users/` | 当前用户信息查询 |
| `/plugin/` | 插件静态资源（JS/CSS）加载 |
| 精确匹配 path 为 `/api/` | API 根路径探活请求 |

只有不匹配以上任何模式的请求才被视为业务接口并被记录。

---

## 注意事项

- 每次 record 时要对比新请求列表和基线编号，只处理增量
- 并行提取多个请求的 body 可以显著加快 record 速度
- response body 如果过大（超过 10KB），只保存前 10KB 并截断
- request/response body 尝试 JSON.parse，如果是合法 JSON 则存为对象；否则存为字符串
- commonHeaders 中的 Authorization 值来自实际请求，保存时原样记录（用于后续测试复用）

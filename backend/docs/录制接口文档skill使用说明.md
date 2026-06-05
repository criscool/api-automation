# API Capture 使用指南

## 简介

通过浏览器自动录制接口，保存为结构化 JSON，并自动分析接口间的数据流依赖关系，生成测试链。

## 首次安装

### 1. 获取 skill 文件

将 `置顶的 api-capture.md` 下载放到你项目根目录的相同路径下：

```
你的项目/
└── .claude/
    └── commands/
        └── api-capture.md   ← 放在这里
```

Claude Code 会自动识别该目录下的 `.md` 文件作为自定义斜杠命令，文件名即命令名。

### 2. 配置 Playwright MCP

skill 依赖 Playwright MCP 来控制浏览器。在 Claude Code 的 MCP 配置中添加：

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@anthropic/mcp-playwright"]
    }
  }
}
```

配置完成后重启 Claude Code 即可使用。

### 3. 验证

输入 `/api-capture` 如果看到命令被识别，说明安装成功。

## 快速上手

完整录制一个模块只需 3 步：

```
/api-capture start https://你的系统地址/
→ 浏览器打开，在页面上操作你要录制的功能
→ /api-capture stop 模块中文名
```

模块名会自动转为英文，例如 `策略新增搜索删除` → `strategy-crud`。

## 四个子命令

### /api-capture start \<url\>

打开浏览器并导航到目标地址，建立请求基线（后续只捕获增量请求）。

```
/api-capture start https://172.16.8.190/
```

执行后会提示"浏览器已打开，可以开始操作"。

### /api-capture record

提取你上一次 record（或 start）之后产生的新业务请求，以表格展示。

```
/api-capture record
```

**可以反复执行**：操作一步 → record 一次，也可以全部操作完一次性 record。系统轮询（心跳、通知等）会自动过滤。

### /api-capture stop \<模块名\>

结束录制，分析重复请求（弹窗询问是否合并），保存为 JSON 文件。

```
/api-capture stop 策略新增搜索删除
```

模块名用中文即可，会自动转为英文 kebab-case。对应关系：

| 输入 | 输出 |
|---|---|
| `态势大屏` | `situation-dashboard` |
| `风险漏洞` | `risk-vulnerability` |
| `告警规则复制查看删除` | `alarm-rule-crud` |
| `资产学习挂起` | `asset-learn-suspend` |

### /api-capture analyze \<模块名\>

分析已保存模块的接口依赖关系，生成测试链。

```
/api-capture analyze strategy-crud
```

输出：数据流依赖（如"列表返回的 ID → 删除接口的 entities 参数"）、接口配对（add↔delete）、推荐测试链。

## 输出文件

保存在 `api-docs/` 目录下：

| 文件 | 说明 |
|---|---|
| `<模块名>.json` | 接口清单，含 method、path、request body、response example |
| `<模块名>-dependencies.json` | 依赖分析，含数据流、配对接口、测试链 |

同名文件已存在时自动追加时间戳后缀，不会覆盖已有数据。

## 重复请求处理

stop 时会自动分析：同一个接口被多次调用时，如果 body 参数完全一致 → 弹窗询问是否合并（只保留首次）；如果 body 参数不同（如不同的搜索关键词）→ 全部保留。

## 自动过滤的噪音

以下请求会被自动排除，不会出现在录制结果中：

- `/api/system/` — 系统通知、会话轮询
- `/api/cluster/` — 集群心跳
- `/api/streams` — 数据流轮询
- `/api/views/` — 视图元数据
- `/api/search/decorators` — 搜索装饰器
- `/api/base64/` — 静态资源
- `/api/tianxiangMenu/` — 菜单数据
- `/api/users/` — 用户信息查询
- `/plugin/` — 插件 JS/CSS
- `/api/` — 根路径探活

## 注意事项

- 自签名证书（内网 HTTPS）会自动忽略，无需额外配置
- 如果浏览器会话断开，重新 start 即可
- 录制过程中可以切换页面、切换 tab，所有业务请求都会被捕获
- analyze 功能需要先完成 stop 生成 JSON 文件后才能使用

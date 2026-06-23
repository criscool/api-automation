# UI 自动化执行工作区

> **零回归红线**：此目录与 `backend/generated_tests/` 物理隔离，禁止混用 Python 解释器进程、依赖、报告。

## 目录约定

| 目录 | 用途 | 是否进 git |
|------|------|----------|
| `scripts/` | Playwright `.spec.js` / `.spec.ts` 测试脚本 | ✅ |
| `reports/` | Playwright HTML 报告归档 | ❌（产物） |
| `screenshots/` | 失败截图归档 | ❌（产物） |
| `videos/` | 失败视频归档 | ❌（产物） |
| `logs/` | 执行日志归档 | ❌（产物） |
| `package.json` | npm 依赖清单（一期阶段 3 创建） | ✅ |
| `playwright.config.js` | Playwright 配置（一期阶段 3 创建） | ✅ |

## 阶段一现状

阶段一只建立目录骨架，不安装 Node/Playwright，所有 health 检查会显示 `playwright unavailable`。

## 阶段三初始化命令

```bash
cd backend/generated_ui_tests
npm init -y
npm i -D @playwright/test
npx playwright install --with-deps chromium
```

## 环境前置依赖

- OS：Ubuntu 22.04 LTS（生产）/ Windows 10+（开发可用，但行为可能略异）
- Node.js：≥ 18 LTS
- 磁盘：≥ 50GB（产物滚动 7 天清理）

## 清理策略

由 `app/services/ui_automation/cleanup_service.py`（阶段 3 实现）定时清理：
- `UI_ARTIFACT_RETENTION_DAYS` 之前的产物全部删除
- 保留最近 `UI_KEEP_LATEST_SUCCESS_REPORTS` 条成功记录的报告

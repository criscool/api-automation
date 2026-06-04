---
name: api-test-fixer
description: 专门用于自动化调试和修复失败的 pytest 接口脚本。当用户指定一个失败的测试文件时，该 Skill 会自动执行“运行-捕获报错-探测 API-应用修复-验证”的闭环流程。
---

# api-test-fixer 指导手册

## 核心流程

1. **运行脚本**：使用项目虚拟环境运行测试文件，捕获报错日志。
   ```bash
   cd backend; ..\.venv\Scripts\python.exe -m pytest <file_path> -v
   ```
2. **分析报错**：
   - 提取响应体（从 Allure 步骤或 loguru 日志中）。
   - 识别 4xx/5xx 具体的后端提示（如 "Null XXX", "Cannot invoke...", "Already exists"）。
3. **API 探测**：生成并运行探测脚本确定正确的 Payload 结构。参考 [api_patterns.md](references/api_patterns.md)。
4. **手术式修复**：使用 `replace` 修复 Payload 字段名、数据类型、必填项或断言逻辑。
5. **最终验证**：确保脚本运行通过。

## 修复规范

- **字段名**：后端混合使用蛇形 (`time_from`) 和驼峰 (`streamIds`)。
- **数据类型**：即使名字是 `streamIds`，也可能是字符串而非列表。
- **动态数据**：优先使用 Fixture 实时获取真实 ID，避免硬编码。
- **断言兼容**：同时支持 `type: "success"` 和 `code: 200` 风格。

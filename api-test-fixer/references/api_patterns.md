# 本项目 API 常见陷阱

## 1. 命名规范冲突
- **态势大屏模块**：`time_from`, `time_to` 是蛇形，但 `streamIds` 是驼峰。
- **资产模块**：`_id` 带有下划线，而 `network_name` 是标准蛇形。

## 2. 特殊必填项
- **删除/修改**：通常需要 `_id` 或 `id`。
- **统计接口**：如 `/realTimeAlarmSum` 强制要求 `type` 字段 (int)。
- **资产启停**：强制要求 `stime` 和 `etime` 字符串。

## 3. 响应结构
- 风格 A：`{"code": 200, "msg": "OK", "data": ...}`
- 风格 B：`{"type": "success", "msg": "成功", "data": ...}`
- 风格 C (资产)：直接返回 MongoDB `WriteResult` 字符串，需用正则或包含校验。

## 4. 删除操作
- 成功可能返回 `200 OK` 伴随 JSON，也可能返回 `204 No Content` 无响应体。

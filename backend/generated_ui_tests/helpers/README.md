# UI 自动化 Helpers

> 给 AI 生成器和人工写用例共用的可复用工具集。
> **AI 生成 .spec.ts 时,凡是这里有的能力,优先 import 调用,不要把步骤逐句铺开。**

---

## 目录速查

| 能力 | 函数 | 文件 |
|------|------|------|
| 走默认账号登录 | `loginAsDefault(actions)` | `helpers/auth.ts` |
| 自定义账号登录 | `loginAs(actions, creds)` | `helpers/auth.ts` |
| 列表关键字搜索 | `searchInList(actions, keyword, opts?)` | `helpers/common.ts` |
| 等列表/表格加载 | `waitForListLoaded(actions, expected?)` | `helpers/common.ts` |
| 多级菜单导航 | `navigateToMenu(actions, "A > B > C")` | `helpers/common.ts` |
| 表格行点击 | `openRowByText(actions, "host-01", { actionButton?: "删除" })` | `helpers/common.ts` |
| 确认弹窗 | `confirmDialog(actions, opts?)` | `helpers/common.ts` |
| 取消弹窗 | `cancelDialog(actions, opts?)` | `helpers/common.ts` |
| 表单批量填写 | `fillForm(actions, [{ label, value, type? }])` | `helpers/common.ts` |
| 翻到指定页 | `goToPage(actions, n)` | `helpers/common.ts` |
| 翻下一页 | `goToNextPage(actions)` | `helpers/common.ts` |

---

## 调用约定

所有 helper 第一个参数都是 `actions` 对象,把 fixture 解构出来的 AI 方法打包传进去。

### 标准模板

```ts
import { expect } from "@playwright/test";
import { test } from "./fixture";
import {
  loginAsDefault,
  searchInList,
  navigateToMenu,
  openRowByText,
  confirmDialog,
} from "../helpers";

test("查询主机并删除", async ({ page, aiTap, aiInput, aiAssert, aiWaitFor, aiKeyboardPress }) => {
  const actions = { page, aiTap, aiInput, aiAssert, aiWaitFor, aiKeyboardPress };

  // 1) 登录(走 .env 默认账号)
  await loginAsDefault(actions);

  // 2) 进入业务页面
  await navigateToMenu(actions, "资产管理 > 主机列表");

  // 3) 搜索
  await searchInList(actions, "host-prod-01");

  // 4) 表格行点删除 + 确认
  await openRowByText(actions, "host-prod-01", { actionButton: "删除" });
  await confirmDialog(actions, { successAssertion: "列表中不再出现 host-prod-01" });
});
```

---

## 环境变量

`auth.ts` 走 `.env`(放在 `generated_ui_tests/.env`):

```
UI_LOGIN_URL=https://172.16.8.190/
UI_LOGIN_USERNAME=superadmin
UI_LOGIN_PASSWORD=Admin@123
```

---

## AI 生成器规则(重要)

1. **优先 import helper**,不要把登录步骤(aiInput 用户名 → aiInput 密码 → aiTap 登录)再写一遍。
2. **业务相关的、跨用例可复用的动作**,封装到 helper(命名规则: `動詞 + 名词`,如 `searchInList` / `openRowByText`)。
3. **本用例独占的、一次性的步骤**,直接写在 test 里,不要为了"复用"而过度抽象。
4. helper 函数名一律驼峰、英文,中文留给 `aiInput / aiTap` 的自然语言定位描述。
5. 描述用语要"信息密集" — 颜色 + 位置 + 文字 + 形状,例:`"页面右上角蓝色圆角矩形,文字'登录'"`。

---

## 何时新加 helper

- 同一段 5 行以上的操作,在 ≥2 个用例里出现 → 抽 helper
- 跨业务模块通用 → 放 `common.ts`
- 仅某业务页面专属 → 新建 `helpers/<module>.ts` (如 `helpers/asset.ts`)
- 不要把"一次性的、用例独有的"操作硬塞进 helper

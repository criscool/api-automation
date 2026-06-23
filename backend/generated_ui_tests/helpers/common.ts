/**
 * 通用 UI 操作 helper
 *
 * 设计哲学:
 *  - 把"全平台通用 / 跨用例复用"的操作集中放这里(查询、导航、表格选行、模态确认...)
 *  - 每个函数只关心"动作语义",定位/输入交给传进来的 aiTap/aiInput/aiAssert
 *  - 这些函数不应耦合任何具体业务页面,如果要写"资产管理页的特定操作",请单独建 helpers/asset.ts
 *
 * AI 生成器使用建议:
 *  - 查询资产列表 → searchInList + waitForListLoaded
 *  - 进菜单 → navigateToMenu("资产管理 > 主机列表")
 *  - 表格里点某一行 → openRowByText(matchText) 然后再 aiTap 行内具体按钮
 *  - 弹窗确认 → confirmDialog / cancelDialog
 *
 * 命名约定:
 *  - 动作返回 Promise<void>,调用方一律 await
 *  - 可选第二参数 opts 走对象语法,便于扩展
 */

export interface CommonActions {
  page: any;
  aiInput: (value: string, locate: string) => Promise<void>;
  aiTap: (locate: string) => Promise<void>;
  aiAssert: (expected: string) => Promise<void>;
  aiWaitFor?: (expected: string, opts?: any) => Promise<void>;
  aiKeyboardPress?: (key: string) => Promise<void>;
  aiScroll?: (direction: "up" | "down" | "left" | "right", locate?: string) => Promise<void>;
}

// ---------------------------------------------------------------------------
// 1. 查询 / 搜索
// ---------------------------------------------------------------------------

export interface SearchOptions {
  /** 搜索框定位描述,默认匹配页面顶部最常见的搜索栏 */
  inputLocator?: string;
  /** 触发搜索的按钮描述;如果未提供则按回车 */
  submitButtonLocator?: string;
  /** 搜索结果加载完成后的视觉断言;不传则默认等到"列表区域已刷新" */
  successAssertion?: string;
  /** 是否在搜索前先清空输入框,默认 true */
  clearBefore?: boolean;
}

/**
 * 通用列表搜索:输入关键字 → 触发搜索 → 等待结果。
 * 适用所有"上方 input + 下方表格/卡片列表"的标准布局。
 */
export async function searchInList(
  actions: CommonActions,
  keyword: string,
  opts: SearchOptions = {}
): Promise<void> {
  const inputLocator =
    opts.inputLocator ||
    "页面顶部的搜索/筛选输入框,通常带有放大镜图标或 placeholder 包含'搜索'/'关键字'";

  if (opts.clearBefore !== false) {
    // MidScene 的 aiInput 默认会覆盖,无需手动清空;
    // 但部分场景需要先清空再输入,这里保留入口由调用方控制
  }

  await actions.aiInput(keyword, inputLocator);

  if (opts.submitButtonLocator) {
    await actions.aiTap(opts.submitButtonLocator);
  } else if (actions.aiKeyboardPress) {
    await actions.aiKeyboardPress("Enter");
  } else {
    // 兜底:尝试点击"搜索"按钮
    await actions.aiTap("搜索框右侧或下方的搜索/查询按钮");
  }

  await actions.aiAssert(
    opts.successAssertion ||
      `列表区域已刷新,展示与关键字 "${keyword}" 匹配的结果(或显示"暂无数据")`
  );
}

/**
 * 等待列表加载完成,适合在 goto 后 / 切 tab 后调用。
 */
export async function waitForListLoaded(
  actions: CommonActions,
  expected: string = "页面主要列表/表格区域已完整渲染,行数据可见或显示空状态"
): Promise<void> {
  if (actions.aiWaitFor) {
    await actions.aiWaitFor(expected, { timeoutMs: 15000 });
  } else {
    await actions.aiAssert(expected);
  }
}

// ---------------------------------------------------------------------------
// 2. 导航 / 菜单
// ---------------------------------------------------------------------------

/**
 * 多级菜单导航:传入 "一级菜单 > 二级菜单 > 三级菜单",按顺序逐级点击。
 * 例: navigateToMenu(actions, "资产管理 > 主机列表")
 */
export async function navigateToMenu(
  actions: CommonActions,
  menuPath: string
): Promise<void> {
  const segments = menuPath
    .split(/[>›/》]/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (segments.length === 0) {
    throw new Error("navigateToMenu: menuPath 不能为空");
  }
  for (const seg of segments) {
    await actions.aiTap(`左侧导航菜单中的 "${seg}" 项`);
  }
  if (actions.aiWaitFor) {
    await actions.aiWaitFor(`已进入 "${segments[segments.length - 1]}" 页面,主区域内容已渲染`, {
      timeoutMs: 10000,
    });
  }
}

// ---------------------------------------------------------------------------
// 3. 表格行操作
// ---------------------------------------------------------------------------

/**
 * 在表格里找到含某段文字的一行,点击该行(或行内具体按钮)。
 *
 * 用法 A:点整行(进入详情)
 *   await openRowByText(actions, "host-prod-01");
 *
 * 用法 B:点行内某个按钮(如"删除")
 *   await openRowByText(actions, "host-prod-01", { actionButton: "删除" });
 */
export async function openRowByText(
  actions: CommonActions,
  matchText: string,
  opts: { actionButton?: string } = {}
): Promise<void> {
  if (opts.actionButton) {
    await actions.aiTap(
      `表格中包含文本 "${matchText}" 的那一行,行末尾"操作"列里的"${opts.actionButton}"按钮`
    );
  } else {
    await actions.aiTap(`表格中包含文本 "${matchText}" 的那一行,点击行首主列(通常是名称/ID 链接)`);
  }
}

// ---------------------------------------------------------------------------
// 4. 弹窗 / 对话框
// ---------------------------------------------------------------------------

/**
 * 确认对话框点"确定"。常用于删除/提交等需要二次确认的操作。
 */
export async function confirmDialog(
  actions: CommonActions,
  opts: { buttonText?: string; successAssertion?: string } = {}
): Promise<void> {
  const btn = opts.buttonText || "确定";
  await actions.aiTap(`屏幕中央确认对话框底部的"${btn}"按钮`);
  if (opts.successAssertion) {
    await actions.aiAssert(opts.successAssertion);
  }
}

export async function cancelDialog(
  actions: CommonActions,
  opts: { buttonText?: string } = {}
): Promise<void> {
  const btn = opts.buttonText || "取消";
  await actions.aiTap(`屏幕中央确认对话框底部的"${btn}"按钮`);
}

// ---------------------------------------------------------------------------
// 5. 表单填充(根据"字段名 → 值"映射批量填写)
// ---------------------------------------------------------------------------

export interface FieldFill {
  /** 字段标签,例:"主机名称" */
  label: string;
  /** 要填的值 */
  value: string;
  /** 控件类型,默认 input;为 select 时走点击下拉选项语义 */
  type?: "input" | "select" | "textarea";
}

/**
 * 按"label → value"批量填写表单。
 * 适合标准 label-input 布局的新建/编辑表单。
 */
export async function fillForm(
  actions: CommonActions,
  fields: FieldFill[]
): Promise<void> {
  for (const f of fields) {
    if (f.type === "select") {
      await actions.aiTap(`表单中标签为"${f.label}"的下拉选择框`);
      await actions.aiTap(`下拉列表中的"${f.value}"选项`);
    } else {
      const desc =
        f.type === "textarea"
          ? `表单中标签为"${f.label}"的多行文本框`
          : `表单中标签为"${f.label}"的输入框`;
      await actions.aiInput(f.value, desc);
    }
  }
}

// ---------------------------------------------------------------------------
// 6. 分页
// ---------------------------------------------------------------------------

export async function goToPage(
  actions: CommonActions,
  pageNumber: number
): Promise<void> {
  await actions.aiTap(`列表底部分页栏中数字"${pageNumber}"的页码按钮`);
  if (actions.aiWaitFor) {
    await actions.aiWaitFor(`第 ${pageNumber} 页数据加载完成`, { timeoutMs: 10000 });
  }
}

export async function goToNextPage(actions: CommonActions): Promise<void> {
  await actions.aiTap("列表底部分页栏的下一页按钮(通常是 > 图标)");
}

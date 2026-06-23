import { expect } from "@playwright/test";
import { test } from "./fixture";

test("资产管理添加资产保存成功", async ({ page, aiTap, aiInput, aiAssert, aiWaitFor, aiHover }) => {
  // 已登录态;baseURL 由 config 注入
  // ⚠️ waitUntil 必须显式给 "domcontentloaded" —— 默认 "load" 会等
  // 全部资源 + load 事件,业务管理后台常驻 SSE/轮询导致 load 永不触发,45s 必挂
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1000);

  // 通过顶部资产菜单进入资产管理页面（使用原生选择器避免ai对顶部菜单的偏移）
  const assetMenu = page.getByText("资产", { exact: false }).first();
  await assetMenu.hover();
  await page.getByText("资产管理").click();
  await aiWaitFor("资产管理列表加载完成", { timeoutMs: 10000 });

  // 悬停“更多”按钮并点击添加资产
  await page.getByText("更多");
  await aiHover("更多");
  await aiWaitFor("添加资产", { timeoutMs: 10000})
  await aiTap("添加资产");
  await aiWaitFor("添加资产表单加载完成", { timeoutMs: 10000 });

  // 生成唯一的资产名称
  const randomSuffix = Date.now().toString(36) + Math.random().toString(36).substring(2, 5);
  const assetName = "测试资产" + randomSuffix;

  // 填写资产名称
  await aiInput(assetName, "资产名称输入框");

  // 选择项目下拉框第一条
  await aiTap("项目下拉框");
  await aiWaitFor("项目下拉列表出现", { timeoutMs: 5000 });
  await aiTap("项目下拉列表中的第一个选项");

  // 选择数据集下拉框第一条
  await aiTap("数据集下拉框");
  await aiWaitFor("数据集下拉列表出现", { timeoutMs: 5000 });
  await aiTap("数据集下拉列表中的第一个选项");

  // 填写IP地址
  await aiInput("172.168.12.1", "IP地址输入框");

  // 选择资产类型下拉框第一条
  await aiTap("资产类型下拉框");
  await aiWaitFor("资产类型下拉列表出现", { timeoutMs: 5000 });
  await aiTap("资产类型下拉列表中的第一个选项");

  // 选择资产等级下拉框第一条
  await aiTap("资产等级下拉框");
  await aiWaitFor("资产等级下拉列表出现", { timeoutMs: 5000 });
  await aiTap("资产等级下拉列表中的第一个选项");

  // 提交表单
  await aiTap("确定按钮");

  // 断言添加成功
  await aiAssert("显示添加成功提示或资产列表中出现新资产");
});

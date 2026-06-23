import { test, expect } from "@playwright/test";

test("资产网段添加网段-搜索-删除", async ({ page }) => {
  // 打开目标页面
  await page.goto("https://172.16.8.189/AssetManagement/AssetSegment", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1000);

  // 点击“更多”按钮，展开下拉菜单
  await page.getByRole("button", { name: " 更多" }).click();
  // 选择“添加网段”菜单项
  await page.getByRole("menuitem", { name: "添加网段" }).click();

  // 填写网段名称
  await page.getByRole("textbox", { name: "* 网段名称 :" }).click();
  await page.getByRole("textbox", { name: "* 网段名称 :" }).fill("添加网段");
  // 填写网段地址
  await page.getByRole("textbox", { name: "* 网段 :" }).click();
  await page.getByRole("textbox", { name: "* 网段 :" }).fill("19.18.17.1/24");

  // 选择网络位置
  await page.getByRole("combobox", { name: "* 网络位置 :" }).click();
  await page.getByText('内网').nth(3).click();

  // 选择数据集
  await page.getByRole("combobox", { name: "* 数据集 :" }).click();
  await page.getByRole("option").first().click();

  // 提交表单
  await page.getByRole("button", { name: "确 定" }).click();
  // 在后续确认弹窗中再次点击确定
  await page.getByRole("button", { name: "确 定" }).nth(1).click();

  // 搜索刚添加的网段
  await page.getByRole("textbox", { name: "请输入网段搜索" }).click();
  await page.getByRole("textbox", { name: "请输入网段搜索" }).fill("19.18.17.1");
  // 按回车触发搜索
  await page.keyboard.press("Enter");

  // 等待搜索结果行出现
  await expect(page.getByRole("row", { name: /19.18.17.1\/24/ })).toBeVisible({ timeout: 5000 });

  // 勾选该网段前的复选框
  await page.getByRole("row", { name: "19.18.17.1/24 添加网段 手动添加 0" }).getByLabel("", { exact: true }).check();

  // 点击“批量删除”按钮
  await page.getByRole("button", { name: "批量删除" }).click();
  // 确认删除
  await page.getByRole("button", { name: "确 定" }).click();

  // 验证删除成功
  await expect(page.getByText("删除成功")).toBeVisible({ timeout: 5000 });
});
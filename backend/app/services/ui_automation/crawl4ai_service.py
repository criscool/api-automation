"""crawl4ai 集成服务（2026-06-17 引入）

职责：
1. analyze_live_url   —— Live URL 页面分析路径,直接抓取 + 返回结构化 UiElement
2. prefetch_page_dict —— 录制前预抓,产物 page_dict 给 LLM 后处理做 selector 字典

零回归红线：
- settings.UI_CRAWL4AI_ENABLED=False 或 lazy import 失败 → 返回 None,调用方走原有 fallback
- 抓取异常(timeout/network/反爬) → 仅 warn,不抛
- 不依赖任何已有 agents/services,可被任意模块 lazy import
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from app.agents.ui_automation.schemas import (
    LocatorSuggestion,
    UiElement,
    UiElementCategory,
)
from app.settings.config import settings

_EXTRACTOR_JS = r"""
(() => {
  const out = { page_title: document.title || "", elements: [], _debug: {} };
  try {
    out._debug.body_text_len = (document.body && document.body.innerText || "").length;
    out._debug.body_html_len = (document.body && document.body.innerHTML || "").length;
    out._debug.dom_total = document.querySelectorAll("*").length;
  } catch (_) {}

  // 探针:把当前 origin 的 localStorage / sessionStorage / cookie 情况吐回来
  // 用来定位"storage_state 是没加载上 vs 加载了但服务端鉴权拒绝"
  try {
    const lsKeys = [];
    for (let i = 0; i < (localStorage && localStorage.length || 0); i++) {
      lsKeys.push(localStorage.key(i));
    }
    out._debug.runtime_origin = window.location.origin;
    out._debug.runtime_ls_count = lsKeys.length;
    out._debug.runtime_ls_keys = lsKeys.slice(0, 30);
    out._debug.runtime_cookie_str_len = (document.cookie || "").length;
    out._debug.runtime_has_password_input = document.querySelector("input[type=password]") !== null;
  } catch (_) {}

  // 原生交互 tag + ARIA role 兜底(Naive UI / Ant / Element 的按钮多是 <div role="button">)
  const selectors = [
    "button",
    "a[href]",
    "input",
    "select",
    "textarea",
    "[role='button']",
    "[role='link']",
    "[role='menuitem']",
    "[role='tab']",
    "[role='option']",
    "[role='switch']",
    "[role='checkbox']",
    "[role='radio']",
    "[role='combobox']",
    "[role='searchbox']",
    "[contenteditable='true']",
    ".ant-btn",
    ".n-button",
    ".el-button",
    ".ant-menu-item",
    ".n-menu-item",
    ".el-menu-item",
  ];
  const seen = new Set();
  const txt = (el) => (el.innerText || el.value || el.placeholder || "").trim().slice(0, 80);
  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) };
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const s = window.getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || s.opacity === "0") return false;
    if (el.getAttribute("aria-hidden") === "true") return false;
    return true;
  };
  const inferCategory = (el, tag) => {
    const role = (el.getAttribute("role") || "").toLowerCase();
    if (tag === "a" || role === "link") return "link";
    if (tag === "select" || role === "combobox" || role === "option") return "selection";
    if (role === "checkbox" || role === "radio" || role === "switch") return "selection";
    if (tag === "textarea" || role === "searchbox" || el.getAttribute("contenteditable") === "true") return "input";
    if (tag === "input") {
      const t = (el.getAttribute("type") || "text").toLowerCase();
      if (["checkbox", "radio"].includes(t)) return "selection";
      if (["submit", "button", "reset"].includes(t)) return "button";
      if (t === "file") return "special";
      return "input";
    }
    return "button";
  };
  const roleMap = { button: "button", a: "link", input: "input", select: "selection", textarea: "input" };
  for (const sel of selectors) {
    let list;
    try { list = document.querySelectorAll(sel); } catch (_) { continue; }
    for (const el of list) {
      if (!visible(el)) continue;
      const tag = el.tagName.toLowerCase();
      const text = txt(el);
      const id = el.id || "";
      const role = el.getAttribute("role") || roleMap[tag] || "";
      const aria = el.getAttribute("aria-label") || "";
      const placeholder = el.getAttribute("placeholder") || "";
      const testid = el.getAttribute("data-testid") || el.getAttribute("data-test-id") || "";
      const key = `${tag}|${id}|${text}|${aria}|${placeholder}|${testid}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.elements.push({
        tag: tag,
        id: id,
        role: role,
        text: text,
        aria_label: aria,
        placeholder: placeholder,
        testid: testid,
        type: tag === "input" ? (el.getAttribute("type") || "text") : "",
        name: el.getAttribute("name") || "",
        href: tag === "a" ? (el.getAttribute("href") || "") : "",
        category: inferCategory(el, tag),
        position: rect(el),
        classes: el.className && typeof el.className === "string" ? el.className.slice(0, 200) : "",
      });
      if (out.elements.length >= 200) break;
    }
    if (out.elements.length >= 200) break;
  }
  return JSON.stringify(out);
})();
"""


def _is_crawl4ai_enabled() -> bool:
    if not getattr(settings, "UI_CRAWL4AI_ENABLED", False):
        return False
    return True


# URL 路径里命中其中一个即判定为登录页(支持 hash 路由 #/login)
_LOGIN_URL_KEYWORDS = (
    "/login",
    "/signin",
    "/sign-in",
    "/sign_in",
    "/auth/login",
    "/passport",
    "/sso/login",
    "#/login",
    "#/signin",
    "#/auth",
)


def _detect_login_redirect(
    requested_url: str, final_url: str, payload: Dict[str, Any]
) -> tuple:
    """判断 crawl 结果是否被强制重定向到登录页(storage_state 失效)。

    返回 (是否登录页 bool, 原因短文案 str)。规则:
    1. final_url 路径(或 hash 段)命中登录关键词,且与 requested_url 路径不一致 → 强信号
    2. DOM 出现 input[type=password] → 几乎必是登录页
    任一命中即判定。
    """
    try:
        from urllib.parse import urlparse

        req_path = (urlparse(requested_url).path or "").lower()
        final_parsed = urlparse(final_url or "")
        final_path = (final_parsed.path or "").lower()
        final_hash = (final_parsed.fragment or "").lower()
        final_full = f"{final_path}#{final_hash}"
    except Exception:
        req_path = ""
        final_path = ""
        final_full = ""

    if final_path and final_path != req_path:
        for kw in _LOGIN_URL_KEYWORDS:
            if kw in final_full:
                return True, f"final_url 命中 {kw}"

    for el in payload.get("elements") or []:
        if not isinstance(el, dict):
            continue
        if (el.get("tag") or "").lower() == "input" and (el.get("type") or "").lower() == "password":
            return True, "DOM 出现 input[type=password]"

    return False, ""


async def _perform_auto_login(
    page: Any,
    login_url: str,
    username: str,
    password: str,
    timeout: int,
) -> Dict[str, Any]:
    """启发式自助登录:goto 登录页 → 定位 username/password/submit → 填入并提交。

    流程对 form 完全无知,纯靠"找 password 框,前面找文本框,后面找提交按钮"三连。
    适配 Naive UI / Ant Design / Element / 原生 form 等绝大多数后台。

    返回 {"success": bool, "reason": str, "steps": [...]} 用于 SSE 诊断。
    """
    result: Dict[str, Any] = {"success": False, "reason": "", "steps": []}

    try:
        await page.goto(login_url, wait_until="domcontentloaded", timeout=timeout * 1000)
        result["steps"].append(f"goto {login_url} OK")
    except Exception as e:
        result["reason"] = f"登录页 goto 失败: {e}"
        return result

    # 等表单 mount(SPA 登录页常见)
    try:
        await page.wait_for_selector("input[type=password]", timeout=10000, state="visible")
        result["steps"].append("password 输入框可见")
    except Exception:
        result["reason"] = "10s 内未找到 input[type=password],可能不是登录页"
        return result

    # 1) password 输入框(全页第一个可见的)
    password_loc = page.locator("input[type=password]:visible").first

    # 2) username 输入框:几种 fallback 由强到弱
    username_loc = None
    for sel in [
        "input[type=text]:visible",
        "input[type=email]:visible",
        "input[type=tel]:visible",
        "input:not([type]):visible",
        "input[type=username]:visible",
    ]:
        try:
            cand = page.locator(sel).first
            if await cand.count() > 0:
                username_loc = cand
                result["steps"].append(f"username 输入框命中 selector={sel}")
                break
        except Exception:
            continue
    if username_loc is None:
        # 兜底:取 password 输入框前面那一个 input(同 form 内最常见)
        try:
            username_loc = page.locator("input:visible").nth(0)
            result["steps"].append("username 输入框走兜底:全页第一个可见 input")
        except Exception:
            result["reason"] = "未找到 username 输入框"
            return result

    try:
        await username_loc.fill(username, timeout=5000)
        await password_loc.fill(password, timeout=5000)
        result["steps"].append("用户名/密码已填入")
    except Exception as e:
        result["reason"] = f"填表失败: {e}"
        return result

    # 3) 提交按钮:按"文案优先 → type=submit → form 末尾按钮"找
    submit_loc = None
    for sel in [
        "button:visible:has-text('登录')",
        "button:visible:has-text('登 录')",
        "button:visible:has-text('Login')",
        "button:visible:has-text('Sign in')",
        "button:visible:has-text('Sign In')",
        "[role='button']:visible:has-text('登录')",
        "button[type=submit]:visible",
        "input[type=submit]:visible",
    ]:
        try:
            cand = page.locator(sel).first
            if await cand.count() > 0:
                submit_loc = cand
                result["steps"].append(f"提交按钮命中 selector={sel}")
                break
        except Exception:
            continue

    if submit_loc is None:
        # 直接回车提交(适用于 Ant Form / 原生 form)
        try:
            await password_loc.press("Enter")
            result["steps"].append("按钮没找着,密码框按 Enter 提交")
        except Exception as e:
            result["reason"] = f"找不到登录按钮且回车失败: {e}"
            return result
    else:
        try:
            await submit_loc.click(timeout=5000)
            result["steps"].append("登录按钮已点击")
        except Exception as e:
            result["reason"] = f"登录按钮点击失败: {e}"
            return result

    # 4) 等登录完成:URL 离开登录页 或 password 框消失
    success = False
    try:
        await page.wait_for_function(
            "document.querySelector('input[type=password]') === null",
            timeout=15000,
        )
        success = True
        result["steps"].append("password 框已消失,判定登录成功")
    except Exception:
        # 兜底:看 URL 是否离开了登录页关键词
        try:
            cur = page.url.lower()
            if not any(kw in cur for kw in _LOGIN_URL_KEYWORDS):
                success = True
                result["steps"].append(f"URL 已离开登录页 → {page.url}")
        except Exception:
            pass

    if not success:
        result["reason"] = "提交后 password 框仍在 + URL 没离开登录页 → 账号密码可能错误"
        return result

    # 5) 多等一会让登录后的 token 写入 localStorage / cookie 完成
    try:
        await page.wait_for_timeout(800)
    except Exception:
        pass

    result["success"] = True
    return result


def _crawl_in_dedicated_loop(
    url: str, storage_state_path: Optional[str], timeout: int
) -> Optional[Dict[str, Any]]:
    """在独立线程内用 ProactorEventLoop + Playwright async 直接抓取。

    Why Playwright 而非 crawl4ai:
      - crawl4ai 0.8.8 处理 js_code 不 await async function,SCRAPE 0.07s 内就跑完,
        SPA 还没 mount 就抓 → 0 元素。我们其实只用它的"开浏览器 + evaluate"两件事。
      - Playwright 已是项目依赖(录制功能在用),直接用,wait 时机我们自己控,可观测可调。

    Why 独立线程 + 新 loop:
      - Windows uvicorn --reload 主循环常是 SelectorEventLoop,Playwright 子进程 spawn
        需要 ProactorEventLoop,主循环里直接 await async_playwright() 会 NotImplementedError。
        本线程独立 set Proactor + new_event_loop 完全规避。

    任何异常 → 返回 None,绝不抛。
    """
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception as exc:
        logger.warning(f"[crawl4ai] playwright import 失败,跳过: {exc}")
        return None

    # 诊断:storage_state 文件状态(诊断"为什么登录态没生效")
    # 注意:Playwright 的 storage_state 同时承载 cookies 和 origins[].localStorage,
    # 不少系统(尤其老 Vue 后台)是 sessionId 塞 localStorage 鉴权,cookies 可以为空。
    # 所以诊断里 cookies 和 origins/localStorage 要分开看,不能只看 cookies 就喊"未登录"。
    storage_state_debug: Dict[str, Any] = {
        "path": storage_state_path or "",
        "exists": False,
        "size_bytes": 0,
        "mtime_iso": "",
        "cookie_count": 0,
        "cookie_domains": [],
        "origins": [],
        "localstorage_key_count": 0,
        "auth_like_keys": [],
        "issues": [],
    }
    if storage_state_path:
        try:
            stat = os.stat(storage_state_path)
            storage_state_debug["exists"] = True
            storage_state_debug["size_bytes"] = stat.st_size
            storage_state_debug["mtime_iso"] = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)
            )
            try:
                with open(storage_state_path, "r", encoding="utf-8") as f:
                    state_json = json.load(f)
                cookies = state_json.get("cookies") or []
                origins = state_json.get("origins") or []
                storage_state_debug["cookie_count"] = len(cookies)
                domains = sorted({(c.get("domain") or "").lstrip(".") for c in cookies if c.get("domain")})
                storage_state_debug["cookie_domains"] = domains[:10]

                # 解析 origins / localStorage
                ls_total = 0
                auth_like: List[str] = []
                origin_summaries: List[Dict[str, Any]] = []
                _AUTH_KW = ("token", "session", "auth", "jwt", "userinfo", "user_info", "key")
                for o in origins:
                    if not isinstance(o, dict):
                        continue
                    o_origin = o.get("origin") or ""
                    ls_list = o.get("localStorage") or []
                    ls_keys = [
                        (item.get("name") or "")
                        for item in ls_list
                        if isinstance(item, dict)
                    ]
                    ls_total += len(ls_keys)
                    for k in ls_keys:
                        kl = k.lower()
                        if any(w in kl for w in _AUTH_KW):
                            auth_like.append(f"{o_origin}::{k}")
                    origin_summaries.append(
                        {"origin": o_origin, "ls_keys": ls_keys[:20]}
                    )
                storage_state_debug["origins"] = origin_summaries[:5]
                storage_state_debug["localstorage_key_count"] = ls_total
                storage_state_debug["auth_like_keys"] = auth_like[:10]

                # 判断登录态是否"看起来有"——cookies 或 localStorage 至少有一种鉴权痕迹
                has_any_auth = bool(cookies) or bool(auth_like)
                if not has_any_auth:
                    storage_state_debug["issues"].append(
                        "storage_state 既没有 cookie 也没有疑似鉴权的 localStorage 键(token/session/auth/...)"
                    )

                # cookie domain 匹配(只对有 cookie 的场景检查)
                try:
                    from urllib.parse import urlparse as _up
                    target_host = (_up(url).hostname or "").lower()
                    target_origin = f"{_up(url).scheme}://{_up(url).netloc}".lower()
                except Exception:
                    target_host = ""
                    target_origin = ""

                if cookies and target_host and not any(
                    target_host == d or target_host.endswith("." + d) or d.endswith("." + target_host) or d == target_host
                    for d in domains
                ):
                    storage_state_debug["issues"].append(
                        f"cookie domains {domains} 不匹配目标 host {target_host}"
                    )

                # origin 匹配(对 localStorage 鉴权场景重要)
                if origin_summaries and target_origin:
                    saved_origins_lower = {
                        (o.get("origin") or "").lower()
                        for o in origin_summaries
                        if o.get("origin")
                    }
                    if saved_origins_lower and target_origin not in saved_origins_lower:
                        storage_state_debug["issues"].append(
                            f"localStorage 是 {list(saved_origins_lower)} 录的,跟目标 {target_origin} 不一致"
                        )

                # cookie 过期粗判
                max_exp = max(
                    (float(c.get("expires") or 0) for c in cookies if c.get("expires")),
                    default=0,
                )
                if cookies and max_exp > 0 and max_exp < time.time():
                    storage_state_debug["issues"].append(
                        f"所有 cookie 都已过期(最晚 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(max_exp))})"
                    )

                # 文件年龄提醒:session 类 localStorage 没有客户端 expires,只能凭文件 mtime 提示
                age_sec = time.time() - stat.st_mtime
                if age_sec > 24 * 3600 and auth_like and not cookies:
                    storage_state_debug["issues"].append(
                        f"storage_state 文件已超过 {int(age_sec / 3600)}h 未更新,"
                        f"localStorage 类 sessionId 可能已被服务端踢下线"
                    )
            except Exception as e:
                storage_state_debug["issues"].append(f"解析 storage_state JSON 失败: {e}")
        except FileNotFoundError:
            storage_state_debug["issues"].append("文件不存在")
        except Exception as e:
            storage_state_debug["issues"].append(f"读取失败: {e}")
    else:
        storage_state_debug["issues"].append("未提供 storage_state 路径(未登录抓)")

    logger.info(f"[crawl4ai] storage_state 诊断: {storage_state_debug}")

    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception as exc:
            logger.warning(f"[crawl4ai] 设置 Proactor 策略失败: {exc}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    mount_selector = (
        "button, a[href], input, textarea, select, "
        "[role='button'], [role='link'], [role='menuitem'], [role='tab'], "
        ".ant-btn, .n-button, .el-button, .ant-menu-item, .n-menu-item"
    )

    async def _do_crawl() -> Optional[Dict[str, Any]]:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context_kwargs: Dict[str, Any] = {
                    "viewport": {"width": 1280, "height": 800},
                    "ignore_https_errors": True,
                }
                if storage_state_path and os.path.isfile(storage_state_path):
                    context_kwargs["storage_state"] = storage_state_path
                context = await browser.new_context(**context_kwargs)

                # 主动注入 localStorage(双保险):Playwright 的 storage_state 对 localStorage 是
                # "延迟+被动"注入,业务 JS 在 navigation 早期就读 localStorage 时拿不到。
                # 用 add_init_script 在每个 page 加载前手工写,origin 匹配才注入。
                injected_origins: List[str] = []
                if storage_state_path and os.path.isfile(storage_state_path):
                    try:
                        with open(storage_state_path, "r", encoding="utf-8") as f:
                            _ss = json.load(f)
                        _origins_in_file = _ss.get("origins") or []
                        logger.info(
                            f"[crawl4ai] add_init_script 准备注入: origins={len(_origins_in_file)} 个"
                        )
                        for o in _origins_in_file:
                            o_origin = (o.get("origin") or "").strip()
                            ls_items = o.get("localStorage") or []
                            logger.info(
                                f"[crawl4ai] 处理 origin={o_origin!r} ls_items={len(ls_items)}"
                            )
                            if not o_origin or not ls_items:
                                continue
                            setters = ";".join(
                                f"localStorage.setItem({json.dumps(i['name'])}, {json.dumps(i['value'])})"
                                for i in ls_items
                                if isinstance(i, dict) and "name" in i and "value" in i
                            )
                            if not setters:
                                continue
                            init_js = (
                                f"(() => {{ try {{ if (window.location.origin === {json.dumps(o_origin)}) "
                                f"{{ {setters} }} }} catch(e) {{}} }})();"
                            )
                            await context.add_init_script(init_js)
                            injected_origins.append(o_origin)
                            logger.info(f"[crawl4ai] add_init_script 已注入 origin={o_origin}")
                    except Exception as exc:
                        logger.warning(f"[crawl4ai] add_init_script 注入 localStorage 失败: {exc}", exc_info=True)

                page = await context.new_page()
                mount_wait_ms_outer = 0
                mount_timed_out_outer = False
                ls_after_goto_count_outer = -1
                ls_after_goto_keys_outer: List[str] = []
                final_url = ""
                raw: Any = None

                async def _grab(target: str) -> tuple:
                    """goto target → wait mount → evaluate → 返回 (raw, final_url, debug)"""
                    nonlocal mount_wait_ms_outer, mount_timed_out_outer
                    nonlocal ls_after_goto_count_outer, ls_after_goto_keys_outer

                    await page.goto(target, wait_until="domcontentloaded", timeout=timeout * 1000)

                    # Phase 0: navigation 完成立即探测 localStorage
                    try:
                        _ls_after = await page.evaluate(
                            "() => { try { const ks=[]; for(let i=0;i<localStorage.length;i++) ks.push(localStorage.key(i)); return ks; } catch(e) { return []; } }"
                        )
                        if isinstance(_ls_after, list):
                            ls_after_goto_keys_outer = [str(k) for k in _ls_after][:30]
                            ls_after_goto_count_outer = len(_ls_after)
                    except Exception:
                        pass

                    # Phase 1: SPA mount poll
                    _mount_start = time.time()
                    _mount_timed_out = False
                    try:
                        await page.wait_for_function(
                            f"document.querySelectorAll({json.dumps(mount_selector)}).length > 0",
                            timeout=12000,
                        )
                    except Exception:
                        _mount_timed_out = True
                    mount_wait_ms_outer = int((time.time() - _mount_start) * 1000)
                    mount_timed_out_outer = _mount_timed_out

                    await page.wait_for_timeout(500)
                    _raw = await page.evaluate(_EXTRACTOR_JS)
                    return _raw, page.url

                # ============================
                # 第一次抓:用现有 storage_state
                # ============================
                auto_login_attempted = False
                auto_login_result: Dict[str, Any] = {}
                try:
                    raw, final_url = await _grab(url)

                    # 解析 raw 判定登录态
                    def _parse_raw(r: Any) -> Optional[Dict[str, Any]]:
                        if isinstance(r, (bytes, bytearray)):
                            r = r.decode("utf-8", errors="ignore")
                        if isinstance(r, dict):
                            return r
                        if isinstance(r, str):
                            try:
                                return json.loads(r)
                            except Exception:
                                logger.warning(f"[crawl4ai] evaluate 返回非 JSON,前 200: {r[:200]!r}")
                                return None
                        return None

                    payload_try1 = _parse_raw(raw)
                    login_required_try1 = False
                    if isinstance(payload_try1, dict):
                        login_required_try1, _ = _detect_login_redirect(url, page.url, payload_try1)

                    # ============================
                    # 第二次抓:登录后重抓
                    # 触发条件:第一次判定登录失效 + .env 配齐了登录三件套
                    # ============================
                    _login_url_cfg = (getattr(settings, "UI_LOGIN_URL", "") or "").strip()
                    _login_user_cfg = (getattr(settings, "UI_LOGIN_USERNAME", "") or "").strip()
                    _login_pwd_cfg = (getattr(settings, "UI_LOGIN_PASSWORD", "") or "").strip()
                    can_auto_login = bool(_login_url_cfg and _login_user_cfg and _login_pwd_cfg)

                    if login_required_try1 and can_auto_login:
                        auto_login_attempted = True
                        logger.info(
                            f"[crawl4ai] 第一次抓判定登录失效,自动登录 login_url={_login_url_cfg}"
                        )
                        auto_login_result = await _perform_auto_login(
                            page=page,
                            login_url=_login_url_cfg,
                            username=_login_user_cfg,
                            password=_login_pwd_cfg,
                            timeout=timeout,
                        )
                        logger.info(f"[crawl4ai] 自动登录结果: {auto_login_result}")

                        if auto_login_result.get("success") and storage_state_path:
                            # 登录成功 → 把当前 storage_state 落盘(下次复用)
                            try:
                                os.makedirs(os.path.dirname(storage_state_path), exist_ok=True)
                                await context.storage_state(path=storage_state_path)
                                logger.info(f"[crawl4ai] storage_state 已写盘: {storage_state_path}")
                                auto_login_result["storage_state_saved"] = True
                            except Exception as e:
                                logger.warning(f"[crawl4ai] storage_state 写盘失败: {e}")
                                auto_login_result["storage_state_saved"] = False
                                auto_login_result["storage_state_save_error"] = str(e)

                        if auto_login_result.get("success"):
                            # 重抓目标 URL
                            try:
                                raw, final_url = await _grab(url)
                                logger.info(f"[crawl4ai] 登录后重抓完成 final={final_url}")
                            except Exception as e:
                                logger.warning(f"[crawl4ai] 登录后重抓失败: {e}")
                    elif login_required_try1 and not can_auto_login:
                        logger.warning(
                            "[crawl4ai] 第一次抓判定登录失效,但 UI_LOGIN_URL/USERNAME/PASSWORD "
                            "未在 .env 配齐,跳过自动登录"
                        )

                    final_url = page.url
                finally:
                    try:
                        await context.close()
                    except Exception:
                        pass
                    try:
                        await browser.close()
                    except Exception:
                        pass

                # 解析最终 raw
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", errors="ignore")
                if isinstance(raw, dict):
                    payload = raw
                elif isinstance(raw, str):
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        logger.warning(f"[crawl4ai] evaluate 返回非 JSON 字符串,前 200 字: {raw[:200]!r}")
                        return None
                else:
                    logger.warning(f"[crawl4ai] evaluate 返回未知类型 {type(raw)}")
                    return None
                if not isinstance(payload, dict):
                    return None

                payload.setdefault("_debug", {})
                payload["_debug"]["mount_wait_ms"] = mount_wait_ms_outer
                payload["_debug"]["mount_timed_out"] = mount_timed_out_outer
                payload["_debug"]["location_href"] = final_url
                payload["_debug"]["storage_state"] = storage_state_debug
                payload["_debug"]["ls_after_goto_count"] = ls_after_goto_count_outer
                payload["_debug"]["ls_after_goto_keys"] = ls_after_goto_keys_outer
                payload["_debug"]["init_script_injected_origins"] = injected_origins
                payload["_debug"]["auto_login_attempted"] = auto_login_attempted
                payload["_debug"]["auto_login_result"] = auto_login_result

                # 登录态判定(用最终一次抓的结果)
                payload["requested_url"] = url
                payload["final_url"] = final_url
                login_required, reason = _detect_login_redirect(url, final_url, payload)
                payload["login_required"] = login_required
                payload["login_reason"] = reason
                payload["storage_state_debug"] = storage_state_debug
                payload["auto_login_attempted"] = auto_login_attempted
                payload["auto_login_result"] = auto_login_result
                if login_required:
                    logger.warning(
                        f"[crawl4ai] 抓完仍判定登录失效 url={url} → final={final_url} 原因={reason} "
                        f"auto_login={auto_login_result}"
                    )
                return payload
        except Exception as exc:
            logger.warning(f"[crawl4ai] playwright 抓取异常 url={url}: {exc}", exc_info=True)
            return None

    try:
        return loop.run_until_complete(asyncio.wait_for(_do_crawl(), timeout=timeout + 10))
    except asyncio.TimeoutError:
        logger.warning(f"[crawl4ai] 总超时 {timeout + 10}s url={url}")
        return None
    except Exception as exc:
        logger.warning(f"[crawl4ai] 执行异常 url={url}: {exc}")
        return None
    finally:
        try:
            loop.close()
        except Exception:
            pass


async def _run_crawl(
    url: str, storage_state_path: Optional[str], timeout: int
) -> Optional[Dict[str, Any]]:
    """异步入口:把 crawl4ai 丢到独立线程的 ProactorEventLoop 跑。

    走 asyncio.to_thread 与主请求循环完全解耦,规避 Windows 上 uvicorn --reload
    场景下主循环可能是 SelectorEventLoop 导致 Playwright subprocess_exec 抛 NotImplementedError。
    """
    return await asyncio.to_thread(
        _crawl_in_dedicated_loop, url, storage_state_path, timeout
    )


def _payload_to_ui_elements(payload: Dict[str, Any]) -> List[UiElement]:
    raw_elements = payload.get("elements") or []
    out: List[UiElement] = []
    for idx, raw in enumerate(raw_elements):
        if not isinstance(raw, dict):
            continue
        tag = (raw.get("tag") or "").lower()
        text = (raw.get("text") or "").strip()
        aria = (raw.get("aria_label") or "").strip()
        placeholder = (raw.get("placeholder") or "").strip()
        testid = (raw.get("testid") or "").strip()
        elem_id = (raw.get("id") or "").strip()
        role = (raw.get("role") or "").strip()
        category_str = (raw.get("category") or "button").lower()
        try:
            category = UiElementCategory(category_str)
        except ValueError:
            category = UiElementCategory.BUTTON

        display_name = text or aria or placeholder or elem_id or f"{tag}_{idx}"

        locator_suggestions: List[LocatorSuggestion] = []
        if elem_id and not _looks_like_dynamic_id(elem_id):
            locator_suggestions.append(
                LocatorSuggestion(strategy="css", expression=f"#{elem_id}", confidence=0.95)
            )
        if testid:
            locator_suggestions.append(
                LocatorSuggestion(strategy="test_id", expression=testid, confidence=0.9)
            )
        if text and len(text) <= 30:
            locator_suggestions.append(
                LocatorSuggestion(strategy="text", expression=text, confidence=0.85)
            )
        if role and text:
            locator_suggestions.append(
                LocatorSuggestion(
                    strategy="role", expression=f"{role}[name='{text}']", confidence=0.8
                )
            )
        if aria:
            locator_suggestions.append(
                LocatorSuggestion(strategy="css", expression=f"[aria-label='{aria}']", confidence=0.75)
            )
        if placeholder:
            locator_suggestions.append(
                LocatorSuggestion(strategy="css", expression=f"[placeholder='{placeholder}']", confidence=0.75)
            )

        if not locator_suggestions:
            continue

        element_id = elem_id or testid or f"el_{tag}_{idx}"

        position_raw = raw.get("position") or {}
        position = None
        if isinstance(position_raw, dict):
            from app.agents.ui_automation.schemas import ElementPosition

            position = ElementPosition(
                x=int(position_raw.get("x") or 0),
                y=int(position_raw.get("y") or 0),
                width=int(position_raw.get("width") or 0),
                height=int(position_raw.get("height") or 0),
            )

        description_parts = []
        if text:
            description_parts.append(f"文案'{text}'")
        if placeholder:
            description_parts.append(f"占位符'{placeholder}'")
        if aria:
            description_parts.append(f"aria-label '{aria}'")
        description_parts.append(f"标签 <{tag}>")
        description = "、".join(description_parts) + "(crawl4ai 抓取自真实 DOM)"

        out.append(
            UiElement(
                element_id=element_id,
                name=display_name,
                category=category,
                element_type=raw.get("type") or tag,
                description=description,
                text_content=text or None,
                position=position,
                visual_features={},
                functionality="",
                interaction_state="normal",
                testability=0.95,
                locator_suggestions=locator_suggestions,
                confidence_score=0.95,
            )
        )
    return out


def _looks_like_dynamic_id(elem_id: str) -> bool:
    """组件库生成的 hash id 不稳定,排除掉"""
    if not elem_id:
        return True
    lower = elem_id.lower()
    if lower.startswith(("n-", "el-", "ant-", "__bvid__", "rc_")):
        return True
    if any(c.isdigit() for c in elem_id[-3:]):
        return True
    return False


async def analyze_live_url(
    url: str,
    storage_state_path: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Live URL 页面分析入口。

    返回值 {"page_title", "elements": List[UiElement], "raw": <原始 payload>}
    失败返回 None。
    """
    if not _is_crawl4ai_enabled():
        logger.info("[crawl4ai] UI_CRAWL4AI_ENABLED=False, 跳过")
        return None
    if not url or not url.strip():
        return None

    effective_timeout = timeout or getattr(settings, "UI_CRAWL4AI_TIMEOUT", 60)
    start = time.time()
    payload = await _run_crawl(url.strip(), storage_state_path, effective_timeout)
    elapsed_ms = int((time.time() - start) * 1000)
    if payload is None:
        logger.warning(f"[crawl4ai] analyze_live_url 失败 url={url} elapsed={elapsed_ms}ms")
        return None
    elements = _payload_to_ui_elements(payload)
    login_required = bool(payload.get("login_required"))
    login_reason = payload.get("login_reason") or ""
    final_url = payload.get("final_url") or ""
    debug = payload.get("_debug") or {}
    storage_state_debug = payload.get("storage_state_debug") or {}
    logger.info(
        f"[crawl4ai] analyze_live_url 成功 url={url} → final={final_url} "
        f"元素 {len(elements)} login_required={login_required} elapsed={elapsed_ms}ms "
        f"debug={debug}"
    )
    return {
        "page_title": payload.get("page_title", ""),
        "elements": elements,
        "raw": payload,
        "login_required": login_required,
        "login_reason": login_reason,
        "final_url": final_url,
        "debug": debug,
        "storage_state_debug": storage_state_debug,
    }


async def prefetch_page_dict(
    url: str,
    storage_state_path: Optional[str] = None,
    timeout: Optional[int] = None,
    persist_dir: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """录制前预抓 page_dict,产物落盘 + 返回简化字典。

    返回值 {"page_title", "elements": List[Dict], "file_path": str | None}
    失败返回 None,**不可阻塞录制主流程**。
    """
    if not _is_crawl4ai_enabled():
        return None
    if not url or not url.strip():
        return None

    effective_timeout = timeout or getattr(settings, "UI_CRAWL4AI_TIMEOUT", 60)
    payload = await _run_crawl(url.strip(), storage_state_path, effective_timeout)
    if payload is None:
        return None

    elements_for_llm: List[Dict[str, Any]] = []
    for raw in payload.get("elements", []) or []:
        if not isinstance(raw, dict):
            continue
        elements_for_llm.append(
            {
                "tag": raw.get("tag"),
                "id": raw.get("id"),
                "role": raw.get("role"),
                "text": raw.get("text"),
                "aria_label": raw.get("aria_label"),
                "placeholder": raw.get("placeholder"),
                "testid": raw.get("testid"),
                "type": raw.get("type"),
                "name": raw.get("name"),
            }
        )

    out: Dict[str, Any] = {
        "page_title": payload.get("page_title", ""),
        "elements": elements_for_llm,
        "file_path": None,
        "login_required": bool(payload.get("login_required")),
        "final_url": payload.get("final_url") or "",
    }

    target_dir = persist_dir or getattr(settings, "UI_CRAWL4AI_PAGE_DICT_DIR", None)
    if target_dir:
        try:
            os.makedirs(target_dir, exist_ok=True)
            fname_stem = session_id or f"prefetch_{int(time.time())}"
            file_path = os.path.join(target_dir, f"{fname_stem}.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            out["file_path"] = file_path
        except Exception as exc:
            logger.warning(f"[crawl4ai] page_dict 落盘失败 dir={target_dir}: {exc}")

    return out


__all__ = ["analyze_live_url", "prefetch_page_dict"]

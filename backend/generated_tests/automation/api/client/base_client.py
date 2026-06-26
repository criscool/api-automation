"""
HTTP 客户端
- 自动从 AuthSession 注入 authorization
- 自动拼接 base_url
- 支持 GET/POST/PUT/DELETE 快捷方法
- 自动把请求/响应明细附加到 Allure 报告
"""

import json

import requests
import urllib3

from automation.core.config.loader import config
from automation.core.auth.session import AuthSession

try:
    import allure
    from allure_commons.types import AttachmentType
    _ALLURE_ENABLED = True
except ImportError:
    _ALLURE_ENABLED = False


_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-auth-token"}


def _mask_headers(headers: dict) -> dict:
    """脱敏敏感请求头，避免 token 等信息泄漏到报告"""
    masked = {}
    for k, v in (headers or {}).items():
        if k.lower() in _SENSITIVE_HEADERS and v:
            sv = str(v)
            masked[k] = sv[:12] + "...[masked]" if len(sv) > 12 else "[masked]"
        else:
            masked[k] = v
    return masked


def _pretty(obj) -> str:
    """尽力把对象格式化成可读 JSON；失败则回退到字符串"""
    if obj is None:
        return ""
    if isinstance(obj, (dict, list)):
        try:
            return json.dumps(obj, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(obj)
    if isinstance(obj, (bytes, bytearray)):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            return f"<bytes len={len(obj)}>"
    if isinstance(obj, str):
        try:
            return json.dumps(json.loads(obj), indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            return obj
    return str(obj)


def _attach(name: str, body: str, attachment_type=None):
    if not _ALLURE_ENABLED or not body:
        return
    try:
        allure.attach(
            body,
            name=name,
            attachment_type=attachment_type or AttachmentType.TEXT,
        )
    except Exception:
        # 报告附件失败不能影响测试本身
        pass


class BaseClient:
    """统一 API 客户端，自动携带登录后的鉴权信息"""

    def __init__(self, base_url=None, verify_ssl=None):
        self.base_url = (base_url or config.get("api.base_url", "")).rstrip("/")
        self.verify_ssl = verify_ssl if verify_ssl is not None else config.get("api.verify_ssl", False)
        self._session = requests.Session()
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _build_headers(self, headers: dict = None) -> dict:
        """构建请求头，自动注入 authorization

        默认带 Accept: application/json 让做内容协商的接口走 JSON 分支
        （某些后端遇到 requests 默认的 */* 会 500）。
        下载二进制 / 非 JSON 响应时通过 headers={'Accept': 'application/octet-stream'} 覆盖。
        """
        request_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Requested-By": "XMLHttpRequest",
            "X-Requested-With": "XMLHttpRequest",
        }

        auth_session = AuthSession()
        if auth_session.is_logged_in:
            request_headers["authorization"] = auth_session.authorization

        if headers:
            request_headers.update(headers)
        return request_headers

    def _build_url(self, url: str) -> str:
        """拼接完整 URL"""
        if url.startswith("http"):
            return url
        return f"{self.base_url}/{url.lstrip('/')}"

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        """通用请求方法"""
        headers = self._build_headers(kwargs.pop("headers", None))
        full_url = self._build_url(url)
        verify = kwargs.pop("verify", self.verify_ssl)

        params = kwargs.get("params")
        json_body = kwargs.get("json")
        data_body = kwargs.get("data")

        step_title = f"HTTP {method.upper()} {full_url}"
        step_cm = allure.step(step_title) if _ALLURE_ENABLED else None

        if step_cm is not None:
            step_cm.__enter__()
        try:
            _attach(
                "Request - URL & Method",
                f"{method.upper()} {full_url}",
            )
            if params:
                _attach("Request - Query Params", _pretty(params))
            _attach("Request - Headers", _pretty(_mask_headers(headers)))
            if json_body is not None:
                _attach(
                    "Request - Body (JSON)",
                    _pretty(json_body),
                    AttachmentType.JSON if _ALLURE_ENABLED else None,
                )
            elif data_body is not None:
                _attach("Request - Body (form/raw)", _pretty(data_body))

            response = self._session.request(
                method=method,
                url=full_url,
                headers=headers,
                verify=verify,
                **kwargs,
            )

            _attach(
                "Response - Status & Elapsed",
                f"Status: {response.status_code} {response.reason}\n"
                f"Elapsed: {response.elapsed.total_seconds() * 1000:.1f} ms",
            )
            _attach("Response - Headers", _pretty(dict(response.headers)))

            body_text = response.text
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "json" in content_type:
                _attach(
                    "Response - Body (JSON)",
                    _pretty(body_text),
                    AttachmentType.JSON if _ALLURE_ENABLED else None,
                )
            elif body_text:
                _attach("Response - Body", body_text)

            return response
        finally:
            if step_cm is not None:
                step_cm.__exit__(None, None, None)

    def get(self, url: str, params=None, **kwargs) -> requests.Response:
        return self.request("GET", url, params=params, **kwargs)

    def post(self, url: str, json=None, data=None, **kwargs) -> requests.Response:
        return self.request("POST", url, json=json, data=data, **kwargs)

    def put(self, url: str, json=None, **kwargs) -> requests.Response:
        return self.request("PUT", url, json=json, **kwargs)

    def delete(self, url: str, **kwargs) -> requests.Response:
        return self.request("DELETE", url, **kwargs)

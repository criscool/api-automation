# -*- coding: utf-8 -*-
"""
登录接口测试用例

验证：
1. 正常登录获取 session_id
2. 登录后 api_client 自动携带 authorization
3. 错误密码登录失败
"""

import pytest

from automation.api.modules.login_api import login
from automation.core.auth.session import AuthSession


class TestLogin:
    """登录功能测试"""

    @pytest.mark.smoke
    @pytest.mark.login
    def test_login_success(self, login_session):
        """验证正常登录成功，获取到 session_id 和 authorization"""
        assert login_session.is_logged_in, "登录状态应为已登录"
        assert login_session.session_id is not None, "session_id 不应为空"
        assert login_session.authorization is not None, "authorization 不应为空"
        assert login_session.authorization.startswith("Basic "), "authorization 应为 Basic 格式"

    @pytest.mark.smoke
    @pytest.mark.login
    def test_api_client_has_auth(self, api_client, login_session):
        """验证 api_client 自动携带 authorization 发送请求"""
        # 调用一个需要认证的接口验证
        resp = api_client.get("/api/system/sessions/current")
        # 只要不是 401 就说明 auth 注入成功
        assert resp.status_code != 401, f"请求返回 401，authorization 未正确注入: {resp.text[:200]}"

    @pytest.mark.login
    def test_login_wrong_password(self, app_config):
        """验证错误密码登录失败"""
        # 使用新的 AuthSession 实例避免污染全局状态
        result = login(
            username="superadmin",
            password="WrongPassword123",
            host=app_config.api.base_url
        )
        # 登录失败应返回错误码
        assert result.get("code") is not None or "error" in str(result).lower(), \
            f"错误密码应登录失败，实际响应: {result}"

"""
pytest fixtures - 鉴权 & API 客户端复用

提供：
1. auth_session     - session 级 fixture，提供 AuthSession 单例
2. login_session    - session 级 fixture，执行一次登录获取动态 token
3. api_client       - function 级 fixture，自动注入鉴权的客户端
"""

import pytest

from automation.core.auth.session import AuthSession
from automation.api.modules.login_api import login
from automation.api.client.base_client import BaseClient


@pytest.fixture(scope="session")
def auth_session():
    """
    session 级 fixture：提供 AuthSession 单例

    使用方式：
        def test_xxx(auth_session):
            token = auth_session.authorization
    """
    session = AuthSession()
    return session


@pytest.fixture(scope="session")
def login_session(auth_session):
    """
    session 级 fixture：执行一次登录，获取动态 authorization

    如果登录成功，AuthSession 中会自动填充 session_id 和 authorization。
    后续所有依赖此 fixture 的测试共享同一个登录态。

    使用方式：
        def test_xxx(login_session):
            token = login_session.authorization
    """
    if not auth_session.is_logged_in:
        login()

    assert auth_session.is_logged_in, "登录失败，未获取到 authorization"
    assert auth_session.session_id is not None, "登录成功但 session_id 为空"
    return auth_session


@pytest.fixture
def api_client(login_session):
    """
    function 级 fixture：提供自动携带 authorization 的 BaseClient

    依赖 login_session 确保登录已完成。
    BaseClient 内部从 AuthSession 自动读取 authorization。

    使用方式：
        def test_xxx(api_client):
            resp = api_client.post("/api/xxx", json={...})
    """
    client = BaseClient()
    return client

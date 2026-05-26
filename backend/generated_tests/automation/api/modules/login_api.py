"""
登录 API 封装

职责：
1. 接收用户名、密码、主机地址
2. 使用 AES 加密用户名和密码
3. 调用 POST /api/system/sessions
4. 返回登录响应
"""

import re

import requests
import urllib3

from automation.core.config.loader import config
from automation.core.auth.crypto import aes_encrypt
from automation.core.auth.session import AuthSession

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def login(username: str = None, password: str = None, host: str = None) -> dict:
    """
    执行登录，返回完整响应 JSON

    参数优先级：显式传入 > AuthSession credentials > config 默认值
    """
    session = AuthSession()
    creds = session.get_credentials()

    final_username = username or creds.get("username") or config.get("auth.username", "superadmin")
    final_password = password or creds.get("password") or config.get("auth.password", "")
    final_host = host or creds.get("host") or config.get("api.base_url", "")

    # 提取纯 IP/域名
    host_match = re.match(r"https?://([^/]+)", final_host)
    host_ip = host_match.group(1) if host_match else final_host

    # 加密用户名和密码
    encrypted_username = aes_encrypt(final_username)
    encrypted_password = aes_encrypt(final_password)

    # 构建请求
    payload = {
        "host": host_ip,
        "username": encrypted_username,
        "password": encrypted_password,
    }

    login_path = config.get("auth.login_path", "/api/system/sessions")
    login_url = f"{final_host}{login_path}"
    headers = {
        "Content-Type": "application/json",
        "X-Requested-By": "XMLHttpRequest",
    }

    resp = requests.post(login_url, json=payload, headers=headers, verify=False, timeout=30)
    resp.raise_for_status()
    resp_json = resp.json()

    # 如果有错误码，直接返回（登录失败）
    if resp_json.get("code"):
        return resp_json

    # 登录成功，提取 session_id 并生成 authorization
    session.login_from_response(resp_json)
    return resp_json

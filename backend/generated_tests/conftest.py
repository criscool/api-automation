# -*- coding: utf-8 -*-
"""
全局 conftest.py

职责：
1. 在 pytest 启动时加载配置
2. 注册 fixture 插件
3. 配置日志系统
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

# 确保 generated_tests/ 在 sys.path 中，以便 import automation.xxx
sys.path.insert(0, str(Path(__file__).resolve().parent))

from automation.core.config.loader import config as app_cfg
from automation.core.utils.path import get_automation_root, get_logs_dir, get_testdata_dir, ensure_dir
from automation.api.modules.login_api import login as _login
from automation.core.auth.session import AuthSession


# ==================== 注册外部 fixture 模块 ====================
pytest_plugins = [
    "automation.core.fixtures.api_fixtures",
]


# ==================== pytest 钩子 ====================


def pytest_addoption(parser):
    """添加自定义命令行参数"""
    parser.addoption(
        "--env",
        action="store",
        default=os.environ.get("AUTOMATION_ENV", "test"),
        help="指定运行环境: test, staging, prod (默认: test)",
    )


def pytest_configure(config):
    """pytest 启动时的配置钩子"""
    # 1. 加载框架配置
    env = config.getoption("--env", default="test")
    app_cfg.load(env=env)

    # 2. 配置日志
    log_dir = get_logs_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = log_dir / f"automation_{timestamp}.log"

    config.option.log_file = str(log_file)
    config.option.log_file_level = app_cfg.get("logging.file_level", "DEBUG")
    config.option.log_file_format = app_cfg.get(
        "logging.format", "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )
    config.option.log_file_date_format = "%Y-%m-%d %H:%M:%S"

    # 3. 配置 Allure
    allure_results = get_automation_root().parent / app_cfg.get(
        "allure.results_dir", "reports/allure-results"
    )
    ensure_dir(allure_results)

    # 4. 输出启动信息
    print(f"\n{'=' * 60}")
    print(f"  Automation Framework")
    print(f"  Environment: {app_cfg.env}")
    print(f"  Base URL:    {app_cfg.api.base_url}")
    print(f"  Log File:    {log_file}")
    print(f"{'=' * 60}\n")


def pytest_sessionfinish(session, exitstatus):
    """测试结束后清理旧日志"""
    max_files = app_cfg.get("logging.max_files", 7)
    log_dir = get_logs_dir()
    log_files = sorted(
        log_dir.glob("automation_*.log"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for old_file in log_files[max_files:]:
        old_file.unlink(missing_ok=True)


# ==================== 全局 Fixtures ====================


@pytest.fixture(scope="session")
def app_config():
    """提供配置对象给测试用例"""
    return app_cfg


@pytest.fixture
def logger(request):
    """为每个测试提供独立的 logger"""
    test_name = request.node.name
    test_logger = logging.getLogger(f"automation.{test_name}")
    test_logger.setLevel(logging.DEBUG)

    if not test_logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(f"[{test_name}] %(levelname)s: %(message)s")
        handler.setFormatter(formatter)
        test_logger.addHandler(handler)

    return test_logger


# ==================== YAML 测试数据加载 ====================


def load_test_data(test_key: str, file_path: str = None) -> list:
    """
    从 YAML 测试数据文件中加载指定 key 的测试数据

    :param test_key: YAML 中的顶层 key
    :param file_path: YAML 文件路径，默认使用 testdata/api_test_data.yml
    :return: 可用于 parametrize 的列表
    """
    import yaml

    if file_path is None:
        file_path = str(get_testdata_dir() / "api_test_data.yml")

    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    cases = data.get(test_key, [])
    if not cases:
        raise ValueError(f"YAML 文件中未找到测试数据 key: {test_key}")
    return cases

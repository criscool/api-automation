# -*- coding: utf-8 -*-
"""
路径工具模块

职责：
- 提供跨平台的路径解析
- 所有路径基于 generated_tests/ 根目录动态计算
"""

from pathlib import Path


def get_automation_root() -> Path:
    """获取 automation 框架根目录（generated_tests/automation/）"""
    return Path(__file__).resolve().parent.parent.parent


def get_project_root() -> Path:
    """获取项目根目录（generated_tests/）"""
    return get_automation_root().parent


def get_config_dir() -> Path:
    """获取配置目录"""
    return get_automation_root() / "core" / "config"


def get_testdata_dir() -> Path:
    """获取测试数据目录"""
    return get_project_root() / "testdata"


def get_reports_dir() -> Path:
    """获取报告输出目录"""
    reports = get_project_root() / "reports"
    reports.mkdir(exist_ok=True)
    return reports


def get_logs_dir() -> Path:
    """获取日志目录"""
    logs = get_project_root() / "logs"
    logs.mkdir(exist_ok=True)
    return logs


def ensure_dir(path: Path) -> Path:
    """确保目录存在，不存在则创建"""
    path.mkdir(parents=True, exist_ok=True)
    return path

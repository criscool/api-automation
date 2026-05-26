# -*- coding: utf-8 -*-
"""
配置加载引擎

加载优先级（后者覆盖前者）：
  settings.yaml < env/{name}.yaml < 环境变量（AUTOMATION_ 前缀）
"""

import os
import re
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
    _yaml_loader = "pyyaml"
except ImportError:
    _yaml_loader = "builtin"


def _parse_yaml_file(file_path: Path) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    if _yaml_loader == "pyyaml":
        import yaml
        data = yaml.safe_load(content)
    else:
        data = _simple_yaml_parse(content)

    return data if isinstance(data, dict) else {}


def _simple_yaml_parse(content: str) -> dict:
    """极简 YAML 解析器"""
    result = {}
    stack = [(result, -1)]

    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        while len(stack) > 1 and indent <= stack[-1][1]:
            stack.pop()

        current_dict = stack[-1][0]

        if stripped.startswith("- "):
            value = _parse_value(stripped[2:].strip())
            parent = stack[-1][0]
            if isinstance(parent, dict):
                last_key = list(parent.keys())[-1] if parent else None
                if last_key and isinstance(parent[last_key], list):
                    parent[last_key].append(value)
                elif last_key and parent[last_key] is None:
                    parent[last_key] = [value]
            elif isinstance(parent, list):
                parent.append(value)
            continue

        match = re.match(r'^([^:]+?):\s*(.*)', stripped)
        if match:
            key = match.group(1).strip()
            value_str = match.group(2).strip()

            if value_str == "" or value_str.startswith("#"):
                current_dict[key] = {}
                stack.append((current_dict[key], indent))
            elif value_str == "[]":
                current_dict[key] = []
            else:
                current_dict[key] = _parse_value(value_str)

    return result


def _parse_value(value_str: str) -> Any:
    if "  #" in value_str:
        value_str = value_str[:value_str.index("  #")].strip()

    if (value_str.startswith('"') and value_str.endswith('"')) or \
       (value_str.startswith("'") and value_str.endswith("'")):
        return value_str[1:-1]

    if value_str.lower() in ("true", "yes", "on"):
        return True
    if value_str.lower() in ("false", "no", "off"):
        return False
    if value_str.lower() in ("null", "~", ""):
        return None

    try:
        if "." in value_str:
            return float(value_str)
        return int(value_str)
    except ValueError:
        pass

    return value_str


class Config:
    """配置管理器"""

    def __init__(self):
        self._data: dict = {}
        self._loaded = False

    def load(self, env: Optional[str] = None) -> "Config":
        config_dir = Path(__file__).parent

        settings_file = config_dir / "settings.yaml"
        if settings_file.exists():
            self._data = _parse_yaml_file(settings_file)

        if env is None:
            env = os.environ.get("AUTOMATION_ENV", self._data.get("env", "test"))
        self._data["env"] = env

        env_file = config_dir / "env" / f"{env}.yaml"
        if env_file.exists():
            env_data = _parse_yaml_file(env_file)
            self._data = self._deep_merge(self._data, env_data)

        self._apply_env_overrides()
        self._loaded = True
        return self

    def get(self, key_path: str, default: Any = None) -> Any:
        keys = key_path.split(".")
        value = self._data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, key_path: str, value: Any) -> None:
        keys = key_path.split(".")
        data = self._data
        for key in keys[:-1]:
            if key not in data or not isinstance(data[key], dict):
                data[key] = {}
            data = data[key]
        data[keys[-1]] = value

    @property
    def env(self) -> str:
        return self._data.get("env", "test")

    @property
    def api(self) -> "ConfigSection":
        return ConfigSection(self._data.get("api", {}))

    @property
    def auth(self) -> "ConfigSection":
        return ConfigSection(self._data.get("auth", {}))

    @property
    def headers(self) -> "ConfigSection":
        return ConfigSection(self._data.get("headers", {}))

    @property
    def allure(self) -> "ConfigSection":
        return ConfigSection(self._data.get("allure", {}))

    @property
    def logging(self) -> "ConfigSection":
        return ConfigSection(self._data.get("logging", {}))

    def to_dict(self) -> dict:
        return self._data.copy()

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = Config._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _apply_env_overrides(self) -> None:
        prefix = "AUTOMATION_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                parts = key[len(prefix):].lower().split("__")
                config_path = ".".join(parts)
                self.set(config_path, value)

    def __repr__(self) -> str:
        return f"<Config env={self.env} loaded={self._loaded}>"


class ConfigSection:
    """配置子节点，支持属性访问"""

    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            return super().__getattribute__(name)
        value = self._data.get(name)
        if isinstance(value, dict):
            return ConfigSection(value)
        return value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def to_dict(self) -> dict:
        return self._data.copy()


# 全局单例
config = Config()

"""配置的存储与加载。

配置默认存放在 ``~/.gzcli/config.yaml``，可用环境变量 ``GZCLI_HOME``
覆盖配置目录（便于测试与多环境隔离）。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict

import yaml

from .schema import ConfigError, validate_config


def config_dir() -> Path:
    return Path(os.environ.get("GZCLI_HOME", Path.home() / ".gzcli"))


def config_path() -> Path:
    return config_dir() / "config.yaml"


def load_config() -> Dict[str, Any]:
    """加载并校验当前生效配置。未初始化或配置损坏时抛 ConfigError。"""
    path = config_path()
    if not path.exists():
        raise ConfigError(
            f"尚未初始化，请先执行 gzcli init --conf <conf.yaml>（期望路径: {path}）"
        )
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return validate_config(data)


def save_config(src: Path) -> Path:
    """将外部配置文件校验后存入配置目录，返回落盘路径。"""
    with open(src, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    validate_config(data)
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    dest = config_path()
    shutil.copyfile(src, dest)
    return dest

"""script 后端：把子指令映射为对团队 Python 脚本的子进程调用。

- source 支持本地路径（.py 文件或目录）与 git+URL[@ref]（缓存到
  ``$GZCLI_HOME/tools/``，ref 建议锁定 tag，保证内容可追溯）；
- 参数映射：``argv.xxx`` 拼为 ``--xxx 值``（bool 为开关、file 传绝对路径），
  ``env.XXX`` 注入子进程环境变量；
- 依赖隔离：脚本目录含 pyproject.toml / requirements.txt 且系统有 uv 时，
  用 ``uv run`` 自动建隔离环境；否则回退到当前解释器直接执行；
- stdout/stderr 原样透传，退出码透传。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config as cfg_mod

EXIT_LOCAL_ERROR = 2


def _err(msg: str) -> None:
    print(f"gzcli: {msg}", file=sys.stderr)


def _tools_dir() -> Path:
    d = cfg_mod.config_dir() / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_source(script_cfg: Dict[str, Any]) -> Tuple[Optional[Path], Optional[str]]:
    """返回 (脚本文件绝对路径, 错误信息)。"""
    source = str(script_cfg["source"])

    if source.startswith("git+"):
        url_ref = source[4:]
        url, _, ref = url_ref.rpartition("@")
        key = hashlib.sha256(url_ref.encode()).hexdigest()[:12]
        dest = _tools_dir() / key
        if not dest.exists():
            cmd = ["git", "clone", "--depth", "1"]
            if ref:
                cmd += ["--branch", ref]
            cmd += [url, str(dest)]
            _err(f"首次使用，正在拉取脚本: {url_ref}")
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                return None, f"拉取脚本失败: {proc.stderr.strip()[:300]}"
        base = dest
    else:
        base = Path(source).expanduser().resolve()
        if not base.exists():
            return None, f"脚本路径不存在: {base}"

    if base.is_file():
        return base, None
    entry = script_cfg.get("entry")
    if not entry:
        return None, "source 为目录时必须在配置中指定 script.entry"
    script_path = base / entry
    if not script_path.is_file():
        return None, f"入口文件不存在: {script_path}"
    return script_path, None


def _runner_for(script_path: Path) -> List[str]:
    """优先用 uv 建隔离环境运行；否则回退当前解释器。"""
    d = script_path.parent
    uv = shutil.which("uv")
    if uv:
        if (d / "pyproject.toml").exists():
            return [uv, "run", "--project", str(d), "python", str(script_path)]
        if (d / "requirements.txt").exists():
            return [uv, "run", "--with-requirements", str(d / "requirements.txt"),
                    "python", str(script_path)]
    return [sys.executable, str(script_path)]


def _build_argv_and_env(
    args_spec: Dict[str, Any], values: Dict[str, Any]
) -> Tuple[List[str], Dict[str, str]]:
    argv: List[str] = []
    env = dict(os.environ)
    for flag, spec in args_spec.items():
        name = flag.replace("-", "_")
        val = values.get(name)
        if val is None:
            continue
        target, _, field = spec["to"].partition(".")
        if target == "env":
            env[field] = str(val)
            continue
        # argv 目标
        dashed = field.replace("_", "-")
        atype = spec.get("type", "string")
        if atype == "bool":
            if val:
                argv.append(f"--{dashed}")
        elif atype == "file":
            argv += [f"--{dashed}", str(Path(val).resolve())]
        else:
            argv += [f"--{dashed}", str(val)]
    return argv, env


def execute_script(sub_cfg: Dict[str, Any], values: Dict[str, Any]) -> int:
    """执行 script 型子指令，返回脚本退出码（本地问题返回 2）。"""
    script_cfg = sub_cfg["script"]
    script_path, err = _resolve_source(script_cfg)
    if err:
        _err(err)
        return EXIT_LOCAL_ERROR

    argv, env = _build_argv_and_env(sub_cfg.get("args") or {}, values)
    cmd = _runner_for(script_path) + argv
    timeout = script_cfg.get("timeout")  # 缺省不限制

    try:
        proc = subprocess.run(cmd, cwd=str(script_path.parent), env=env, timeout=timeout)
        return proc.returncode
    except subprocess.TimeoutExpired:
        _err(f"脚本执行超时（{timeout}s）: {script_path.name}")
        return EXIT_LOCAL_ERROR
    except OSError as e:
        _err(f"脚本启动失败: {e}")
        return EXIT_LOCAL_ERROR

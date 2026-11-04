"""gzcli 入口：内置 init/update 命令 + 按配置动态生成子指令树。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import click
import httpx
import yaml

from . import __version__
from . import config as cfg_mod
from .executor import EXIT_LOCAL_ERROR, EXIT_OK, execute_subcommand
from .schema import ConfigError, validate_config

_ARG_TYPE_MAP = {
    "string": str,
    "int": int,
    "float": float,
}


def _make_callback(ns_cfg: Dict[str, Any], sub_cfg: Dict[str, Any]):
    def callback(**kwargs):
        code = execute_subcommand(ns_cfg, sub_cfg, kwargs)
        if code:
            raise SystemExit(code)

    return callback


def _build_subcommand(ns_cfg: Dict[str, Any], sub_name: str, sub_cfg: Dict[str, Any]) -> click.Command:
    params = []
    for flag, spec in (sub_cfg.get("args") or {}).items():
        atype = spec.get("type", "string")
        kwargs: Dict[str, Any] = {
            "required": bool(spec.get("required", False)),
            "default": spec.get("default"),
            "help": spec.get("help", ""),
        }
        if atype == "file":
            kwargs["type"] = click.Path(exists=True, dir_okay=False)
        elif atype == "bool":
            kwargs["is_flag"] = True
            kwargs["default"] = bool(spec.get("default", False))
            kwargs.pop("required")
        else:
            kwargs["type"] = _ARG_TYPE_MAP[atype]
        # 同时接受 --img_url 与 --img-url，参数名统一为下划线形式
        decls = [f"--{flag}"]
        dashed = flag.replace("_", "-")
        if dashed != flag:
            decls.append(f"--{dashed}")
        decls.append(flag.replace("-", "_"))
        params.append(click.Option(decls, **kwargs))

    return click.Command(
        name=sub_name,
        params=params,
        callback=_make_callback(ns_cfg, sub_cfg),
        help=sub_cfg.get("description", ""),
    )


def _attach_dynamic_commands(root: click.Group, conf: Dict[str, Any]) -> None:
    for ns_name, ns_cfg in conf["commands"].items():
        ns_group = click.Group(name=ns_name, help=ns_cfg.get("description", ""))
        for sub_name, sub_cfg in ns_cfg["subcommands"].items():
            ns_group.add_command(_build_subcommand(ns_cfg, sub_name, sub_cfg))
        root.add_command(ns_group)


@click.command("init")
@click.option("--conf", "conf_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="子指令注册配置文件（YAML）")
def init_cmd(conf_path: str) -> None:
    """初始化：校验并注册子指令配置。"""
    try:
        dest = cfg_mod.save_config(Path(conf_path))
    except ConfigError as e:
        click.echo(f"gzcli: {e}", err=True)
        raise SystemExit(EXIT_LOCAL_ERROR)
    conf = cfg_mod.load_config()
    ns_count = len(conf["commands"])
    sub_count = sum(len(ns["subcommands"]) for ns in conf["commands"].values())
    click.echo(f"配置已生效: {dest}")
    click.echo(f"已注册 {ns_count} 个命名空间、{sub_count} 个子指令，执行 gzcli --help 查看")


@click.command("update")
def update_cmd() -> None:
    """从管理站点拉取最新配置（需配置 registry.url）。"""
    try:
        conf = cfg_mod.load_config()
    except ConfigError as e:
        click.echo(f"gzcli: {e}", err=True)
        raise SystemExit(EXIT_LOCAL_ERROR)

    url = (conf.get("registry") or {}).get("url")
    if not url:
        click.echo("gzcli: 当前配置未声明 registry.url，无法从管理站点更新", err=True)
        raise SystemExit(EXIT_LOCAL_ERROR)

    try:
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
        data = yaml.safe_load(resp.text)
        validate_config(data)
    except (httpx.HTTPError, yaml.YAMLError, ConfigError) as e:
        click.echo(f"gzcli: 拉取配置失败: {e}", err=True)
        raise SystemExit(EXIT_LOCAL_ERROR)

    dest = cfg_mod.config_path()
    dest.write_text(resp.text, encoding="utf-8")
    click.echo(f"配置已更新: {dest}")


def _build_root() -> click.Group:
    root = click.Group(
        name="gzcli",
        help="CLIHub 统一入口：团队 HTTP 接口以子指令形式对外提供",
        context_settings={"help_option_names": ["-h", "--help"]},
    )
    root.add_command(init_cmd)
    root.add_command(update_cmd)

    try:
        conf = cfg_mod.load_config()
    except ConfigError:
        return root  # 未初始化时仅暴露 init/update
    _attach_dynamic_commands(root, conf)
    return root


def main() -> None:
    root = _build_root()
    try:
        root(prog_name="gzcli")
    except ConfigError as e:
        click.echo(f"gzcli: {e}", err=True)
        sys.exit(EXIT_LOCAL_ERROR)


if __name__ == "__main__":
    main()

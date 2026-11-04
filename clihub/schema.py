"""conf.yaml 的 Schema 校验。

配置结构::

    version: 1
    registry:                 # 可选，未来 Web 管理站点
      url: https://clihub.example.com/api/config
    commands:                 # 一级子指令（团队命名空间）
      img_detect:
        description: 图像检测能力集
        service:                        # http 型子指令必填
          base_url: http://img-detect.internal.api
          timeout: 30
          auth:
            type: header_token          # header_token | bearer | basic | none
            header: X-API-Token
            token_env: GZCLI_IMG_TOKEN
        subcommands:                    # 二级子指令
          obj_detect:
            description: 图像目标检测
            method: POST                # http 型必填
            path: /v1/detect            # http 型必填
            stream: false
            args:
              img:
                type: file              # string|int|float|bool|file
                to: form.img            # http 目标: query|json|form|header.字段名
                required: true

      data_team:                        # script 型命名空间可以没有 service
        description: 数据团队工具集
        subcommands:
          clean_csv:
            type: script                # script 后端：执行团队提供的 Python 脚本
            description: CSV 清洗工具
            script:
              source: git+https://git.internal.com/data-team/clean_csv.git@v1.2.0
              # 也支持本地路径: ./tools/clean_csv.py（文件）或 ./tools/clean_csv/（目录）
              entry: clean_csv.py       # source 为目录时必填；为 .py 文件时忽略
              timeout: 300              # 可选，秒；缺省不限制
            args:
              input:
                type: file
                to: argv.input          # script 目标: argv.参数名 | env.环境变量名
                required: true
"""

from __future__ import annotations

import re
from typing import Any, Dict

SUPPORTED_ARG_TYPES = {"string", "int", "float", "bool", "file"}
SUPPORTED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}
SUPPORTED_AUTH = {"header_token", "bearer", "basic", "none"}
SUPPORTED_BACKENDS = {"http", "script"}

_HTTP_TO_RE = re.compile(r"^(query|json|form|header)\.[A-Za-z0-9_.\[\]-]+$")
_SCRIPT_TO_RE = re.compile(r"^(argv|env)\.[A-Za-z_][A-Za-z0-9_]*$")


class ConfigError(Exception):
    """配置不合法或缺失。"""


def _fail(path: str, msg: str) -> None:
    raise ConfigError(f"配置错误 [{path}]: {msg}")


def _validate_auth(auth: Any, p: str) -> None:
    if auth.get("type") not in SUPPORTED_AUTH:
        _fail(f"{p}.type", f"仅支持 {sorted(SUPPORTED_AUTH)}")
    if auth.get("type") in ("header_token", "bearer") and not auth.get("token_env"):
        _fail(f"{p}.token_env", "header_token/bearer 必须指定读取凭证的环境变量名")
    if auth.get("type") == "basic" and not (auth.get("user_env") and auth.get("pass_env")):
        _fail(f"{p}.user_env/pass_env", "basic 必须指定用户名/密码的环境变量名")


def _validate_http_sub(sub: Dict[str, Any], sp: str) -> None:
    method = str(sub.get("method", "")).upper()
    if method not in SUPPORTED_METHODS:
        _fail(f"{sp}.method", f"http 型子指令必填，仅支持 {sorted(SUPPORTED_METHODS)}")
    path = sub.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        _fail(f"{sp}.path", "http 型子指令必填，且必须以 / 开头")


def _validate_script_sub(sub: Dict[str, Any], sp: str) -> None:
    script = sub.get("script")
    if not isinstance(script, dict) or not script.get("source"):
        _fail(f"{sp}.script.source", "script 型子指令必填（本地路径或 git+URL[@ref]）")
    source = str(script["source"])
    if not (source.startswith("git+") or source.endswith(".py") or script.get("entry")):
        _fail(f"{sp}.script.entry", "source 为目录时必须指定 entry 入口文件")


def _validate_args(sub: Dict[str, Any], sp: str, backend: str) -> None:
    args = sub.get("args") or {}
    if not isinstance(args, dict):
        _fail(f"{sp}.args", "必须是 mapping")
    to_re = _HTTP_TO_RE if backend == "http" else _SCRIPT_TO_RE
    to_hint = "query|json|form|header.字段名" if backend == "http" else "argv.参数名 | env.环境变量名"
    for flag, spec in args.items():
        ap = f"{sp}.args.{flag}"
        if not isinstance(spec, dict):
            _fail(ap, "必须是 mapping")
        atype = spec.get("type", "string")
        if atype not in SUPPORTED_ARG_TYPES:
            _fail(f"{ap}.type", f"仅支持 {sorted(SUPPORTED_ARG_TYPES)}")
        to = spec.get("to")
        if not isinstance(to, str) or not to_re.match(to):
            _fail(f"{ap}.to", f"必填，格式为 {to_hint}")
        if backend == "http" and atype == "file" and not to.startswith("form."):
            _fail(f"{ap}.to", "http 后端中 file 类型只能映射到 form.字段（multipart 上传）")
        if backend == "script" and atype == "file" and not to.startswith("argv."):
            _fail(f"{ap}.to", "script 后端中 file 类型只能映射到 argv.参数（传文件路径）")


def validate_config(data: Any) -> Dict[str, Any]:
    """校验并返回配置 dict，不合法时抛 ConfigError。"""
    if not isinstance(data, dict):
        _fail("$", "顶层必须是 mapping")

    commands = data.get("commands")
    if not isinstance(commands, dict) or not commands:
        _fail("commands", "至少需要一个一级子指令（团队命名空间）")

    for ns_name, ns in commands.items():
        p = f"commands.{ns_name}"
        if not isinstance(ns, dict):
            _fail(p, "必须是 mapping")

        subs = ns.get("subcommands")
        if not isinstance(subs, dict) or not subs:
            _fail(f"{p}.subcommands", "至少需要一个二级子指令")

        backends = set()
        for sub_name, sub in subs.items():
            sp = f"{p}.subcommands.{sub_name}"
            if not isinstance(sub, dict):
                _fail(sp, "必须是 mapping")
            backend = sub.get("type", "http")
            if backend not in SUPPORTED_BACKENDS:
                _fail(f"{sp}.type", f"仅支持 {sorted(SUPPORTED_BACKENDS)}，缺省为 http")
            backends.add(backend)
            if backend == "http":
                _validate_http_sub(sub, sp)
            else:
                _validate_script_sub(sub, sp)
            _validate_args(sub, sp, backend)

        # 含 http 子指令时必须有 service；纯 script 命名空间可以没有
        service = ns.get("service")
        if service is None and "http" in backends:
            _fail(f"{p}.service.base_url", "命名空间包含 http 型子指令，必填")
        if service is not None:
            if not service.get("base_url"):
                _fail(f"{p}.service.base_url", "必填，团队接口的 base url")
            _validate_auth(service.get("auth") or {"type": "none"}, f"{p}.service.auth")

    return data

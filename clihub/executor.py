"""HTTP 调用执行层：把命令行参数按配置映射为一次内部 HTTP 调用。

约定：
- 正常结果（JSON/文本/流）写 stdout，诊断与错误写 stderr；
- 非 JSON/文本 的二进制响应落盘，stdout 打印文件路径；
- 退出码：0 成功；1 接口返回错误或网络错误；2 本地配置/凭证问题。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx

EXIT_OK = 0
EXIT_REMOTE_ERROR = 1
EXIT_LOCAL_ERROR = 2


def _err(msg: str) -> None:
    print(f"gzcli: {msg}", file=sys.stderr)


def _build_auth(auth_cfg: Dict[str, Any]) -> Tuple[Dict[str, str], Optional[httpx.Auth], Optional[str]]:
    """返回 (headers, httpx_auth, error_msg)。凭证缺失时不抛异常，返回错误信息。"""
    atype = (auth_cfg or {}).get("type", "none")
    if atype == "none":
        return {}, None, None

    if atype in ("header_token", "bearer"):
        env_name = auth_cfg.get("token_env", "")
        token = os.environ.get(env_name, "")
        if not token:
            return {}, None, f"缺少凭证：请设置环境变量 {env_name}"
        if atype == "header_token":
            return {auth_cfg.get("header", "X-API-Token"): token}, None, None
        return {"Authorization": f"Bearer {token}"}, None, None

    if atype == "basic":
        user = os.environ.get(auth_cfg.get("user_env", ""), "")
        password = os.environ.get(auth_cfg.get("pass_env", ""), "")
        if not user or not password:
            return {}, None, (
                f"缺少凭证：请设置环境变量 {auth_cfg.get('user_env')} / {auth_cfg.get('pass_env')}"
            )
        return {}, httpx.BasicAuth(user, password), None

    return {}, None, f"不支持的鉴权类型: {atype}"


def _dump_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _handle_response(resp: httpx.Response) -> int:
    ct = resp.headers.get("content-type", "")
    if "json" in ct:
        try:
            _dump_json(resp.json())
            return EXIT_OK
        except ValueError:
            pass
    if ct.startswith("text/") or ct == "":
        sys.stdout.write(resp.text)
        if resp.text and not resp.text.endswith("\n"):
            sys.stdout.write("\n")
        return EXIT_OK

    # 二进制响应：落盘并打印路径
    ext = ""
    if "/" in ct:
        ext = "." + ct.split("/", 1)[1].split(";")[0].replace("jpeg", "jpg")
    out = Path.cwd() / f"gzcli_output_{int(time.time())}{ext}"
    out.write_bytes(resp.content)
    print(str(out))
    return EXIT_OK


def execute_subcommand(ns_cfg: Dict[str, Any], sub_cfg: Dict[str, Any], values: Dict[str, Any]) -> int:
    """按后端类型分发执行，返回进程退出码。"""
    if sub_cfg.get("type", "http") == "script":
        from .script_backend import execute_script

        return execute_script(sub_cfg, values)
    return _execute_http(ns_cfg, sub_cfg, values)


def _execute_http(ns_cfg: Dict[str, Any], sub_cfg: Dict[str, Any], values: Dict[str, Any]) -> int:
    """执行 http 型子指令，返回进程退出码。"""
    service = ns_cfg["service"]
    url = service["base_url"].rstrip("/") + sub_cfg["path"]
    method = sub_cfg["method"].upper()
    timeout = float(service.get("timeout", 30))

    headers, auth, auth_err = _build_auth(service.get("auth") or {})
    if auth_err:
        _err(auth_err)
        return EXIT_LOCAL_ERROR

    query: Dict[str, Any] = {}
    json_body: Dict[str, Any] = {}
    form: Dict[str, Any] = {}
    files: Dict[str, Any] = {}
    opened = []

    for flag, spec in (sub_cfg.get("args") or {}).items():
        name = flag.replace("-", "_")
        val = values.get(name)
        if val is None:
            continue
        target, _, field = spec["to"].partition(".")
        atype = spec.get("type", "string")
        try:
            if atype == "file":
                fh = open(val, "rb")
                opened.append(fh)
                files[field] = (Path(val).name, fh)
            elif target == "query":
                query[field] = val
            elif target == "json":
                json_body[field] = val
            elif target == "form":
                form[field] = val if isinstance(val, str) else str(val)
            elif target == "header":
                headers[field] = str(val)
        except OSError as e:
            _err(f"无法读取文件 {val}: {e}")
            for fh in opened:
                fh.close()
            return EXIT_LOCAL_ERROR

    # 有文件或表单字段时用 multipart，否则 JSON body
    request_kwargs: Dict[str, Any] = {"params": query, "headers": headers, "auth": auth}
    if files or form:
        request_kwargs["data"] = form
        request_kwargs["files"] = files
    elif json_body and method not in ("GET", "HEAD"):
        request_kwargs["json"] = json_body
    elif json_body:
        query.update(json_body)

    stream = bool(sub_cfg.get("stream"))
    try:
        with httpx.Client(timeout=timeout) as client:
            if stream:
                with client.stream(method, url, **request_kwargs) as resp:
                    if resp.status_code >= 400:
                        resp.read()
                        _err(f"HTTP {resp.status_code}: {resp.text.strip()[:500]}")
                        return EXIT_REMOTE_ERROR
                    for chunk in resp.iter_bytes():
                        sys.stdout.buffer.write(chunk)
                        sys.stdout.buffer.flush()
                    return EXIT_OK

            resp = client.request(method, url, **request_kwargs)
            if resp.status_code >= 400:
                _err(f"HTTP {resp.status_code}: {resp.text.strip()[:500]}")
                return EXIT_REMOTE_ERROR
            return _handle_response(resp)
    except httpx.TimeoutException:
        _err(f"请求超时（{timeout}s）: {url}")
        return EXIT_REMOTE_ERROR
    except httpx.HTTPError as e:
        _err(f"网络错误: {e}")
        return EXIT_REMOTE_ERROR
    finally:
        for fh in opened:
            fh.close()

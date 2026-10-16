"""解析用户从浏览器导出的 Cookie 文件。只在 CLI 中使用，Cookie 永远不经过 MCP。"""

from __future__ import annotations

import json
import re

from .errors import ConfigError

_NAME = re.compile(r"^[!#$%&\'*+\-.^_`|~0-9A-Za-z]+$")


def parse_cookie_text(text: str, host: str | None = None) -> dict[str, str]:
    """支持三种格式：

    * ``Cookie:`` 请求头或 ``a=b; c=d`` 字符串；
    * Netscape ``cookies.txt``（制表符分隔 7 列）；
    * 浏览器扩展导出的 JSON 数组（元素含 name/value/domain）。

    给出 ``host`` 时，cookies.txt / JSON 列表只保留域名匹配的条目；
    无 domain 字段的条目会被丢弃。纯 name→value 字典视为针对当前 host 的请求头格式。
    """
    stripped = text.strip().lstrip("\ufeff")
    if not stripped:
        raise ConfigError("Cookie 文件为空")
    if stripped.startswith("[") or stripped.startswith("{"):
        cookies = _parse_json(stripped, host)
    elif "\t" in stripped:
        cookies = _parse_netscape(stripped, host)
    else:
        cookies = _parse_header(stripped)
    cookies = {k: v for k, v in cookies.items() if _NAME.match(k)}
    if not cookies:
        raise ConfigError("没有解析出任何可用的 Cookie")
    return cookies


def _domain_ok(domain: str, host: str | None) -> bool:
    """结构化 Cookie（含 domain 列/字段）在给定 host 时必须域名匹配。"""
    if host is None:
        return True
    if not domain:
        return False
    domain = domain.lstrip(".").lower()
    host = host.lower()
    return host == domain or host.endswith("." + domain)


def _parse_header(text: str) -> dict[str, str]:
    text = re.sub(r"(?i)^cookie\s*:\s*", "", text.splitlines()[0] if "\n" in text else text)
    result: dict[str, str] = {}
    for part in text.split(";"):
        if "=" in part:
            name, value = part.split("=", 1)
            result[name.strip()] = value.strip()
    return result


def _parse_netscape(text: str, host: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
        elif not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) == 7 and _domain_ok(cols[0], host):
            result[cols[5]] = cols[6].strip()
    return result


def _parse_json(text: str, host: str | None) -> dict[str, str]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ConfigError("Cookie JSON 格式错误") from exc
    if isinstance(data, dict) and "cookies" in data:
        data = data["cookies"]
    if isinstance(data, dict):
        # 纯 name→value：视为当前 host 的请求头格式（无 domain 可校验）
        # 若值是对象则不是合法的简单字典
        if any(isinstance(v, (dict, list)) for v in data.values()):
            raise ConfigError("Cookie JSON 字典值必须是字符串")
        return {str(k): str(v) for k, v in data.items() if k != "domain"}
    result: dict[str, str] = {}
    if isinstance(data, list):
        for item in data:
            if (
                isinstance(item, dict)
                and "name" in item
                and "value" in item
                and _domain_ok(str(item.get("domain", "")), host)
            ):
                result[str(item["name"])] = str(item["value"])
    return result

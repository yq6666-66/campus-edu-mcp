"""日志与错误信息脱敏。任何可能进入日志的字符串都应经过这里。"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MASK = "***"

#: URL 查询参数或表单中需要整体打码的键（小写比较）
SENSITIVE_KEYS = frozenset(
    {
        "xh",
        "xh_id",
        "su",
        "yhm",
        "mm",
        "password",
        "passwd",
        "pwd",
        "token",
        "access_token",
        "ticket",
        "jsessionid",
        "sessionid",
        "serverid",
        "route",
        "cookie",
        "sfzh",
        "xm",
        "csrftoken",
    }
)

_COOKIE_HEADER = re.compile(r"(?im)^(\s*(?:set-)?cookie\s*:\s*).*$")
_KV = re.compile(
    r"(?i)\b(" + "|".join(sorted(SENSITIVE_KEYS, key=len, reverse=True)) + r")(\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s;&,\"'}]+)"
)
_JSON_KV = re.compile(r"(?i)(\"(?:" + "|".join(SENSITIVE_KEYS) + r")\"\s*:\s*)(\"[^\"]*\"|[0-9]+)")
#: 8 位以上连续数字，视为可能的学号 / 身份证号
_LONG_DIGITS = re.compile(r"(?<![\d.])\d{8,}(?![\d.])")


def redact_url(url: str) -> str:
    """把 URL 中敏感查询参数的值替换为 ***，同时去掉 userinfo。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return redact(url)
    netloc = parts.netloc.rsplit("@", 1)[-1]
    query = parts.query
    if query:
        pairs = parse_qsl(query, keep_blank_values=True)
        query = urlencode(
            [(k, MASK if k.lower() in SENSITIVE_KEYS else _mask_digits(v)) for k, v in pairs],
            safe="*",
        )
    path = re.sub(r"(?i);jsessionid=[^/?#]*", ";jsessionid=" + MASK, parts.path)
    return urlunsplit((parts.scheme, netloc, path, query, ""))


def _mask_digits(text: str) -> str:
    return _LONG_DIGITS.sub(MASK, text)


def redact(text: str) -> str:
    """对任意文本脱敏：Cookie 头、敏感键值对、URL 参数、长数字串。"""
    text = _COOKIE_HEADER.sub(lambda m: m.group(1) + MASK, text)
    text = re.sub(r"https?://[^\s\"'<>]+", lambda m: redact_url(m.group(0)), text)
    text = _JSON_KV.sub(lambda m: m.group(1) + '"' + MASK + '"', text)
    text = _KV.sub(lambda m: m.group(1) + m.group(2) + MASK, text)
    return _mask_digits(text)


class RedactingFilter(logging.Filter):
    """挂到 handler 上，保证日志落地前先脱敏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = redact(message)
        record.args = None
        return True


def install_logging(verbose: bool = False) -> None:
    """配置包日志：输出到 stderr（stdio 模式下 stdout 留给 MCP 协议）。"""
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger("campus_edu_mcp")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.DEBUG if verbose else logging.WARNING)
    logger.propagate = False
    # 第三方 HTTP 库也可能打印 Cookie 头；挂同一过滤器并默认静音
    for name in ("httpx", "httpcore", "urllib3"):
        lib = logging.getLogger(name)
        lib.addFilter(RedactingFilter())
        if not verbose:
            lib.setLevel(logging.WARNING)
        lib.propagate = False

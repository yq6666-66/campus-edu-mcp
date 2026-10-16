"""``campus-edu-mcp doctor``：本地自检。只报告「有 / 无 / 数量」，绝不输出 Cookie 或密钥内容。"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from .errors import ProjectError
from .redact import redact
from .storage import SessionStore, load_config
from .verification import ALLOW_UNVERIFIED_ENV, UNVERIFIED_VENDORS


@dataclass(frozen=True)
class Check:
    name: str
    level: str  # ok / warn / fail
    detail: str


def run_checks(
    *,
    online: bool = False,
    store_factory: Callable[[], SessionStore] = SessionStore,
    status_fn: Callable[[], object] | None = None,
) -> list[Check]:
    checks: list[Check] = []
    py = sys.version_info
    checks.append(
        Check("python", "ok" if py >= (3, 11) else "fail", f"{py.major}.{py.minor}.{py.micro}")
    )
    try:
        config = load_config()
    except ProjectError as exc:
        checks.append(Check("config", "fail", redact(str(exc))))
        return checks
    url = httpx.URL(config.base_url)
    checks.append(Check("config", "ok", f"vendor={config.vendor} scheme={url.scheme}"))
    if url.scheme != "https":
        checks.append(Check("transport", "warn", "教务地址不是 https，Cookie 会明文传输"))
    if config.min_interval < 1.0:
        checks.append(Check("rate-limit", "warn", f"min_interval={config.min_interval}s 偏小"))
    if config.vendor in UNVERIFIED_VENDORS:
        allowed = os.environ.get(ALLOW_UNVERIFIED_ENV) == "1"
        checks.append(
            Check(
                "vendor",
                "warn" if allowed else "fail",
                f"{config.vendor} 未做 live 实测"
                + ("（已通过环境变量启用）" if allowed else f"，需设置 {ALLOW_UNVERIFIED_ENV}=1"),
            )
        )
    sources = []
    try:
        store = store_factory()
        persistent = store.persistent
        if store.load(url.host):
            sources.append("加密存储")
    except ProjectError as exc:
        persistent = False
        checks.append(Check("session-store", "warn", redact(str(exc))))
    checks.append(
        Check(
            "keyring",
            "ok" if persistent else "warn",
            "系统 keyring 可用" if persistent else "keyring 不可用，会话只能经环境变量提供",
        )
    )
    if os.environ.get("CAMPUS_EDU_COOKIE_FILE"):
        sources.append("CAMPUS_EDU_COOKIE_FILE")
    if os.environ.get("CAMPUS_EDU_COOKIE"):
        sources.append("CAMPUS_EDU_COOKIE")
    checks.append(
        Check(
            "session",
            "ok" if sources else "fail",
            ("来源：" + "、".join(sources)) if sources else "未找到会话，请先 import-session",
        )
    )
    if online and sources:
        if status_fn is None:
            from .service import Service

            status_fn = Service().session_status
        status = status_fn()
        valid = getattr(status, "valid", None)
        message = redact(str(getattr(status, "message", "")))
        level = "ok" if valid else ("warn" if valid is None else "fail")
        checks.append(Check("session-online", level, message))
    return checks


def render(checks: list[Check]) -> tuple[str, int]:
    icon = {"ok": "[ok]  ", "warn": "[warn]", "fail": "[FAIL]"}
    lines = [f"{icon[c.level]} {c.name}: {c.detail}" for c in checks]
    code = 1 if any(c.level == "fail" for c in checks) else 0
    return "\n".join(lines), code

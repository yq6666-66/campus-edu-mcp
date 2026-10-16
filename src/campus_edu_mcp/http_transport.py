"""实验性：Streamable HTTP 传输（默认关闭，仅本机）。

* 只监听 127.0.0.1，不提供修改监听地址的选项；
* 必须设置 ``CAMPUS_EDU_HTTP_TOKEN``（至少 32 个字符），每个请求都要带
  ``Authorization: Bearer <token>``，常量时间比较；
* Host / Origin 由 MCP SDK 的 DNS rebinding 防护限定为本机地址；
* 工具与 stdio 完全相同，仍然只读。

不属于语义化版本承诺范围。
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from .errors import ConfigError

TOKEN_ENV = "CAMPUS_EDU_HTTP_TOKEN"  # noqa: S105 - 环境变量名
MIN_TOKEN_LEN = 32
HOST = "127.0.0.1"

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def load_token() -> str:
    token = os.environ.get(TOKEN_ENV, "")
    if len(token) < MIN_TOKEN_LEN:
        raise ConfigError(
            f"HTTP 传输需要环境变量 {TOKEN_ENV}（至少 {MIN_TOKEN_LEN} 个字符的随机串），"
            '例如 python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    return token


class BearerAuth:
    """纯 ASGI 中间件：缺少或错误的 Bearer token 一律 401，不区分原因。"""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        values = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
        provided = values[0] if len(values) == 1 else b""
        # 恰好一个 Authorization 头且常量时间相等才放行；重复头一律拒绝
        if len(values) != 1 or not hmac.compare_digest(provided, self._expected):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"text/plain; charset=utf-8"),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b"unauthorized"})
            return
        await self.app(scope, receive, send)


def build_app(port: int, token: str, server: Any | None = None) -> ASGIApp:
    from mcp.server.transport_security import TransportSecuritySettings

    from .server import build_server

    mcp = server or build_server()
    hosts = [f"{HOST}:{port}", f"localhost:{port}"]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[f"http://{h}" for h in hosts],
    )
    app = mcp.streamable_http_app(transport_security=security, host=HOST)
    return BearerAuth(app, token)


def check_port(port: int) -> int:
    if not 1024 <= port <= 65535:
        raise ConfigError("端口应在 1024-65535 之间")
    return port


def serve_http(port: int) -> None:  # pragma: no cover - 由端到端测试以子进程覆盖
    import uvicorn

    check_port(port)
    token = load_token()
    uvicorn.run(build_app(port, token), host=HOST, port=port, log_level="warning")

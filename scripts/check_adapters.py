"""静态检查：适配器不得自行发起网络请求，只能使用注入的 GuardedClient。

用 AST 而不是 grep，能识别 ``import httpx as h; h.Client()``、
``from httpx import Client as C`` 等写法。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ADAPTER_DIR = Path(__file__).resolve().parent.parent / "src" / "campus_edu_mcp" / "adapters"
BANNED_MODULES = {
    "requests",
    "urllib.request",
    "urllib3",
    "http.client",
    "aiohttp",
    "socket",
    "ssl",
    "subprocess",
    "pycurl",
    "websocket",
    "websockets",
}
#: httpx 只允许导入这些（类型 / 响应对象），不允许任何能发请求的东西
HTTPX_ALLOWED = {"Response", "URL", "Request", "Headers"}
BANNED_CALL_NAMES = {
    "Client",
    "AsyncClient",
    "HTTPTransport",
    "AsyncHTTPTransport",
    "request",
    "stream",
}
BANNED_HTTPX_ATTRS = BANNED_CALL_NAMES | {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
}
BANNED_PRIVATE_ATTRS = {"_client", "inner", "whitelist", "_transport"}
BANNED_BUILTINS = {"eval", "exec", "__import__", "compile"}


def _banned_module(name: str) -> bool:
    return any(name == m or name.startswith(m + ".") for m in BANNED_MODULES)


def check_source(source: str, filename: str = "<string>") -> list[str]:
    tree = ast.parse(source, filename)
    problems: list[str] = []
    httpx_aliases: set[str] = set()

    def report(node: ast.AST, msg: str) -> None:
        problems.append(f"{filename}:{getattr(node, 'lineno', 0)}: {msg}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _banned_module(alias.name):
                    report(node, f"禁止导入 {alias.name}")
                if alias.name == "httpx":
                    httpx_aliases.add(alias.asname or "httpx")
                if alias.name in {"importlib"}:
                    report(node, "禁止动态导入")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _banned_module(module):
                report(node, f"禁止导入 {module}")
            if module.startswith("httpx"):
                for alias in node.names:
                    if module != "httpx" or alias.name not in HTTPX_ALLOWED:
                        report(node, f"禁止从 httpx 导入 {alias.name}")
            if module == "importlib":
                report(node, "禁止动态导入")
            if module.endswith("guard"):
                for alias in node.names:
                    if alias.name not in {"GuardedClient", "Rule"}:
                        report(node, f"禁止从 guard 导入 {alias.name}")
        elif isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id in httpx_aliases
                and (node.attr in BANNED_HTTPX_ATTRS or node.attr not in HTTPX_ALLOWED)
            ):
                report(node, f"禁止使用 httpx.{node.attr}")
            if node.attr in BANNED_PRIVATE_ATTRS:
                report(node, f"禁止访问内部属性 .{node.attr}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BANNED_BUILTINS:
                report(node, f"禁止调用 {func.id}")
            if isinstance(func, ast.Name) and func.id == "getattr":
                report(node, "禁止使用 getattr（可能绕过静态检查）")
    return problems


def main(paths: list[str] | None = None) -> int:
    targets = [Path(p) for p in paths] if paths else sorted(ADAPTER_DIR.rglob("*.py"))
    problems: list[str] = []
    for path in targets:
        problems.extend(check_source(path.read_text("utf-8"), str(path)))
    for line in problems:
        print(line)
    if problems:
        print(f"发现 {len(problems)} 处违规", file=sys.stderr)
        return 1
    print(f"适配器静态检查通过（{len(targets)} 个文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

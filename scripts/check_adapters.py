"""静态检查：适配器不得自行发起网络请求，只能使用注入的 GuardedClient。"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ADAPTER_DIR = Path(__file__).resolve().parent.parent / "src" / "campus_edu_mcp" / "adapters"
BANNED_MODULES = {
    "requests",
    "urllib",
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
    "os",
    "asyncio",
    "httpx",  # 只允许下面白名单 from-import
}
# httpx 仅允许类型；禁止 import httpx 模块本身（用 from httpx import Response）
HTTPX_ALLOWED = {"Response", "URL", "Request", "Headers"}
BANNED_CALL_NAMES = {
    "Client",
    "AsyncClient",
    "HTTPTransport",
    "AsyncHTTPTransport",
    "request",
    "stream",
    "system",
    "popen",
    "open_connection",
    "create_connection",
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
BANNED_DUNDER_ATTRS = {
    "__dict__",
    "__getattribute__",
    "__getattr__",
    "__class__",
    "__bases__",
    "__mro__",
    "__subclasses__",
    "__globals__",
    "__code__",
}
BANNED_BUILTINS = {
    "eval",
    "exec",
    "__import__",
    "compile",
    "getattr",
    "setattr",
    "vars",
    "globals",
    "locals",
}


def _banned_module(name: str) -> bool:
    if name == "httpx":
        return False  # 单独处理：禁止 import httpx，允许 from httpx import Response
    return any(name == m or name.startswith(m + ".") for m in BANNED_MODULES if m != "httpx")


def check_source(source: str, filename: str = "<string>") -> list[str]:
    tree = ast.parse(source, filename)
    problems: list[str] = []
    httpx_aliases: set[str] = set()

    def report(node: ast.AST, msg: str) -> None:
        problems.append(f"{filename}:{getattr(node, 'lineno', 0)}: {msg}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "httpx" or alias.name.startswith("httpx."):
                    report(node, "禁止 import httpx（请用 from httpx import Response 等类型）")
                elif _banned_module(alias.name):
                    report(node, f"禁止导入 {alias.name}")
                if alias.name in {"importlib"}:
                    report(node, "禁止动态导入")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "httpx" or module.startswith("httpx."):
                for alias in node.names:
                    if module != "httpx" or alias.name not in HTTPX_ALLOWED:
                        report(node, f"禁止从 httpx 导入 {alias.name}")
            elif _banned_module(module) or module.split(".", 1)[0] in BANNED_MODULES:
                report(node, f"禁止导入 {module}")
            if module == "importlib":
                report(node, "禁止动态导入")
            if module.endswith("guard"):
                for alias in node.names:
                    if alias.name not in {"GuardedClient", "Rule"}:
                        report(node, f"禁止从 guard 导入 {alias.name}")
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_PRIVATE_ATTRS or node.attr in BANNED_DUNDER_ATTRS:
                report(node, f"禁止访问内部/反射属性 .{node.attr}")
            if (
                isinstance(node.value, ast.Name)
                and node.value.id in httpx_aliases
                and (node.attr in BANNED_HTTPX_ATTRS or node.attr not in HTTPX_ALLOWED)
            ):
                report(node, f"禁止使用 httpx.{node.attr}")
        elif isinstance(node, ast.Subscript):
            # client.__dict__['_client']
            if isinstance(node.value, ast.Attribute) and node.value.attr == "__dict__":
                report(node, "禁止通过 __dict__ 取内部属性")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BANNED_BUILTINS:
                report(node, f"禁止调用 {func.id}")
            if isinstance(func, ast.Attribute) and func.attr in BANNED_CALL_NAMES:
                report(node, f"禁止调用 .{func.attr}()")
    return problems


def main(paths: list[str] | None = None) -> int:
    targets = [Path(p) for p in paths] if paths else sorted(ADAPTER_DIR.rglob("*.py"))
    problems: list[str] = []
    for path in targets:
        # 允许 adapters 里 from httpx import Response：先不把 httpx 当 banned import-from 根
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

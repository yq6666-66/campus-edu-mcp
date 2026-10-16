"""MCP 服务（mcp 2.x 的 MCPServer，仅 stdio）。所有工具只读。"""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from . import __version__
from .errors import ProjectError
from .redact import redact
from .service import Service

INSTRUCTIONS = (
    "这是只读的高校教务助手（默认强智 jsxsd，可选正方 V9）。"
    "只能查询用户本人的课表、考试安排和成绩，不能做任何修改。"
    "成绩默认只给出是否通过和学分；只有用户明确想知道分数时才传 include_scores=true。"
    "如果提示会话失效，请让用户自己在终端重新导入 Cookie，不要向用户索要 Cookie 或密码。"
)
READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)


def _safe(fn: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        result: dict[str, Any] = fn(*args, **kwargs)
        return result
    except ProjectError as exc:
        return {"error": type(exc).__name__, "message": redact(str(exc))}


def build_server(service: Service | None = None) -> MCPServer:
    svc = service or Service()
    mcp: MCPServer = MCPServer(
        name="campus-edu-mcp", version=__version__, instructions=INSTRUCTIONS
    )

    @mcp.tool(annotations=READ_ONLY)
    def get_timetable(year: int | None = None, term: int | None = None) -> dict[str, Any]:
        """查询本人课表。

        year 为学年起始年（如 2025 表示 2025-2026 学年），term 为 1/2/3；不填则取当前学期。
        """
        return _safe(svc.timetable, year, term)

    @mcp.tool(annotations=READ_ONLY)
    def get_exams(year: int | None = None, term: int | None = None) -> dict[str, Any]:
        """查询本人考试安排（时间、地点、座位号）。参数同 get_timetable。"""
        return _safe(svc.exams, year, term)

    @mcp.tool(annotations=READ_ONLY)
    def get_grades(
        year: int | None = None, term: int | None = None, include_scores: bool = False
    ) -> dict[str, Any]:
        """查询本人成绩。默认只返回课程、学分、是否通过；include_scores=true 时才返回分数和绩点。
        year 与 term 都不填则返回全部学期。返回的数据会进入你所用模型的上下文。"""
        return _safe(svc.grades, year, term, include_scores)

    @mcp.tool(annotations=READ_ONLY)
    def session_status() -> dict[str, Any]:
        """检查教务会话是否已导入、是否仍然有效。不会返回任何 Cookie 内容。"""
        return svc.session_status().model_dump()

    return mcp


def main() -> None:  # pragma: no cover - 由 CLI / 端到端测试覆盖
    build_server().run("stdio")

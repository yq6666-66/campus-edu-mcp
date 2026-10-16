"""MCP 服务（mcp 2.x 的 MCPServer，仅 stdio）。所有工具只读。"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from .errors import ProjectError
from .redact import redact
from .service import Service

logger = logging.getLogger(__name__)

INSTRUCTIONS = (
    "这是只读的高校教务助手（默认强智 jsxsd；正方 V9 适配器未做 live 实测，默认禁用）。"
    "只能查询用户本人的课表、考试安排、成绩、学期列表和空闲教室，不能做任何修改。"
    "成绩默认返回课程、学分、课程性质、是否通过；只有用户明确想知道分数时才传 include_scores=true。"
    "结果中的 meta.status 为 pending/stale 时，请提醒用户该功能尚未在真实学校充分验证。"
    "如果提示会话缺失或失效，请让用户自己在终端导入 Cookie，不要向用户索要 Cookie 或密码。"
)
READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)


def _safe(fn: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """执行业务函数；失败时抛出 ToolError，使 MCP 结果带 isError=true。"""
    try:
        result: dict[str, Any] = fn(*args, **kwargs)
        return result
    except ProjectError as exc:
        raise ToolError(f"{type(exc).__name__}: {redact(str(exc))}") from exc
    except Exception:
        logger.exception("工具执行出现未预期错误")
        raise ToolError("服务内部错误，请查看本机日志或重试") from None


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
        """查询本人成绩。

        默认返回课程、学分、课程性质、是否通过；include_scores=true 时才返回分数和绩点。
        year 与 term 都不填则返回全部学期（结果中 term 为 null）。返回的数据会进入模型上下文。
        """
        return _safe(svc.grades, year, term, include_scores)

    @mcp.tool(annotations=READ_ONLY)
    def get_terms() -> dict[str, Any]:
        """列出教务系统可选的学期（current=true 为系统默认学期）。已在一所强智校只读实测。"""
        return _safe(svc.terms)

    @mcp.tool(annotations=READ_ONLY)
    def get_empty_classrooms(
        week: int,
        weekday: int,
        periods: list[str] | None = None,
        campus: str | None = None,
        min_capacity: int | None = None,
        year: int | None = None,
        term: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """查询某教学周某天的空闲教室（只读，不会提交借用申请）。

        week 为教学周（1-30），weekday 为 1=周一 … 7=周日；periods 为必须全部空闲的节次编码
        （如 ["0102","0304"]，可选值见返回的 periods）；campus 为校区编号；
        year/term 不填则用教务系统默认学期。
        """
        return _safe(
            svc.empty_classrooms, week, weekday, periods, campus, year, term, min_capacity, limit
        )

    @mcp.tool(annotations=READ_ONLY)
    def session_status() -> dict[str, Any]:
        """检查教务会话是否已导入、是否仍然有效。不会返回任何 Cookie 内容。"""
        return svc.session_status().model_dump()

    return mcp


def main() -> None:  # pragma: no cover - 由 CLI / 端到端测试覆盖
    build_server().run("stdio")

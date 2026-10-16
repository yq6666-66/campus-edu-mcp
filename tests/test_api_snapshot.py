"""1.0 API 冻结：工具名、入参 schema、注解与结果字段的快照。

有意修改公开 API 时运行 ``CAMPUS_EDU_UPDATE_SNAPSHOT=1 uv run pytest tests/test_api_snapshot.py``
重新生成，并在 CHANGELOG 中按 docs/api-stability.md 的弃用策略说明。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

from campus_edu_mcp.server import build_server
from campus_edu_mcp.service import Service
from campus_edu_mcp.storage import Config

SNAPSHOT = Path(__file__).parent / "snapshots" / "api-v1.json"
FIX = Path(__file__).parent / "fixtures" / "qiangzhi"
BASE = "https://jw.example.edu.cn/jsxsd/"
ROUTES = {
    "xskb/xskb_list.do": "timetable.html",
    "kscj/cjcx_list": "grades.html",
    "xsks/xsksap_list": "exams.html",
    "kbxx/jsjy_query": "rooms_form.html",
    "kbxx/jsjy_query2": "rooms_grid.html",
}


def _service() -> Service:
    def handler(request: httpx.Request) -> httpx.Response:
        rel = request.url.path.removeprefix("/jsxsd/")
        name = ROUTES.get(rel)
        if name is None:
            return httpx.Response(404)
        return httpx.Response(200, text=(FIX / name).read_text("utf-8"))

    return Service(
        Config(base_url=BASE, vendor="qiangzhi", min_interval=0),
        cookies_loader=lambda h: {"JSESSIONID": "FAKE"},
        transport=httpx.MockTransport(handler),
    )


def _shape(value: Any) -> Any:
    """只保留结构：字典的键与列表首元素的结构。"""
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    return "*"  # 叶子值的类型可能随数据为 null，只冻结字段名


CALLS: dict[str, dict[str, Any]] = {
    "get_timetable": {"year": 2098, "term": 1},
    "get_exams": {"year": 2098, "term": 1},
    "get_grades": {},
    "get_terms": {},
    "get_empty_classrooms": {"week": 1, "weekday": 5, "periods": ["0102"]},
    "session_status": {},
}


def current_api() -> dict[str, Any]:
    server = build_server(_service())

    async def go() -> dict[str, Any]:
        tools = {}
        for tool in sorted(await server.list_tools(), key=lambda t: t.name):
            annotations = tool.annotations.model_dump(exclude_none=True) if tool.annotations else {}
            result = await server.call_tool(tool.name, CALLS[tool.name])
            structured = (
                result.structured_content if hasattr(result, "structured_content") else None
            )
            if structured is None:
                text = "".join(getattr(c, "text", "") for c in getattr(result, "content", []))
                structured = json.loads(text)
            tools[tool.name] = {
                "input_schema": tool.input_schema,
                "annotations": annotations,
                "result_shape": _shape(structured),
            }
        return tools

    return asyncio.run(go())


def test_api_snapshot() -> None:
    api = current_api()
    rendered = json.dumps(api, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("CAMPUS_EDU_UPDATE_SNAPSHOT") == "1":
        SNAPSHOT.write_text(rendered, "utf-8")
    expected = json.loads(SNAPSHOT.read_text("utf-8"))
    assert api == expected, "公开 API 发生变化：请按 docs/api-stability.md 处理后更新快照"


def test_cli_surface_frozen() -> None:
    import argparse

    from campus_edu_mcp.cli import _parser

    sub = next(a for a in _parser()._actions if isinstance(a, argparse._SubParsersAction))
    assert set(sub.choices) == {
        "serve",
        "configure",
        "import-session",
        "session-status",
        "clear-session",
        "doctor",
        "schools",
        "login",  # experimental
        "export-ics",  # experimental
    }

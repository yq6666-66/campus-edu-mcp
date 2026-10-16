"""端到端冒烟：真实启动 MCP stdio 子进程，连到本地 mock_server。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

from mock_server.server import QZ_BASE as BASE
from mock_server.server import VALID_COOKIE, serve


@pytest.fixture
def mock_school() -> Iterator[str]:
    httpd, _state = serve(0, vendor="qiangzhi")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _text(result: Any) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


def _env(base_url: str, cookie_file: Path, tmp_path: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if isinstance(v, str)}
    env.update(
        {
            "CAMPUS_EDU_BASE_URL": base_url + BASE,
            "CAMPUS_EDU_VENDOR": "qiangzhi",
            "CAMPUS_EDU_COOKIE_FILE": str(cookie_file),
            "CAMPUS_EDU_DATA_DIR": str(tmp_path / "data"),
            "CAMPUS_EDU_MIN_INTERVAL": "0",
            "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
        }
    )
    return env


async def _session(env: dict[str, str], err_path: Path) -> dict[str, str]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "campus_edu_mcp", "serve"],
        env=env,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    out: dict[str, str] = {}
    with err_path.open("w") as errlog:
        async with (
            stdio_client(params, errlog=errlog) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            out["tools"] = ",".join(sorted(t.name for t in tools.tools))
            out["status"] = _text(await session.call_tool("session_status", {}))
            tt = await session.call_tool("get_timetable", {"year": 2098, "term": 1})
            out["timetable"] = _text(tt)
            out["timetable_is_error"] = str(bool(getattr(tt, "is_error", False)))
            out["terms"] = _text(await session.call_tool("get_terms", {}))
            rooms = await session.call_tool(
                "get_empty_classrooms", {"week": 3, "weekday": 5, "periods": ["0102"]}
            )
            out["rooms"] = _text(rooms)
            out["exams"] = _text(await session.call_tool("get_exams", {"year": 2098, "term": 1}))
            out["grades"] = _text(await session.call_tool("get_grades", {}))
            out["scores"] = _text(await session.call_tool("get_grades", {"include_scores": True}))
    return out


def test_stdio_end_to_end(mock_school: str, tmp_path: Path) -> None:
    cookie = tmp_path / "cookie.txt"
    cookie.write_text(f"JSESSIONID={VALID_COOKIE}", "utf-8")
    err = tmp_path / "stderr.txt"
    out = asyncio.run(_session(_env(mock_school, cookie, tmp_path), err))
    assert (
        out["tools"]
        == "get_empty_classrooms,get_exams,get_grades,get_terms,get_timetable,session_status"
    ), err.read_text()
    assert "会话有效" in out["status"], out["status"] + "\n" + err.read_text()
    assert len(json.loads(out["timetable"])["courses"]) == 6
    assert len(json.loads(out["exams"])["exams"]) == 4
    assert [r["name"] for r in json.loads(out["rooms"])["rooms"]] == ["虚构楼A101", "虚构楼B201"]
    assert [t["current"] for t in json.loads(out["terms"])["terms"]] == [False, True]
    grades = json.loads(out["grades"])
    assert grades["failed_count"] >= 1 and "score" not in grades["grades"][0]
    assert "score" in json.loads(out["scores"])["grades"][0]
    everything = json.dumps(out, ensure_ascii=False)
    assert VALID_COOKIE not in everything
    assert "2099000001" not in everything and "测试学生" not in everything
    with urllib.request.urlopen(mock_school + "/__hits") as resp:  # noqa: S310
        assert json.load(resp)["write_hits"] == 0


def test_stdio_expired_session(mock_school: str, tmp_path: Path) -> None:
    cookie = tmp_path / "cookie.txt"
    cookie.write_text("JSESSIONID=FAKE-EXPIRED", "utf-8")
    err = tmp_path / "stderr.txt"
    out = asyncio.run(_session(_env(mock_school, cookie, tmp_path), err))
    assert "会话已失效" in out["status"] or "SessionExpired" in out["status"], out["status"]
    assert "SessionExpired" in out["timetable"] and "import-session" in out["timetable"]
    assert out["timetable_is_error"] == "True"
    assert "FAKE-EXPIRED" not in json.dumps(out, ensure_ascii=False)


def test_stdio_expired_json_session(mock_school: str, tmp_path: Path) -> None:
    cookie = tmp_path / "cookie.txt"
    cookie.write_text("JSESSIONID=FAKE-EXPIRED-JSON", "utf-8")
    err = tmp_path / "stderr.txt"
    out = asyncio.run(_session(_env(mock_school, cookie, tmp_path), err))
    assert "会话已失效" in out["status"], out["status"]
    for key in ("timetable", "terms", "exams", "grades"):
        assert "SessionExpired" in out[key], (key, out[key])
    assert "FAKE-EXPIRED-JSON" not in json.dumps(out, ensure_ascii=False)

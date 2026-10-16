from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from campus_edu_mcp.adapters.zfsoft_v9 import RULES
from campus_edu_mcp.errors import ConfigError, SessionExpired, SessionMissing
from campus_edu_mcp.models import PRIVACY_NOTICE
from campus_edu_mcp.server import build_server
from campus_edu_mcp.service import Service, current_term, load_cookies, resolve_term
from campus_edu_mcp.storage import Config, SessionStore

from .conftest import BASE_URL, MemoryKeyring, fixture_text

FILES = {
    "kbcx/xskbcx_cxXsKb.html": "timetable.json",
    "kwgl/kscx_cxXsksxxIndex.html": "exams.json",
    "cjcx/cjcx_cxXsgrcj.html": "grades.json",
}


def fake_school(request: httpx.Request) -> httpx.Response:
    if request.headers.get("cookie") != "JSESSIONID=FAKE-OK":
        return httpx.Response(302, headers={"location": "/jwglxt/xtgl/login_slogin.html"})
    for suffix, name in FILES.items():
        if request.url.path.endswith(suffix):
            return httpx.Response(200, text=fixture_text(name))
    return httpx.Response(404)


def make_service(cookie: str | None = "FAKE-OK") -> Service:
    return Service(
        Config(base_url=BASE_URL, vendor="zfsoft_v9", min_interval=0),
        cookies_loader=lambda host: {"JSESSIONID": cookie} if cookie else None,
        transport=httpx.MockTransport(fake_school),
    )


@pytest.mark.parametrize(
    ("day", "year", "term"),
    [
        (dt.date(2026, 10, 16), 2026, 1),
        (dt.date(2027, 1, 5), 2026, 1),
        (dt.date(2027, 4, 1), 2026, 2),
    ],
)
def test_current_term(day: dt.date, year: int, term: int) -> None:
    assert current_term(day).model_dump() == {"year": year, "term": term}
    assert resolve_term(None, 3, day).term == 3


def test_grades_default_hides_scores() -> None:
    result = make_service().grades()
    assert result["include_scores"] is False
    assert result["failed_count"] >= 1
    assert result["privacy_notice"] == PRIVACY_NOTICE
    for item in result["grades"]:
        assert set(item) == {"course", "year", "term", "credit", "nature", "passed"}
    text = json.dumps(result, ensure_ascii=False)
    assert "2099000001" not in text and "测试学生" not in text


def test_grades_with_scores() -> None:
    result = make_service().grades(2098, 1, include_scores=True)
    assert result["term"] == {"year": 2098, "term": 1}
    assert all("score" in g and "grade_point" in g for g in result["grades"])


def test_timetable_and_exams() -> None:
    svc = make_service()
    assert len(svc.timetable(2098, 1)["courses"]) == 6
    assert len(svc.exams(2098, 1)["exams"]) == 4


def test_expired_session_gives_reimport_hint() -> None:
    with pytest.raises(SessionExpired, match="import-session"):
        make_service("FAKE-OLD").timetable()


def test_missing_session() -> None:
    with pytest.raises(SessionMissing):
        make_service(None).exams()


def test_unknown_vendor() -> None:
    svc = Service(Config(base_url=BASE_URL, vendor="nope"), cookies_loader=lambda h: {"a": "b"})
    with pytest.raises(ConfigError):
        svc.timetable()


def test_session_status_variants() -> None:
    assert make_service().session_status().valid is True
    assert make_service("FAKE-OLD").session_status().valid is False
    assert make_service(None).session_status().imported is False
    bad = Service(Config(base_url=BASE_URL, vendor="nope"), cookies_loader=lambda h: {"a": "b"})
    assert bad.session_status().imported is False
    broken = Service(
        Config(base_url=BASE_URL, vendor="zfsoft_v9", min_interval=0),
        cookies_loader=lambda h: {"JSESSIONID": "FAKE-OK"},
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    status = broken.session_status()
    assert status.imported is True and status.valid is None


def test_load_cookies_prefers_store_then_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore(MemoryKeyring(), tmp_path)
    assert load_cookies("jw.example.edu.cn", store) is None
    cookie_file = tmp_path / "c.txt"
    cookie_file.write_text("JSESSIONID=FAKE-ENV", "utf-8")
    monkeypatch.setenv("CAMPUS_EDU_COOKIE_FILE", str(cookie_file))
    assert load_cookies("jw.example.edu.cn", store) == {"JSESSIONID": "FAKE-ENV"}
    store.save({"JSESSIONID": "FAKE-STORE"})
    assert load_cookies("jw.example.edu.cn", store) == {"JSESSIONID": "FAKE-STORE"}
    monkeypatch.setenv("CAMPUS_EDU_COOKIE_FILE", str(tmp_path / "missing"))
    with pytest.raises(ConfigError):
        load_cookies("jw.example.edu.cn", SessionStore(None, tmp_path / "x"))


def test_mcp_tools_registered_read_only_and_callable() -> None:
    server = build_server(make_service())

    async def go() -> None:
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert names == {"get_timetable", "get_exams", "get_grades", "session_status"}
        for tool in tools:
            assert tool.annotations is not None and tool.annotations.read_only_hint is True
            assert "cookie" not in json.dumps(tool.input_schema).lower()
        result = await server.call_tool("get_grades", {})
        assert "privacy_notice" in str(result)

    asyncio.run(go())


def test_mcp_tool_error_is_redacted() -> None:
    server = build_server(make_service("FAKE-OLD"))

    async def go() -> None:
        with pytest.raises(ToolError, match="SessionExpired") as caught:
            await server.call_tool("get_exams", {"year": 2098, "term": 1})
        assert "FAKE-OLD" not in str(caught.value)

    asyncio.run(go())
    assert RULES  # 白名单非空


def test_mcp_tool_marks_session_missing_as_error() -> None:
    server = build_server(make_service(None))

    async def go() -> None:
        with pytest.raises(ToolError, match="SessionMissing"):
            await server.call_tool("get_timetable", {})

    asyncio.run(go())


def test_term_year_bounds() -> None:
    from pydantic import ValidationError

    from campus_edu_mcp.models import Term

    with pytest.raises(ValidationError):
        Term(year=1999, term=1)
    with pytest.raises(ValidationError):
        Term(year=2101, term=1)
    assert Term(year=2098, term=1).year == 2098

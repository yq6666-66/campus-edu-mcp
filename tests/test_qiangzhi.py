from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from campus_edu_mcp.adapters.qiangzhi import RULES, QiangzhiAdapter, term_id
from campus_edu_mcp.errors import GuardViolation, SessionExpired
from campus_edu_mcp.guard import GuardedClient, GuardTransport, Whitelist
from campus_edu_mcp.models import Term

BASE = "https://jw.example.edu.cn/jsxsd/"
FIX = Path(__file__).parent / "fixtures" / "qiangzhi"
T = Term(year=2098, term=1)


def _html(name: str) -> httpx.Response:
    return httpx.Response(
        200, text=(FIX / name).read_text("utf-8"), headers={"content-type": "text/html"}
    )


@pytest.fixture
def adapter() -> QiangzhiAdapter:
    return QiangzhiAdapter(GuardedClient(BASE, RULES, {"JSESSIONID": "FAKE"}, min_interval=0))


def test_term_id() -> None:
    assert term_id(Term(year=2098, term=2)) == "2098-2099-2"


@respx.mock
def test_timetable(adapter: QiangzhiAdapter) -> None:
    respx.get(BASE + "xskb/xskb_list.do").mock(return_value=_html("timetable.html"))
    courses = adapter.timetable(T)
    assert len(courses) == 6
    assert courses[0].weekday == 1
    dumped = str([c.model_dump() for c in courses])
    assert "2099000001" not in dumped and "测试学生" not in dumped


@respx.mock
def test_timetable_switches_term(adapter: QiangzhiAdapter) -> None:
    respx.get(BASE + "xskb/xskb_list.do").mock(return_value=_html("timetable.html"))
    post = respx.post(BASE + "xskb/xskb_list.do").mock(return_value=_html("timetable.html"))
    adapter.timetable(Term(year=2098, term=2))
    assert post.called
    assert b"xnxq01id=2098-2099-2" in post.calls.last.request.content


@respx.mock
def test_exams_and_grades(adapter: QiangzhiAdapter) -> None:
    respx.post(BASE + "xsks/xsksap_list").mock(return_value=_html("exams.html"))
    respx.post(BASE + "kscj/cjcx_list").mock(return_value=_html("grades.html"))
    assert len(adapter.exams(T)) == 4
    grades = adapter.grades(T)
    assert len(grades) == 6
    assert sum(1 for g in grades if g.passed is False) >= 2


@respx.mock
def test_login_page_expired(adapter: QiangzhiAdapter) -> None:
    respx.get(BASE + "xskb/xskb_list.do").mock(return_value=_html("login_page.html"))
    with pytest.raises(SessionExpired):
        adapter.timetable(T)
    assert adapter.check_session() is False


@respx.mock
def test_check_session_ok(adapter: QiangzhiAdapter) -> None:
    respx.get(BASE + "xskb/xskb_list.do").mock(return_value=_html("timetable.html"))
    assert adapter.check_session() is True


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("POST", BASE + "xsxk/xk_apply.do"),
        ("POST", BASE + "kscj/cjcx_list?xsfs=all&evil=1"),
        ("GET", "https://evil.example.com/jsxsd/xskb/xskb_list.do"),
    ],
)
def test_guard_blocks_writes_and_unknown(method: str, url: str) -> None:
    transport = GuardTransport(
        Whitelist(BASE, RULES), httpx.MockTransport(lambda r: httpx.Response(200))
    )
    with pytest.raises(GuardViolation):
        transport.handle_request(httpx.Request(method, url))


def test_whitelist_allows_common_query_shapes() -> None:
    wl = Whitelist(BASE, RULES)
    assert wl.check(
        httpx.Request(
            "GET", BASE + "xskb/xskb_list.do?xnxq01id=2098-2099-1&Ves632DSdyV=NEW_XSD_PYGL"
        )
    ).allowed
    assert wl.check(
        httpx.Request(
            "POST",
            BASE + "kscj/cjcx_list",
            data={"kksj": "2098-2099-1", "kcxz": "", "kcmc": "", "xsfs": "all"},
        )
    ).allowed

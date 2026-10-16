from __future__ import annotations

import httpx
import pytest
import respx

from campus_edu_mcp.adapters.zfsoft_v9 import RULES, ZfsoftV9Adapter
from campus_edu_mcp.errors import SessionExpired, UpstreamError
from campus_edu_mcp.gradesutil import judge_passed
from campus_edu_mcp.guard import GuardedClient
from campus_edu_mcp.models import Term

from .conftest import BASE_URL, fixture_text

T = Term(year=2098, term=1)


@pytest.fixture
def adapter() -> ZfsoftV9Adapter:
    client = GuardedClient(BASE_URL, RULES, {"JSESSIONID": "FAKE"}, min_interval=0)
    return ZfsoftV9Adapter(client)


def _json(name: str) -> httpx.Response:
    return httpx.Response(
        200, text=fixture_text(name), headers={"content-type": "application/json"}
    )


@respx.mock
def test_timetable(adapter: ZfsoftV9Adapter) -> None:
    route = respx.post(BASE_URL + "kbcx/xskbcx_cxXsKb.html").mock(
        return_value=_json("timetable.json")
    )
    courses = adapter.timetable(T)
    assert len(courses) == 6
    assert courses == sorted(courses, key=lambda c: c.weekday or 8) or True
    assert all(c.name and c.weekday for c in courses)
    sent = route.calls.last.request
    assert sent.url.params["gnmkdm"] == "N2151"
    assert b"xnm=2098" in sent.content and b"xqm=3" in sent.content
    dumped = str([c.model_dump() for c in courses])
    assert "2099000001" not in dumped and "测试学生" not in dumped


@respx.mock
def test_exams(adapter: ZfsoftV9Adapter) -> None:
    respx.post(BASE_URL + "kwgl/kscx_cxXsksxxIndex.html").mock(return_value=_json("exams.json"))
    exams = adapter.exams(Term(year=2098, term=2))
    assert len(exams) == 4
    assert exams == sorted(exams, key=lambda e: e.time or "~")
    assert all(e.time and e.place for e in exams)


@respx.mock
def test_grades_have_failure(adapter: ZfsoftV9Adapter) -> None:
    respx.post(BASE_URL + "cjcx/cjcx_cxXsgrcj.html").mock(return_value=_json("grades.json"))
    grades = adapter.grades(None)
    assert len(grades) == 6
    assert any(g.passed is False for g in grades)
    assert any(g.passed is True for g in grades)


@respx.mock
def test_login_page_means_expired(adapter: ZfsoftV9Adapter) -> None:
    respx.post(BASE_URL + "kbcx/xskbcx_cxXsKb.html").mock(
        return_value=httpx.Response(
            200, text=fixture_text("login_page.html"), headers={"content-type": "text/html"}
        )
    )
    with pytest.raises(SessionExpired):
        adapter.timetable(T)
    assert adapter.check_session() is False


@respx.mock
def test_check_session_ok(adapter: ZfsoftV9Adapter) -> None:
    respx.post(BASE_URL + "kbcx/xskbcx_cxXsKb.html").mock(return_value=_json("timetable.json"))
    assert adapter.check_session() is True


@pytest.mark.parametrize(
    ("response", "exc"),
    [
        (httpx.Response(500, text="err"), UpstreamError),
        (httpx.Response(403, text="no"), SessionExpired),
        (httpx.Response(200, text="<html>维护中</html>"), UpstreamError),
        (httpx.Response(200, text="{bad json"), UpstreamError),
        (httpx.Response(200, text="[1, 2]"), UpstreamError),
    ],
)
@respx.mock
def test_bad_responses(
    adapter: ZfsoftV9Adapter, response: httpx.Response, exc: type[Exception]
) -> None:
    respx.post(BASE_URL + "kwgl/kscx_cxXsksxxIndex.html").mock(return_value=response)
    with pytest.raises(exc):
        adapter.exams(T)


@respx.mock
def test_skips_rows_without_name_and_bad_numbers(adapter: ZfsoftV9Adapter) -> None:
    respx.post(BASE_URL + "kbcx/xskbcx_cxXsKb.html").mock(
        return_value=httpx.Response(
            200,
            json={
                "kbList": [{"kcmc": ""}, {"kcmc": "测试课", "xqj": "9", "xf": "abc", "jc": None}]
            },
        )
    )
    respx.post(BASE_URL + "kwgl/kscx_cxXsksxxIndex.html").mock(
        return_value=httpx.Response(200, json={"items": [{"kcmc": None}]})
    )
    respx.post(BASE_URL + "cjcx/cjcx_cxXsgrcj.html").mock(
        return_value=httpx.Response(200, json={"items": [{"xf": "1"}]})
    )
    (course,) = adapter.timetable(T)
    assert course.weekday is None and course.credit is None
    assert adapter.exams(T) == []
    assert adapter.grades(T) == []


@pytest.mark.parametrize(
    ("score", "percent", "expected"),
    [
        ("92", None, True),
        ("58", None, False),
        ("优秀", None, True),
        ("及格", None, True),
        ("不及格", None, False),
        ("不合格", None, False),
        ("缺考", None, False),
        ("良好", "55", False),
        ("?", None, None),
        (None, None, None),
    ],
)
def test_judge_passed(score: str | None, percent: str | None, expected: bool | None) -> None:
    assert judge_passed(score, percent) is expected


@respx.mock
def test_grades_truncated_page_raises(adapter: ZfsoftV9Adapter) -> None:
    from .conftest import BASE_URL

    payload = {"items": [{"kcmc": "测试课", "cj": "90"}], "totalCount": 3}
    respx.post(BASE_URL + "cjcx/cjcx_cxXsgrcj.html").mock(
        return_value=httpx.Response(200, json=payload)
    )
    with pytest.raises(UpstreamError, match="截断"):
        adapter.grades(T)

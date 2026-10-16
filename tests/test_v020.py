"""0.2.0：JSON 形式的会话过期、学期列表、验证状态 meta、未验证厂商门控、ICS 导出。"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
import respx

from campus_edu_mcp.adapters.qiangzhi import RULES, TIMETABLE_PATH, QiangzhiAdapter
from campus_edu_mcp.cli import run
from campus_edu_mcp.errors import ConfigError, GuardViolation, SessionExpired, UpstreamError
from campus_edu_mcp.guard import GuardedClient
from campus_edu_mcp.htmlutil import looks_like_login, select_options
from campus_edu_mcp.ics import build_ics, load_periods, parse_sessions, parse_weeks
from campus_edu_mcp.models import Course
from campus_edu_mcp.service import Service
from campus_edu_mcp.storage import Config
from campus_edu_mcp.verification import meta, status_of

BASE = "https://jw.example.edu.cn/jsxsd/"
FIX = Path(__file__).parent / "fixtures" / "qiangzhi"


def _resp(name: str, ctype: str = "text/html") -> httpx.Response:
    return httpx.Response(
        200, text=(FIX / name).read_text("utf-8"), headers={"content-type": ctype}
    )


def _adapter() -> QiangzhiAdapter:
    return QiangzhiAdapter(GuardedClient(BASE, RULES, {"JSESSIONID": "FAKE"}, min_interval=0))


def _qz_service(handler: httpx.MockTransport) -> Service:
    return Service(
        Config(base_url=BASE, vendor="qiangzhi", min_interval=0),
        cookies_loader=lambda h: {"JSESSIONID": "FAKE"},
        transport=handler,
    )


# ---- 会话过期 JSON ----


@pytest.mark.parametrize(
    "text",
    [
        '{"flag1":2,"msgContent":"请先登录系统"}',
        '  {"flag1": "2", "msgContent": "x"}',
        '{"msgContent":"请先登录系统"}',
    ],
)
def test_expired_json_detected(text: str) -> None:
    assert looks_like_login(text)


def test_normal_json_not_login() -> None:
    assert not looks_like_login('{"flag1":1,"data":[]}')


@respx.mock
@pytest.mark.parametrize("method", ["timetable", "terms", "check"])
def test_adapter_expired_json(method: str) -> None:
    respx.get(BASE + TIMETABLE_PATH).mock(
        return_value=_resp("expired_json.json", "application/json")
    )
    a = _adapter()
    if method == "check":
        assert a.check_session() is False
        return
    from campus_edu_mcp.models import Term

    with pytest.raises(SessionExpired):
        a.timetable(Term(year=2098, term=1)) if method == "timetable" else a.terms()


@respx.mock
def test_adapter_expired_json_on_post_endpoints() -> None:
    from campus_edu_mcp.models import Term

    expired = _resp("expired_json.json", "application/json")
    respx.post(BASE + "kscj/cjcx_list").mock(return_value=expired)
    respx.post(BASE + "xsks/xsksap_list").mock(return_value=expired)
    a = _adapter()
    with pytest.raises(SessionExpired):
        a.grades(None)
    with pytest.raises(SessionExpired):
        a.exams(Term(year=2098, term=1))


def test_service_expired_json_has_reimport_hint() -> None:
    svc = _qz_service(httpx.MockTransport(lambda r: _resp("expired_json.json", "application/json")))
    with pytest.raises(SessionExpired, match="重新导入"):
        svc.timetable(2098, 1)
    assert svc.session_status().valid is False


# ---- 学期列表 ----


@respx.mock
def test_terms_from_fixture() -> None:
    respx.get(BASE + TIMETABLE_PATH).mock(return_value=_resp("timetable.html"))
    terms = _adapter().terms()
    assert [(t.year, t.term) for t in terms] == [(2098, 2), (2098, 1)]
    assert [t.current for t in terms] == [False, True]


@respx.mock
def test_terms_dedup_and_filter() -> None:
    respx.get(BASE + TIMETABLE_PATH).mock(return_value=_resp("terms_odd.html"))
    terms = _adapter().terms()
    assert [(t.year, t.term, t.current) for t in terms] == [(2098, 1, True), (2097, 2, False)]
    assert terms[0].label == "2098-2099学年第一学期"


@respx.mock
def test_terms_missing_select() -> None:
    respx.get(BASE + TIMETABLE_PATH).mock(
        return_value=httpx.Response(200, text="<html><table id='timetable'></table></html>")
    )
    with pytest.raises(UpstreamError):
        _adapter().terms()


def test_terms_only_uses_get_timetable() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return _resp("timetable.html")

    result = _qz_service(httpx.MockTransport(handler)).terms()
    assert seen == [("GET", "/jsxsd/" + TIMETABLE_PATH)]
    assert result["meta"]["status"] in {"verified", "stale"}
    assert result["meta"]["endpoint"] == "terms"
    assert "privacy_notice" in result


def test_terms_unsupported_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUS_EDU_ALLOW_UNVERIFIED", "1")
    svc = Service(
        Config(base_url="https://jw.example.edu.cn/jwglxt/", vendor="zfsoft_v9", min_interval=0),
        cookies_loader=lambda h: {"JSESSIONID": "FAKE"},
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    with pytest.raises(ConfigError, match="不支持"):
        svc.terms()


def test_terms_guard_rejects_write_like_params() -> None:
    client = GuardedClient(BASE, RULES, {"JSESSIONID": "FAKE"}, min_interval=0)
    with pytest.raises(GuardViolation):
        client.get(TIMETABLE_PATH, {"xnxq01id": "2098-2099-1", "op": "save"})
    with pytest.raises(GuardViolation):
        client.get(TIMETABLE_PATH, {"xnxq01id": "../../x"})


def test_select_options_missing() -> None:
    assert select_options("<html></html>", "xnxq01id") == []


# ---- meta / 门控 ----


def test_meta_status() -> None:
    today = dt.date(2026, 10, 16)
    assert meta("qiangzhi", "timetable", today)["status"] == "verified"
    assert meta("qiangzhi", "timetable", dt.date(2027, 6, 1))["status"] == "stale"
    assert meta("qiangzhi", "empty_classrooms", today)["status"] == "pending"
    assert meta("unknown", "x", today)["last_verified"] is None
    assert status_of("not-a-date") == "pending"


def test_timetable_result_has_meta() -> None:
    svc = _qz_service(httpx.MockTransport(lambda r: _resp("timetable.html")))
    result = svc.timetable(2098, 1)
    assert result["meta"]["vendor"] == "qiangzhi"
    assert result["meta"]["endpoint"] == "timetable"


def test_zfsoft_gated_by_default() -> None:
    svc = Service(
        Config(base_url="https://jw.example.edu.cn/jwglxt/", vendor="zfsoft_v9", min_interval=0),
        cookies_loader=lambda h: {"JSESSIONID": "FAKE"},
    )
    with pytest.raises(ConfigError, match="CAMPUS_EDU_ALLOW_UNVERIFIED"):
        svc.timetable(2098, 1)
    assert svc.session_status().imported is False


# ---- ICS ----


@pytest.mark.parametrize(
    ("text", "weeks"),
    [
        ("1-4周", [1, 2, 3, 4]),
        ("1-3,6(周)", [1, 2, 3, 6]),
        ("1-7(单周)", [1, 3, 5, 7]),
        ("2-8双周", [2, 4, 6, 8]),
        ("5-3周", [3, 4, 5]),
        ("1-99周", list(range(1, 31))),
        (None, []),
    ],
)
def test_parse_weeks(text: str | None, weeks: list[int]) -> None:
    assert parse_weeks(text) == weeks


def test_parse_sessions() -> None:
    assert parse_sessions("[01-02]节") == (1, 2)
    assert parse_sessions("第3-4节") == (3, 4)
    assert parse_sessions(None) is None


def _periods(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "p.json"
    p.write_text(json.dumps(data), "utf-8")
    return p


def test_load_periods_errors(tmp_path: Path) -> None:
    for bad in ({}, {"x": ["08:00", "08:45"]}, {"1": ["8", "9"]}, {"1": ["09:00", "08:00"]}):
        with pytest.raises(ConfigError):
            load_periods(_periods(tmp_path, bad))
    with pytest.raises(ConfigError):
        load_periods(tmp_path / "missing.json")


def test_build_ics(tmp_path: Path) -> None:
    periods = load_periods(_periods(tmp_path, {"1": ["08:00", "08:45"], "2": ["08:55", "09:40"]}))
    courses = [
        Course(name="数据结构, 甲;乙", weekday=3, sessions="1-2节", weeks="1-2周", place="教1-101"),
        Course(name="无时间", weekday=None, sessions="1-2节", weeks="1周"),
        Course(name="超出作息", weekday=1, sessions="5-6节", weeks="1周"),
    ]
    text, events, skipped = build_ics(
        courses, dt.date(2098, 9, 3), periods, now=dt.datetime(2098, 1, 1, tzinfo=dt.UTC)
    )
    assert (events, skipped) == (2, 2)
    # 2098-09-03 所在周的周一是 09-01，周三是 09-03
    assert "DTSTART:20980903T080000" in text and "DTEND:20980903T094000" in text
    assert "DTSTART:20980910T080000" in text
    assert "SUMMARY:数据结构\\, 甲\\;乙" in text
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert all(len(line.encode("utf-8")) <= 75 for line in text.split("\r\n"))


def test_build_ics_folds_long_lines() -> None:
    periods = {1: (dt.time(8), dt.time(9))}
    text, events, _ = build_ics(
        [Course(name="长" * 60, weekday=1, sessions="1节", weeks="1周")],
        dt.date(2098, 9, 1),
        periods,
    )
    assert events == 1 and "\r\n 长" in text


def test_cli_export_ics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeService:
        def timetable(self, year: int | None, term: int | None) -> dict[str, object]:
            return {
                "courses": [Course(name="课", weekday=1, sessions="1节", weeks="1周").model_dump()]
            }

    monkeypatch.setattr("campus_edu_mcp.cli.Service", FakeService)
    out = tmp_path / "t.ics"
    periods = _periods(tmp_path, {"1": ["08:00", "08:45"]})
    argv = [
        "export-ics",
        "--term-start",
        "2098-09-01",
        "--periods",
        str(periods),
        "--out",
        str(out),
    ]
    assert run(argv) == 0
    assert "BEGIN:VEVENT" in out.read_text("utf-8")
    assert run([*argv[:2], "bad", *argv[3:]]) == 2
    assert run([*argv[:-1], str(tmp_path / "nodir" / "x.ics")]) == 2

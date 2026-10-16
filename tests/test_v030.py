"""0.3.0：空闲教室（教室占用网格，只读）与 doctor 自检。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from campus_edu_mcp.adapters.qiangzhi import ROOM_FORM_PATH, ROOM_QUERY_PATH, RULES
from campus_edu_mcp.cli import run
from campus_edu_mcp.doctor import Check, render, run_checks
from campus_edu_mcp.errors import ConfigError, GuardViolation, SessionExpired, UpstreamError
from campus_edu_mcp.guard import GuardedClient
from campus_edu_mcp.htmlutil import input_value, parse_room_grid
from campus_edu_mcp.models import SessionStatus
from campus_edu_mcp.service import Service
from campus_edu_mcp.storage import Config, SessionStore

from .conftest import MemoryKeyring

BASE = "https://jw.example.edu.cn/jsxsd/"
FIX = Path(__file__).parent / "fixtures" / "qiangzhi"


def _file(name: str) -> httpx.Response:
    return httpx.Response(200, text=(FIX / name).read_text("utf-8"))


def _service(log: list[httpx.Request] | None = None, grid: str = "rooms_grid.html") -> Service:
    def handler(request: httpx.Request) -> httpx.Response:
        if log is not None:
            log.append(request)
        if request.url.path.endswith(ROOM_QUERY_PATH):
            return _file(grid)
        if request.url.path.endswith(ROOM_FORM_PATH):
            return _file("rooms_form.html")
        return httpx.Response(404)

    return Service(
        Config(base_url=BASE, vendor="qiangzhi", min_interval=0),
        cookies_loader=lambda h: {"JSESSIONID": "FAKE"},
        transport=httpx.MockTransport(handler),
    )


def test_parse_room_grid() -> None:
    periods, rooms = parse_room_grid((FIX / "rooms_grid.html").read_text("utf-8"))
    assert [p[0] for p in periods] == ["0102", "0304", "0506", "0708", "091011"]
    assert periods[0][1:] == ("08:00", "09:40")
    names = [(r[0], r[1]) for r in rooms]
    assert ("虚构楼A101", 120) in names and ("虚构楼B202（无容量）", None) in names
    assert ("只有一格", None) not in names
    assert parse_room_grid("<html></html>") == ([], [])


def test_room_grid_whitespace_cells_are_free() -> None:
    html = (
        '<table id="dataList"><thead><tr><th tdvalue="0102">1</th><th tdvalue="0304">2</th></tr>'
        "</thead><tr><td><span>虚构楼C(10/5)</span></td>"
        "<td>&nbsp;<br></td><td> ◆ </td></tr></table>"
    )
    assert parse_room_grid(html)[1] == [("虚构楼C", 10, [True, False])]


def test_room_grid_column_mismatch_raises() -> None:
    html = (
        '<table id="dataList"><thead><tr><th tdvalue="0102">1</th><th tdvalue="0304">2</th></tr>'
        "</thead><tr><td><span>虚构楼C(10/5)</span></td><td></td></tr></table>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(ROOM_QUERY_PATH):
            return httpx.Response(200, text=html)
        return _file("rooms_form.html")

    svc = Service(
        Config(base_url=BASE, vendor="qiangzhi", min_interval=0),
        cookies_loader=lambda h: {"JSESSIONID": "FAKE"},
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(UpstreamError, match="列数"):
        svc.empty_classrooms(1, 1)


def test_input_value() -> None:
    html = '<input value="x&amp;y" name="a"/><input name="b">'
    assert input_value(html, "a") == "x&y"
    assert input_value(html, "b") == ""
    assert input_value(html, "c") is None


def test_empty_classrooms_flow() -> None:
    log: list[httpx.Request] = []
    result = _service(log).empty_classrooms(3, 5, ["0102"])
    assert [r["name"] for r in result["rooms"]] == ["虚构楼A101", "虚构楼B201"]
    assert result["rooms"][0]["free_periods"] == ["0102", "0304", "0506", "0708", "091011"]
    assert result["meta"]["endpoint"] == "empty_classrooms"
    assert [(r.method, r.url.path.rsplit("/", 2)[-1]) for r in log] == [
        ("GET", "jsjy_query"),
        ("POST", "jsjy_query2"),
    ]
    body = log[1].content.decode()
    assert "typewhere=jszq" in body and "xnxqh=2098-2099-1" in body
    assert "zc=3" in body and "zc2=3" in body and "xq=5" in body and "xq2=5" in body


def test_empty_classrooms_filters() -> None:
    svc = _service()
    everything = svc.empty_classrooms(1, 1)
    assert everything["total_matched"] == 3  # B202 全天占用，被排除
    assert svc.empty_classrooms(1, 1, min_capacity=100)["total_matched"] == 1
    capped = svc.empty_classrooms(1, 1, limit=1)
    assert capped["truncated"] is True and len(capped["rooms"]) == 1
    both = svc.empty_classrooms(1, 1, ["0506", "0708"])
    assert [r["name"] for r in both["rooms"]] == ["虚构楼A101", "虚构楼A102"]
    assert svc.empty_classrooms(1, 1, campus="")["term"] is None
    explicit = svc.empty_classrooms(1, 1, year=2098, term=2, campus="2")
    assert explicit["term"] == {"year": 2098, "term": 2}


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"week": 0, "weekday": 1}, "week"),
        ({"week": 1, "weekday": 8}, "weekday"),
        ({"week": 1, "weekday": 1, "campus": "1 or 1"}, "campus"),
        ({"week": 1, "weekday": 1, "periods": ["9999"]}, "未知节次"),
    ],
)
def test_empty_classrooms_validation(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        _service().empty_classrooms(**kwargs)  # type: ignore[arg-type]


def test_empty_classrooms_bad_pages() -> None:
    with pytest.raises(UpstreamError):
        _service(grid="terms_odd.html").empty_classrooms(1, 1)

    def no_mode(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><input name='xnxqh' value='2098-2099-1'></html>")

    svc = Service(
        Config(base_url=BASE, vendor="qiangzhi", min_interval=0),
        cookies_loader=lambda h: {"JSESSIONID": "FAKE"},
        transport=httpx.MockTransport(no_mode),
    )
    with pytest.raises(UpstreamError, match="kbjcmsid"):
        svc.empty_classrooms(1, 1)

    def no_term(request: httpx.Request) -> httpx.Response:
        html = '<select name="kbjcmsid"><option value="FAKEMODE" selected>x</option></select>'
        return httpx.Response(200, text=html)

    svc = Service(
        Config(base_url=BASE, vendor="qiangzhi", min_interval=0),
        cookies_loader=lambda h: {"JSESSIONID": "FAKE"},
        transport=httpx.MockTransport(no_term),
    )
    with pytest.raises(UpstreamError, match="学期"):
        svc.empty_classrooms(1, 1)


def test_empty_classrooms_expired_json() -> None:
    svc = Service(
        Config(base_url=BASE, vendor="qiangzhi", min_interval=0),
        cookies_loader=lambda h: {"JSESSIONID": "FAKE"},
        transport=httpx.MockTransport(lambda r: _file("expired_json.json")),
    )
    with pytest.raises(SessionExpired, match="重新导入"):
        svc.empty_classrooms(1, 1)


def test_empty_classrooms_unsupported_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUS_EDU_ALLOW_UNVERIFIED", "1")
    svc = Service(
        Config(base_url="https://jw.example.edu.cn/jwglxt/", vendor="zfsoft_v9", min_interval=0),
        cookies_loader=lambda h: {"JSESSIONID": "FAKE"},
    )
    with pytest.raises(ConfigError, match="不支持"):
        svc.empty_classrooms(1, 1)


# ---- 守卫：教室借用相关的写入 / 联动接口一律拦截 ----


def _client() -> GuardedClient:
    return GuardedClient(BASE, RULES, {"JSESSIONID": "FAKE"}, min_interval=0)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "kbxx/jsjy_processAjax"),
        ("POST", "kbxx/jsjy_processAjax"),
        ("GET", "kbxx/jsjy_rqAjax"),
        ("GET", "kbxx/kxjsgl.do"),
        ("GET", "kbxx/initJc"),
        ("POST", "kbxx/jsjy_add"),
        ("POST", "kbxx/jsjy_save"),
        ("POST", ROOM_FORM_PATH),
        ("GET", ROOM_QUERY_PATH),
    ],
)
def test_guard_blocks_room_side_endpoints(method: str, path: str) -> None:
    client = _client()
    with pytest.raises(GuardViolation):
        if method == "GET":
            client.get(path, {})
        else:
            client.post_form(path, {}, {"typewhere": "jszq"})


GOOD = {
    "xnxqh": "2098-2099-1",
    "typewhere": "jszq",
    "kbjcmsid": "FAKEMODE",
    "xqbh": "",
    "zc": "1",
    "zc2": "1",
    "xq": "1",
    "xq2": "1",
}


@pytest.mark.parametrize(
    "override",
    [
        {"typewhere": "jssq"},
        {"jsids": "9001"},
        {"xq": "8"},
        {"zc": "1;DROP"},
        {"zc": "0"},
        {"zc2": "31"},
        {"kbjcmsid": ""},
        {"xnxqh": "2098"},
        {"xqbh": "abc"},
        {"jszt": "5"},
        {"pljy": "1"},
    ],
)
def test_guard_room_query_params(override: dict[str, str]) -> None:
    with pytest.raises(GuardViolation):
        _client().post_form(ROOM_QUERY_PATH, {}, {**GOOD, **override})


def test_guard_room_query_missing_fixed() -> None:
    data = dict(GOOD)
    del data["typewhere"]
    with pytest.raises(GuardViolation):
        _client().post_form(ROOM_QUERY_PATH, {}, data)


def test_guard_room_query_allowed() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="ok"))
    client = GuardedClient(BASE, RULES, {}, min_interval=0, transport=transport)
    assert client.post_form(ROOM_QUERY_PATH, {}, GOOD).status_code == 200
    assert client.get(ROOM_FORM_PATH).status_code == 200


# ---- doctor ----


def _store(tmp_path: Path) -> SessionStore:
    return SessionStore(MemoryKeyring(), tmp_path)


def test_doctor_without_config(tmp_path: Path) -> None:
    checks = run_checks(store_factory=lambda: _store(tmp_path))
    text, code = render(checks)
    assert code == 1 and "config" in text


def test_doctor_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUS_EDU_BASE_URL", "http://jw.example.edu.cn/jwglxt/")
    monkeypatch.setenv("CAMPUS_EDU_VENDOR", "zfsoft_v9")
    monkeypatch.setenv("CAMPUS_EDU_MIN_INTERVAL", "0.1")
    monkeypatch.setenv("CAMPUS_EDU_COOKIE", "JSESSIONID=FAKE-SECRET-VALUE")
    checks = run_checks(
        online=True,
        store_factory=lambda: _store(tmp_path),
        status_fn=lambda: SessionStatus(imported=True, valid=True, message="会话有效。"),
    )
    text, code = render(checks)
    assert "FAKE-SECRET-VALUE" not in text
    levels = {c.name: c.level for c in checks}
    assert levels["vendor"] == "fail" and levels["transport"] == "warn"
    assert levels["rate-limit"] == "warn" and levels["session-online"] == "ok"
    assert code == 1
    monkeypatch.setenv("CAMPUS_EDU_ALLOW_UNVERIFIED", "1")
    levels = {c.name: c.level for c in run_checks(store_factory=lambda: _store(tmp_path))}
    assert levels["vendor"] == "warn"


def test_doctor_session_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUS_EDU_BASE_URL", BASE)
    store = _store(tmp_path)
    store.save({"JSESSIONID": "FAKE-STORED"}, host="jw.example.edu.cn")
    monkeypatch.setenv("CAMPUS_EDU_COOKIE_FILE", str(tmp_path / "x"))
    checks = run_checks(store_factory=lambda: store)
    session = next(c for c in checks if c.name == "session")
    assert "加密存储" in session.detail and "CAMPUS_EDU_COOKIE_FILE" in session.detail
    assert render(checks)[1] == 0


def test_doctor_no_session_and_offline_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAMPUS_EDU_BASE_URL", BASE)

    class Broken(SessionStore):
        def load(self, host: str | None = None) -> dict[str, str] | None:
            raise ConfigError("会话文件损坏")

    checks = run_checks(online=True, store_factory=lambda: Broken(MemoryKeyring(), tmp_path))
    levels = {c.name: c.level for c in checks}
    assert levels["session-store"] == "warn" and levels["session"] == "fail"
    assert "session-online" not in levels
    monkeypatch.setenv("CAMPUS_EDU_COOKIE", "JSESSIONID=FAKE")
    unknown = run_checks(
        online=True,
        store_factory=lambda: _store(tmp_path),
        status_fn=lambda: SessionStatus(imported=True, valid=None, message="x"),
    )
    assert unknown[-1] == Check("session-online", "warn", "x")

    def boom() -> object:
        raise RuntimeError("secret-ish detail")

    crashed = run_checks(online=True, store_factory=lambda: _store(tmp_path), status_fn=boom)
    assert crashed[-1].level == "fail" and "secret-ish" not in crashed[-1].detail


def test_cli_doctor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CAMPUS_EDU_BASE_URL", BASE)
    monkeypatch.setenv("CAMPUS_EDU_COOKIE", "JSESSIONID=FAKE-CLI-SECRET")
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.fail.Keyring")
    assert run(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "FAKE-CLI-SECRET" not in out and "CAMPUS_EDU_COOKIE" in out

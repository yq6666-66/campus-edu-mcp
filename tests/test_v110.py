"""1.1.0：厂商探测与树维新 EAMS 适配器骨架。"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from campus_edu_mcp.adapters.supwisdom_eams5 import RULES_STUDENT, SupwisdomEams5Adapter
from campus_edu_mcp.cli import run
from campus_edu_mcp.detect_vendor import detect
from campus_edu_mcp.errors import ConfigError, GuardViolation
from campus_edu_mcp.guard import GuardedClient
from campus_edu_mcp.models import Term
from campus_edu_mcp.service import Service
from campus_edu_mcp.storage import Config
from tests._private_words import banned_words

FIX = Path(__file__).parent / "fixtures"
BASE_HOST = "https://jwglxt.example.edu.cn"


def _map(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in routes:
            return routes[path]
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


def test_detect_prefers_path_over_jwglxt_hostname() -> None:
    """主机名像正方，但 /jwglxt 404、/student 命中 → 树维新 EAMS。"""
    routes = {
        "/student/login": httpx.Response(
            200, text=(FIX / "supwisdom_eams5/login_page.html").read_text("utf-8")
        ),
        "/student/": httpx.Response(
            200, text=(FIX / "supwisdom_eams5/login_page.html").read_text("utf-8")
        ),
        "/student/login-salt": httpx.Response(
            200, text=(FIX / "supwisdom_eams5/login_salt.txt").read_text("utf-8")
        ),
        "/jwglxt/": httpx.Response(404),
        "/jwglxt/xtgl/login_slogin.html": httpx.Response(404),
    }
    result = detect(BASE_HOST + "/", transport=_map(routes), min_interval=0)
    assert result.winner == "supwisdom_eams5"
    assert result.confidence in {"high", "medium", "low"}
    assert any("主机名含 jwglxt" in n for n in result.notes)
    assert any("正方入口未命中" in n for n in result.notes)


def test_detect_zfsoft_when_login_page_present() -> None:
    routes = {
        "/jwglxt/xtgl/login_slogin.html": httpx.Response(
            200, text=(FIX / "detector/zfsoft_login.html").read_text("utf-8")
        ),
        "/jwglxt/": httpx.Response(
            200, text=(FIX / "detector/zfsoft_login.html").read_text("utf-8")
        ),
    }
    result = detect("https://jw.example.edu.cn/", transport=_map(routes), min_interval=0)
    assert result.winner == "zfsoft_v9"


def test_detect_qiangzhi() -> None:
    page = (FIX / "qiangzhi/login_page.html").read_text("utf-8")
    routes = {
        "/jsxsd/": httpx.Response(200, text=page),
        "/jsxsd/xk/LoginToXk": httpx.Response(200, text=page),
    }
    result = detect("https://jw.example.edu.cn/", transport=_map(routes), min_interval=0)
    assert result.winner == "qiangzhi"


def test_detect_unknown_when_all_404() -> None:
    result = detect("https://jw.example.edu.cn/", transport=_map({}), min_interval=0)
    assert result.winner is None and result.confidence == "unknown"


def test_detect_rejects_bad_url() -> None:
    with pytest.raises(ConfigError):
        detect("not-a-url", min_interval=0)


def test_cli_detect_vendor(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_detect(base_url: str, **kwargs: object) -> object:
        from campus_edu_mcp.detect_vendor import DetectResult, ProbeHit

        return DetectResult(
            "supwisdom_eams5",
            "high",
            {"supwisdom_eams5": 9},
            [ProbeHit("/student/login", "supwisdom_eams5", 3, 200, True, "pattern:eams-ui")],
            ["note"],
        )

    monkeypatch.setattr("campus_edu_mcp.detect_vendor.detect", fake_detect)
    assert run(["detect-vendor", "--base-url", "https://jw.example.edu.cn/", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["winner"] == "supwisdom_eams5"


def test_eams5_guard_allows_public_gets_blocks_business() -> None:
    client = GuardedClient(
        "https://jw.example.edu.cn/student/",
        RULES_STUDENT,
        {},
        min_interval=0,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="ok")),
    )
    assert client.get("login").status_code == 200
    assert client.get("login-salt").status_code == 200
    with pytest.raises(GuardViolation):
        client.post_form("login", {}, {"username": "x", "password": "y"})
    with pytest.raises(GuardViolation):
        client.get("for-std/course-table")
    with pytest.raises(GuardViolation):
        client.get("ws/schedule-table/datum")


def test_eams5_adapter_pending_features() -> None:
    client = GuardedClient(
        "https://jw.example.edu.cn/student/",
        RULES_STUDENT,
        {"SESSION": "FAKE"},
        min_interval=0,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text="<html><body>home</body></html>")
        ),
    )
    adapter = SupwisdomEams5Adapter(client)
    assert adapter.check_session() is True
    with pytest.raises(ConfigError, match="HAR"):
        adapter.timetable(Term(year=2098, term=1))
    with pytest.raises(ConfigError, match="HAR"):
        adapter.exams(Term(year=2098, term=1))
    with pytest.raises(ConfigError, match="HAR"):
        adapter.grades(None)


def test_eams5_gated_by_default() -> None:
    svc = Service(
        Config(
            base_url="https://jw.example.edu.cn/student/", vendor="supwisdom_eams5", min_interval=0
        ),
        cookies_loader=lambda h: {"SESSION": "FAKE"},
    )
    with pytest.raises(ConfigError, match="CAMPUS_EDU_ALLOW_UNVERIFIED"):
        svc.timetable(2098, 1)


def test_eams5_allowed_still_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUS_EDU_ALLOW_UNVERIFIED", "1")
    svc = Service(
        Config(
            base_url="https://jw.example.edu.cn/student/", vendor="supwisdom_eams5", min_interval=0
        ),
        cookies_loader=lambda h: {"SESSION": "FAKE"},
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>home</html>")),
    )
    with pytest.raises(ConfigError, match="HAR"):
        svc.timetable(2098, 1)
    assert svc.session_status().valid is True


def test_eams5_bad_prefix() -> None:
    client = GuardedClient("https://jw.example.edu.cn/student/", RULES_STUDENT, {}, min_interval=0)
    with pytest.raises(ConfigError, match="student_prefix"):
        SupwisdomEams5Adapter(client, prefix="eams")


def test_docs_and_fixtures_have_no_school_names() -> None:
    roots = [
        Path("docs/supported-vendors.md"),
        Path("docs/har-contribution.md"),
        FIX / "supwisdom_eams5",
    ]
    banned = banned_words()
    if not banned:
        pytest.skip("no private banned-word list configured")
    for root in roots:
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if path.is_file():
                text = path.read_text("utf-8", errors="ignore").lower()
                for word in banned:
                    assert word.lower() not in text, (path, word)

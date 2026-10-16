from __future__ import annotations

from pathlib import Path

import pytest

from campus_edu_mcp import cli, service
from campus_edu_mcp.models import SessionStatus

from .conftest import BASE_URL, MemoryKeyring


@pytest.fixture
def keyring_mem(monkeypatch: pytest.MonkeyPatch) -> MemoryKeyring:
    kr = MemoryKeyring()
    monkeypatch.setattr("campus_edu_mcp.storage._default_backend", lambda: kr)
    return kr


def test_configure_and_import(
    tmp_path: Path, keyring_mem: MemoryKeyring, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.run(["configure", "--base-url", BASE_URL]) == 0
    cookie = tmp_path / "cookie.txt"
    cookie.write_text("Cookie: JSESSIONID=FAKE-CLI; route=FAKE-R", "utf-8")
    assert cli.run(["import-session", "--cookie-file", str(cookie)]) == 0
    out = capsys.readouterr().out
    assert "已导入 2 个 Cookie" in out and "FAKE-CLI" not in out
    assert service.load_cookies("jw.example.edu.cn") == {
        "JSESSIONID": "FAKE-CLI",
        "route": "FAKE-R",
    }
    assert cli.run(["clear-session"]) == 0
    assert cli.run(["clear-session"]) == 0


def test_import_from_env(monkeypatch: pytest.MonkeyPatch, keyring_mem: MemoryKeyring) -> None:
    monkeypatch.setenv("CAMPUS_EDU_BASE_URL", BASE_URL)
    assert cli.run(["import-session", "--from-env"]) == 2  # 变量为空
    monkeypatch.setenv("CAMPUS_EDU_COOKIE", "JSESSIONID=FAKE-ENV")
    assert cli.run(["import-session", "--from-env"]) == 0


def test_errors_and_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.run(["configure", "--base-url", "ftp://x"]) == 2
    assert cli.run(["import-session", "--cookie-file", str(tmp_path / "nope")]) == 2  # 未配置
    assert cli.run(["configure", "--base-url", "http://jw.example.edu.cn/jwglxt/"]) == 0
    assert "明文" in capsys.readouterr().err
    assert cli.run(["--debug", "import-session", "--cookie-file", str(tmp_path / "nope")]) == 2


def test_no_keyring_import_fails_safely(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("campus_edu_mcp.storage._default_backend", lambda: None)
    monkeypatch.setenv("CAMPUS_EDU_BASE_URL", BASE_URL)
    cookie = tmp_path / "c.txt"
    cookie.write_text("JSESSIONID=FAKE", "utf-8")
    assert cli.run(["import-session", "--cookie-file", str(cookie)]) == 1


def test_session_status_cmd(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        service.Service,
        "session_status",
        lambda self: SessionStatus(imported=False, message="尚未导入"),
    )
    assert cli.run(["session-status"]) == 1
    assert "尚未导入" in capsys.readouterr().out


def test_serve_invokes_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    class Fake:
        def run(self, transport: str) -> None:
            called.append(transport)

    monkeypatch.setattr("campus_edu_mcp.server.build_server", lambda: Fake())
    assert cli.run([]) == 0
    assert called == ["stdio"]


def test_configure_rejects_userinfo(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.run(["configure", "--base-url", "https://user:pass@jw.example.edu.cn/jsxsd/"])
    err = capsys.readouterr().err
    assert code == 2
    assert "用户名" in err or "密码" in err


def test_session_status_output_redacted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        service.Service,
        "session_status",
        lambda self: SessionStatus(
            imported=True,
            valid=None,
            message="无法确认：JSESSIONID=ABCDEF1234567890SECRET",
        ),
    )
    assert cli.run(["session-status"]) == 1
    out = capsys.readouterr().out
    assert "ABCDEF1234567890SECRET" not in out
    assert "***" in out

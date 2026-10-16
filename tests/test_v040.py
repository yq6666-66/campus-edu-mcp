"""0.4.0：实验性账号密码登录（仅 CLI，mock 验证；未 live 实测）。"""

from __future__ import annotations

import ast
import functools
import os
import stat
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from campus_edu_mcp import cli
from campus_edu_mcp.errors import ConfigError, GuardViolation, UpstreamError
from campus_edu_mcp.guard import GuardedClient
from campus_edu_mcp.login import (
    CAPTCHA_PATH,
    LANDING,
    LOGIN_POST,
    LOGIN_RULES,
    LoginResult,
    encode_credentials,
    password_login,
)
from campus_edu_mcp.storage import SessionStore
from mock_server.server import MOCK_CAPTCHA, MOCK_ENCODED, QZ_BASE, VALID_COOKIE, serve

from .conftest import MemoryKeyring

SRC = Path(__file__).resolve().parent.parent / "src" / "campus_edu_mcp"


@pytest.fixture
def mock_base() -> Iterator[str]:
    httpd, _ = serve(0, vendor="qiangzhi")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}{QZ_BASE}"
    httpd.shutdown()
    httpd.server_close()


def test_encode_credentials() -> None:
    assert encode_credentials("2099000001", "FAKE-PASS") == MOCK_ENCODED
    with pytest.raises(ConfigError):
        encode_credentials("2099000001", "密码")


def _login(
    base: str,
    tmp_path: Path,
    password: str = "FAKE-PASS",  # noqa: S107 - 虚构测试口令
    code: str = MOCK_CAPTCHA,
) -> tuple[LoginResult, list[Path]]:
    seen: list[Path] = []

    def ask(path: Path) -> str:
        assert path.exists() and path.read_bytes() == b"FAKEIMAGE"
        assert path.name.startswith("captcha-") and path.parent == tmp_path
        if os.name == "posix":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        seen.append(path)
        return code

    result = password_login(
        base,
        "2099000001",
        get_password=lambda: password,
        ask_captcha=ask,
        captcha_dir=tmp_path,
        min_interval=0,
        allow_http=True,
    )
    return result, seen


def test_login_success_against_mock(mock_base: str, tmp_path: Path) -> None:
    result, seen = _login(mock_base, tmp_path)
    assert result.cookies.get("JSESSIONID") == VALID_COOKIE
    assert seen and not seen[0].exists()  # 验证码用完即删


@pytest.mark.parametrize(("password", "code"), [("WRONG", MOCK_CAPTCHA), ("FAKE-PASS", "ZZZZ")])
def test_login_failure_against_mock(
    mock_base: str, tmp_path: Path, password: str, code: str
) -> None:
    with pytest.raises(UpstreamError, match="验证码错误|登录失败"):
        _login(mock_base, tmp_path, password, code)
    assert not list(tmp_path.glob("captcha-*"))


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [({"code": "bad code!"}, "验证码"), ({"password": ""}, "密码")],
)
def test_login_input_validation(
    mock_base: str, tmp_path: Path, kwargs: dict[str, str], match: str
) -> None:
    with pytest.raises(ConfigError, match=match):
        _login(mock_base, tmp_path, **kwargs)


def test_login_rejects_bad_account(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        password_login(
            "https://jw.example.edu.cn/jsxsd/",
            "a b",
            get_password=lambda: "x",
            ask_captcha=lambda p: "A",
            captcha_dir=tmp_path,
        )


def _transport_login(tmp_path: Path, handler: httpx.MockTransport) -> None:
    password_login(
        "https://jw.example.edu.cn/jsxsd/",
        "2099000001",
        get_password=lambda: "FAKE-PASS",
        ask_captcha=lambda p: "ABCD",
        captcha_dir=tmp_path,
        transport=handler,
        min_interval=0,
    )


@pytest.mark.parametrize(
    ("responses", "match"),
    [
        ({"": httpx.Response(500)}, "HTTP 500"),
        ({"": httpx.Response(200, text="<html>CAS</html>")}, "不支持"),
        (
            {
                "": httpx.Response(200, text="LoginToXk"),
                CAPTCHA_PATH: httpx.Response(200, text="x", headers={"content-type": "text/html"}),
            },
            "验证码",
        ),
        (
            {
                "": httpx.Response(200, text="LoginToXk"),
                CAPTCHA_PATH: httpx.Response(
                    200, content=b"i", headers={"content-type": "image/png"}
                ),
                LOGIN_POST: httpx.Response(302, headers={"location": "/jsxsd/xk/LoginToXk"}),
            },
            "重定向回登录页",
        ),
        (
            {
                "": httpx.Response(200, text="LoginToXk"),
                CAPTCHA_PATH: httpx.Response(
                    200, content=b"i" * (256 * 1024 + 1), headers={"content-type": "image/png"}
                ),
            },
            "过大",
        ),
        (
            {
                "": httpx.Response(200, text="LoginToXk"),
                CAPTCHA_PATH: httpx.Response(
                    200, content=b"i", headers={"content-type": "image/png"}
                ),
                LOGIN_POST: httpx.Response(302, headers={"location": "/jsxsd/" + LANDING}),
                LANDING: httpx.Response(200, text="<html>ok, but no cookie</html>"),
            },
            "Cookie",
        ),
        (
            {
                "": httpx.Response(200, text="LoginToXk"),
                CAPTCHA_PATH: httpx.Response(
                    200, content=b"i", headers={"content-type": "image/png"}
                ),
                LOGIN_POST: httpx.Response(200, text="<form action='LoginToXk'>"),
            },
            "登录失败",
        ),
    ],
)
def test_login_upstream_errors(
    tmp_path: Path, responses: dict[str, httpx.Response], match: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        rel = request.url.path.removeprefix("/jsxsd/")
        return responses.get(rel, httpx.Response(404))

    with pytest.raises(UpstreamError, match=match):
        _transport_login(tmp_path, httpx.MockTransport(handler))


# ---- 守卫 ----


def _client() -> GuardedClient:
    return GuardedClient("https://jw.example.edu.cn/jsxsd/", LOGIN_RULES, {}, min_interval=0)


GOOD = {
    "loginMethod": "LoginToXk",
    "userAccount": "2099000001",
    "userPassword": "",
    "RANDOMCODE": "ABCD",
    "encoded": MOCK_ENCODED,
}


@pytest.mark.parametrize(
    "override",
    [
        {"userPassword": "plaintext"},
        {"loginMethod": "logonLdap"},
        {"encoded": "no-separator"},
        {"userAccount": "../x"},
        {"RANDOMCODE": "TOO-LONG-CODE"},
        {"method": "qrCodeCreate"},
    ],
)
def test_login_guard_rejects(override: dict[str, str]) -> None:
    with pytest.raises(GuardViolation):
        _client().post_form(LOGIN_POST, {}, {**GOOD, **override})


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", LOGIN_POST),
        ("GET", "xk/LoginToXk?method=loginByWx"),
        ("POST", "xskb/xskb_list.do"),
        ("GET", "kscj/cjcx_list"),
        ("POST", "Logon.do"),
    ],
)
def test_login_rules_do_not_cover_data_or_other_flows(method: str, path: str) -> None:
    with pytest.raises(GuardViolation):
        if method == "GET":
            _client().get(path)
        else:
            _client().post_form(path, {}, {})


def test_server_does_not_import_login_and_no_password_param() -> None:
    for name in ("server.py", "service.py"):
        tree = ast.parse((SRC / name).read_text("utf-8"))
        imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
        }
        assert not any("login" in m for m in imported), name
    assert "password" not in (SRC / "server.py").read_text("utf-8").lower()


def test_export_cookies_filters_other_hosts() -> None:
    client = GuardedClient("https://jw.example.edu.cn/jsxsd/", LOGIN_RULES, {}, min_interval=0)
    client._client.cookies.set("A", "FAKE-1", domain="jw.example.edu.cn")
    client._client.cookies.set("B", "FAKE-2", domain=".example.edu.cn")
    client._client.cookies.set("C", "FAKE-3", domain="evil.example.com")
    assert client.export_cookies() == {"A": "FAKE-1", "B": "FAKE-2"}


# ---- CLI ----


def test_cli_login_end_to_end(
    mock_base: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    keyring = MemoryKeyring()
    monkeypatch.setenv("CAMPUS_EDU_BASE_URL", mock_base)
    monkeypatch.setenv("CAMPUS_EDU_MIN_INTERVAL", "0")
    monkeypatch.setattr(cli, "SessionStore", lambda: SessionStore(keyring, tmp_path / "s"))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "FAKE-PASS")
    monkeypatch.setattr("builtins.input", lambda prompt="": MOCK_CAPTCHA)
    from campus_edu_mcp import login as login_mod

    real = login_mod.password_login
    assert cli.run(["login", "--username", "2099000001"]) == 2  # CLI 拒绝 http
    monkeypatch.setattr(login_mod, "password_login", functools.partial(real, allow_http=True))
    assert cli.run(["login", "--username", "2099000001"]) == 0
    out = capsys.readouterr()
    printed = out.out + out.err
    assert "FAKE-PASS" not in printed and VALID_COOKIE not in printed
    assert MOCK_ENCODED not in printed and "RkFLRS1QQVNT" not in printed
    stored = SessionStore(keyring, tmp_path / "s").load("127.0.0.1")
    assert stored and stored["JSESSIONID"] == VALID_COOKIE


def test_cli_login_refuses_without_keyring_or_wrong_vendor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAMPUS_EDU_BASE_URL", "https://jw.example.edu.cn/jsxsd/")
    monkeypatch.setattr(cli, "SessionStore", lambda: SessionStore(None, tmp_path))
    assert cli.run(["login", "--username", "2099000001"]) == 2
    monkeypatch.setenv("CAMPUS_EDU_VENDOR", "zfsoft_v9")
    assert cli.run(["login", "--username", "2099000001"]) == 2


def test_login_requires_https(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="https"):
        password_login(
            "http://jw.example.edu.cn/jsxsd/",
            "2099000001",
            get_password=lambda: "x",
            ask_captcha=lambda p: "A",
            captcha_dir=tmp_path,
        )


def test_login_cleans_captcha_when_prompt_fails(mock_base: str, tmp_path: Path) -> None:
    def ask(path: Path) -> str:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        password_login(
            mock_base,
            "2099000001",
            get_password=lambda: "FAKE-PASS",
            ask_captcha=ask,
            captcha_dir=tmp_path,
            min_interval=0,
            allow_http=True,
        )
    assert not list(tmp_path.glob("captcha-*"))


def test_error_message_is_scrubbed(tmp_path: Path) -> None:
    page = '<font color="red">账号 2099000001 编码 MjA5OTAwMDAwMQ==%%%RkFLRS1QQVNT 无效</font>'

    def handler(request: httpx.Request) -> httpx.Response:
        rel = request.url.path.removeprefix("/jsxsd/")
        if rel == "":
            return httpx.Response(200, text="LoginToXk")
        if rel == CAPTCHA_PATH:
            return httpx.Response(200, content=b"i", headers={"content-type": "image/png"})
        return httpx.Response(200, text=page)

    with pytest.raises(UpstreamError) as info:
        _transport_login(tmp_path, httpx.MockTransport(handler))
    assert "2099000001" not in str(info.value) and "%%%" not in str(info.value)

"""0.5.0：学校登记表过期状态、实验性 Streamable HTTP（仅本机 + Bearer）。"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from campus_edu_mcp.cli import run
from campus_edu_mcp.doctor import run_checks
from campus_edu_mcp.errors import ConfigError
from campus_edu_mcp.http_transport import TOKEN_ENV, BearerAuth, build_app, load_token
from campus_edu_mcp.registry import find_school, list_schools, parse_school, schools_dir
from campus_edu_mcp.storage import SessionStore
from mock_server.server import QZ_BASE, VALID_COOKIE, serve

from .conftest import MemoryKeyring

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "FAKE-TOKEN-" + "x" * 32


# ---- 登记表 ----


def test_repo_schools_are_fictional_and_valid() -> None:
    entries = list_schools(ROOT / "schools")
    assert entries
    for filename, school, error in entries:
        assert school is not None, (filename, error)
        assert httpx.URL(school.base_url).host.endswith("example.edu.cn"), filename
        assert school.vendor in {"qiangzhi", "zfsoft_v9"}


def test_parse_school_and_status() -> None:
    school = parse_school(
        "# c\nschool_id: demo # 注释\nvendor: qiangzhi\nbase_url: 'https://jw.example.edu.cn/jsxsd/'\n"
        "notes: |\n  key: ignored\nlast_verified: 2026-01-01\n"
    )
    assert school.base_url == "https://jw.example.edu.cn/jsxsd/"
    assert school.status(dt.date(2026, 3, 1)) == "verified"
    assert school.status(dt.date(2026, 10, 16)) == "stale"
    assert parse_school("school_id: a\nvendor: b\nbase_url: c\n").status() == "pending"
    with pytest.raises(ValueError, match="base_url"):
        parse_school("school_id: a\nvendor: b\n")


def test_list_schools_tolerates_bad_files(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("school_id: a\nvendor: qiangzhi\nbase_url: x\n", "utf-8")
    (tmp_path / "b.yaml").write_text("nothing", "utf-8")
    (tmp_path / "c.yaml").write_bytes(b"\xff\xfe\x00")
    entries = list_schools(tmp_path)
    assert [e[0] for e in entries] == ["a.yaml", "b.yaml", "c.yaml"]
    assert entries[0][1] is not None and entries[1][1] is None and entries[2][1] is None
    assert find_school("a", tmp_path) is not None and find_school("zz", tmp_path) is None
    assert list_schools(tmp_path / "missing") == []


def test_schools_dir_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUS_EDU_SCHOOLS_DIR", str(tmp_path))
    assert schools_dir() == tmp_path


def test_cli_schools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.yaml").write_text(
        "school_id: a\nvendor: qiangzhi\nbase_url: x\nlast_verified: 2000-01-01\n", "utf-8"
    )
    (tmp_path / "b.yaml").write_text("bad", "utf-8")
    assert run(["schools", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "a\tqiangzhi\tstale\t2000-01-01" in out and "[无效] b.yaml" in out
    assert run(["schools", "--dir", str(tmp_path / "none")]) == 1


def test_doctor_reports_school(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "s.yaml").write_text(
        "school_id: demo\nvendor: qiangzhi\nbase_url: x\nlast_verified: 2000-01-01\n", "utf-8"
    )
    monkeypatch.setenv("CAMPUS_EDU_SCHOOLS_DIR", str(tmp_path))
    monkeypatch.setenv("CAMPUS_EDU_BASE_URL", "https://jw.example.edu.cn/jsxsd/")
    monkeypatch.setenv("CAMPUS_EDU_SCHOOL", "demo")
    store = lambda: SessionStore(MemoryKeyring(), tmp_path)  # noqa: E731
    school = next(c for c in run_checks(store_factory=store) if c.name == "school")
    assert school.level == "warn" and "stale" in school.detail
    monkeypatch.setenv("CAMPUS_EDU_SCHOOL", "missing")
    school = next(c for c in run_checks(store_factory=store) if c.name == "school")
    assert "没有" in school.detail
    (tmp_path / "s.yaml").write_text(
        f"school_id: demo\nvendor: qiangzhi\nbase_url: x\nlast_verified: {dt.date.today()}\n",
        "utf-8",
    )
    monkeypatch.setenv("CAMPUS_EDU_SCHOOL", "demo")
    school = next(c for c in run_checks(store_factory=store) if c.name == "school")
    assert school.level == "ok"


# ---- HTTP 传输 ----


def test_load_token(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError):
        load_token()
    monkeypatch.setenv(TOKEN_ENV, "short")
    with pytest.raises(ConfigError):
        load_token()
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    assert load_token() == TOKEN


def test_cli_http_requires_token() -> None:
    assert run(["serve", "--transport", "http", "--port", "18999"]) == 2


async def _asgi(app: Any, headers: dict[str, str], port: int = 8848) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url=f"http://127.0.0.1:{port}"
    ) as client:
        return await client.post(
            "/mcp",
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
                **headers,
            },
            content=b"{}",
        )


def test_bearer_auth_rejects() -> None:
    calls: list[str] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        calls.append(scope["type"])

    app = BearerAuth(inner, TOKEN)
    for headers in ({}, {"authorization": "Bearer wrong"}, {"authorization": TOKEN}):
        assert asyncio.run(_asgi(app, headers)).status_code == 401
    assert calls == []

    async def lifespan() -> None:
        await app({"type": "lifespan"}, None, None)  # type: ignore[arg-type]

    asyncio.run(lifespan())
    assert calls == ["lifespan"]


def test_build_app_host_and_origin_checks() -> None:
    app = build_app(8848, TOKEN)
    assert isinstance(app, BearerAuth)
    inner: Any = app.app

    async def scenario() -> list[int]:
        async with inner.router.lifespan_context(inner):
            auth = {"authorization": f"Bearer {TOKEN}"}
            return [
                (await _asgi(app, {**auth, "host": "evil.example.com"})).status_code,
                (await _asgi(app, {**auth, "origin": "http://evil.example.com"})).status_code,
                (await _asgi(app, {"host": "127.0.0.1:8848"})).status_code,
            ]

    bad_host, bad_origin, no_auth = asyncio.run(scenario())
    assert bad_host in {400, 403, 421} and bad_origin in {400, 403}
    assert no_auth == 401


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def mock_school() -> Iterator[str]:
    httpd, _ = serve(0, vendor="qiangzhi")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


async def _http_session(url: str, token: str) -> dict[str, str]:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    out: dict[str, str] = {}
    client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30)
    async with (
        client,
        streamable_http_client(url, http_client=client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        out["tools"] = ",".join(sorted(t.name for t in tools.tools))
        result = await session.call_tool("get_terms", {})
        out["terms"] = "".join(getattr(c, "text", "") for c in result.content)
    return out


def test_http_end_to_end(mock_school: str, tmp_path: Path) -> None:
    port = _free_port()
    cookie = tmp_path / "cookie.txt"
    cookie.write_text(f"JSESSIONID={VALID_COOKIE}", "utf-8")
    env = {k: v for k, v in os.environ.items() if isinstance(v, str)}
    env.update(
        {
            "CAMPUS_EDU_BASE_URL": mock_school + QZ_BASE,
            "CAMPUS_EDU_COOKIE_FILE": str(cookie),
            "CAMPUS_EDU_DATA_DIR": str(tmp_path / "data"),
            "CAMPUS_EDU_MIN_INTERVAL": "0",
            "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
            TOKEN_ENV: TOKEN,
        }
    )
    err = (tmp_path / "err.txt").open("w")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "campus_edu_mcp",
            "serve",
            "--transport",
            "http",
            "--port",
            str(port),
        ],
        env=env,
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=err,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.2)
        url = f"http://127.0.0.1:{port}/mcp"
        assert httpx.post(url, content=b"{}").status_code == 401
        out = asyncio.run(_http_session(url, TOKEN))
        assert "get_terms" in out["tools"]
        assert len(json.loads(out["terms"])["terms"]) == 2
        assert VALID_COOKIE not in json.dumps(out) and TOKEN not in json.dumps(out)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        err.close()
    assert TOKEN not in (tmp_path / "err.txt").read_text("utf-8", errors="replace")

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from campus_edu_mcp.errors import ConfigError, StorageError
from campus_edu_mcp.storage import Config, SessionStore, data_dir, load_config, save_config

from .conftest import BASE_URL, MemoryKeyring


def test_session_roundtrip_is_encrypted(tmp_path: Path) -> None:
    store = SessionStore(MemoryKeyring(), tmp_path)
    assert store.persistent
    path = store.save({"JSESSIONID": "FAKE-SECRET-VALUE"})
    raw = path.read_bytes()
    assert b"FAKE-SECRET-VALUE" not in raw
    if sys.platform != "win32":
        assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert store.load() == {"JSESSIONID": "FAKE-SECRET-VALUE"}
    assert store.clear() is True
    assert store.load() is None
    assert store.clear() is False


def test_no_keyring_never_writes_disk(tmp_path: Path) -> None:
    store = SessionStore(None, tmp_path)
    assert not store.persistent
    with pytest.raises(StorageError, match="CAMPUS_EDU_COOKIE_FILE"):
        store.save({"JSESSIONID": "FAKE"})
    assert list(tmp_path.iterdir()) == []
    assert store.load() is None


def test_wrong_key_is_ignored(tmp_path: Path) -> None:
    kr = MemoryKeyring()
    SessionStore(kr, tmp_path).save({"a": "FAKE"})
    kr.store.clear()
    assert SessionStore(MemoryKeyring(), tmp_path).load() is None


def test_keyring_errors_are_wrapped(tmp_path: Path) -> None:
    class Broken(MemoryKeyring):
        def get_password(self, service: str, username: str) -> str | None:
            raise RuntimeError("locked")

    with pytest.raises(StorageError):
        SessionStore(Broken(), tmp_path).save({"a": "FAKE"})


def test_config_roundtrip_and_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError):
        load_config()
    save_config(Config(base_url=BASE_URL, min_interval=3))
    cfg = load_config()
    assert cfg.base_url == BASE_URL and cfg.min_interval == 3.0 and cfg.vendor == "qiangzhi"
    monkeypatch.setenv("CAMPUS_EDU_BASE_URL", "https://other.example.edu.cn/jwglxt/")
    monkeypatch.setenv("CAMPUS_EDU_MIN_INTERVAL", "-1")
    cfg = load_config()
    assert cfg.base_url.startswith("https://other") and cfg.min_interval == 0
    monkeypatch.setenv("CAMPUS_EDU_MIN_INTERVAL", "abc")
    with pytest.raises(ConfigError):
        load_config()


def test_corrupt_config() -> None:
    d = data_dir()
    d.mkdir(parents=True)
    (d / "config.json").write_text("{oops", "utf-8")
    with pytest.raises(ConfigError):
        load_config()


def test_data_dir_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAMPUS_EDU_DATA_DIR")
    assert data_dir().name == "campus-edu-mcp"


def test_keyring_backend_allowlist() -> None:
    from keyring.backends import fail

    from campus_edu_mcp.storage import is_secure_backend

    class FakeWin:
        pass

    FakeWin.__module__ = "keyring.backends.Windows"

    class Plain:
        pass

    Plain.__module__ = "keyrings.alt.file"

    class ChainerBackend:
        def __init__(self, backends: list[object]) -> None:
            self.backends = backends

    assert is_secure_backend(FakeWin())
    assert not is_secure_backend(Plain())
    assert not is_secure_backend(fail.Keyring())  # type: ignore[no-untyped-call]
    assert is_secure_backend(ChainerBackend([FakeWin()]))
    assert not is_secure_backend(ChainerBackend([FakeWin(), Plain()]))
    assert not is_secure_backend(ChainerBackend([]))


def test_session_host_binding(tmp_path: Path) -> None:
    store = SessionStore(MemoryKeyring(), tmp_path)
    store.save({"JSESSIONID": "FAKE-SECRET-VALUE"}, host="jw.example.edu.cn")
    assert store.load(host="jw.example.edu.cn") == {"JSESSIONID": "FAKE-SECRET-VALUE"}
    assert store.load(host="other.example.edu.cn") is None
    # 不传 host 时仍可读（兼容）
    assert store.load() == {"JSESSIONID": "FAKE-SECRET-VALUE"}


def test_session_legacy_format_still_loads(tmp_path: Path) -> None:
    from cryptography.fernet import Fernet

    from campus_edu_mcp.storage import KEY_NAME, SERVICE

    kr = MemoryKeyring()
    key = Fernet.generate_key().decode("ascii")
    kr.set_password(SERVICE, KEY_NAME, key)
    store = SessionStore(kr, tmp_path)
    token = Fernet(key.encode()).encrypt(b'{"JSESSIONID": "FAKE-LEGACY"}')
    store.path.write_bytes(token)
    assert store.load(host="jw.example.edu.cn") == {"JSESSIONID": "FAKE-LEGACY"}


def test_data_dir_ignores_empty_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CAMPUS_EDU_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", "")
    monkeypatch.setenv("APPDATA", "")
    d = data_dir()
    assert d.name == "campus-edu-mcp"
    # 不得落到相对当前目录
    assert d.is_absolute()


def test_data_dir_windows_and_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAMPUS_EDU_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(Path("/tmp/win-appdata")))
    assert data_dir() == Path("/tmp/win-appdata") / "campus-edu-mcp"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert "Application Support" in str(data_dir())

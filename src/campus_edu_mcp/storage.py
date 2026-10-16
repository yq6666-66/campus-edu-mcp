"""本地存储：配置（明文，无敏感信息）与会话（Fernet 加密，密钥放系统 keyring）。

keyring 不可用时**不落盘**：会话只能通过环境变量 CAMPUS_EDU_COOKIE_FILE
在每次启动时读取（由 MCP 客户端配置传入，不经过模型）。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken

from .errors import ConfigError, StorageError

logger = logging.getLogger(__name__)

SERVICE = "campus-edu-mcp"
KEY_NAME = "session-key"


def data_dir() -> Path:
    override = os.environ.get("CAMPUS_EDU_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        # 空字符串也要回退，避免写到进程当前目录
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        base = Path(appdata)
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        base = Path(xdg)
    return base / SERVICE


@dataclass(frozen=True)
class Config:
    base_url: str
    vendor: str = "qiangzhi"
    school_id: str | None = None
    min_interval: float = 2.0
    exams_path: str | None = None


def load_config() -> Config:
    """环境变量优先，其次 data_dir/config.json。"""
    path = data_dir() / "config.json"
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text("utf-8"))
        except ValueError as exc:
            raise ConfigError(f"配置文件损坏：{path}") from exc
    base_url = os.environ.get("CAMPUS_EDU_BASE_URL") or raw.get("base_url")
    if not base_url:
        raise ConfigError("未配置教务地址，请先运行 campus-edu-mcp configure --base-url <地址>")
    interval = os.environ.get("CAMPUS_EDU_MIN_INTERVAL") or raw.get("min_interval", 2.0)
    try:
        min_interval = max(float(interval), 0.0)
    except (TypeError, ValueError) as exc:
        raise ConfigError("min_interval 必须是数字") from exc
    vendor = os.environ.get("CAMPUS_EDU_VENDOR") or raw.get("vendor", "qiangzhi")
    return Config(
        base_url=str(base_url),
        vendor=str(vendor),
        school_id=(os.environ.get("CAMPUS_EDU_SCHOOL") or raw.get("school_id")),
        min_interval=min_interval,
        exams_path=raw.get("exams_path"),
    )


def save_config(config: Config) -> Path:
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.json"
    path.write_text(
        json.dumps(
            {
                "base_url": config.base_url,
                "vendor": config.vendor,
                "school_id": config.school_id,
                "min_interval": config.min_interval,
                "exams_path": config.exams_path,
            },
            ensure_ascii=False,
            indent=2,
        ),
        "utf-8",
    )
    return path


class KeyBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


#: 只信任操作系统级的加密凭据存储（白名单，而不是黑名单）
SECURE_BACKEND_MODULES = (
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.libsecret",
    "keyring.backends.kwallet",
)


def is_secure_backend(backend: object) -> bool:
    children = getattr(backend, "backends", None)
    if type(backend).__name__ == "ChainerBackend" and children is not None:
        return bool(children) and all(is_secure_backend(b) for b in children)
    module = type(backend).__module__
    return any(module == m or module.startswith(m + ".") for m in SECURE_BACKEND_MODULES)


def _default_backend() -> KeyBackend | None:
    try:
        import keyring
        from keyring.backends import fail
    except Exception:  # pragma: no cover - keyring 是必选依赖
        return None
    backend = keyring.get_keyring()
    if isinstance(backend, fail.Keyring) or not is_secure_backend(backend):
        return None
    return keyring


class SessionStore:
    """加密会话存储。``backend`` 可注入以便测试。"""

    def __init__(
        self, backend: KeyBackend | None | str = "auto", directory: Path | None = None
    ) -> None:
        self.backend: KeyBackend | None = (
            _default_backend() if isinstance(backend, str) else backend
        )
        self.directory = directory or data_dir()
        self.path = self.directory / "session.enc"

    @property
    def persistent(self) -> bool:
        return self.backend is not None

    def _fernet(self, create: bool) -> Fernet:
        if self.backend is None:
            raise StorageError(
                "系统 keyring 不可用，为安全起见不把会话写入磁盘。"
                "请改用环境变量 CAMPUS_EDU_COOKIE_FILE 指向 Cookie 文件。"
            )
        try:
            key = self.backend.get_password(SERVICE, KEY_NAME)
            if key is None and create:
                key = Fernet.generate_key().decode("ascii")
                self.backend.set_password(SERVICE, KEY_NAME, key)
        except Exception as exc:
            raise StorageError("访问系统 keyring 失败") from exc
        if key is None:
            raise StorageError("找不到会话密钥")
        return Fernet(key.encode("ascii"))

    def save(self, cookies: dict[str, str], host: str | None = None) -> Path:
        payload = {"v": 1, "host": host, "cookies": cookies}
        token = self._fernet(create=True).encrypt(json.dumps(payload).encode("utf-8"))
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(token)
        os.replace(tmp, self.path)
        if sys.platform != "win32":
            os.chmod(self.path, 0o600)
        return self.path

    def load(self, host: str | None = None) -> dict[str, str] | None:
        if not self.path.exists() or self.backend is None:
            return None
        try:
            data = self._fernet(create=False).decrypt(self.path.read_bytes())
        except (InvalidToken, StorageError):
            logger.warning("会话文件无法解密，已忽略")
            return None
        loaded = json.loads(data)
        if isinstance(loaded, dict) and isinstance(loaded.get("cookies"), dict):
            stored_host = loaded.get("host")
            if host and stored_host and str(stored_host).lower() != host.lower():
                logger.warning("会话绑定域名与当前配置不符，已忽略")
                return None
            cookies = loaded["cookies"]
            return {str(k): str(v) for k, v in cookies.items()}
        # 兼容旧格式：整份 JSON 即 cookie 字典
        return {str(k): str(v) for k, v in loaded.items()}

    def clear(self) -> bool:
        removed = False
        if self.path.exists():
            self.path.unlink()
            removed = True
        if self.backend is not None:
            with contextlib.suppress(Exception):  # 密钥不存在时忽略
                self.backend.delete_password(SERVICE, KEY_NAME)
        return removed

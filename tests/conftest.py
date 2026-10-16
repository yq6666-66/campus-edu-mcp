from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "zfsoft_v9"
BASE_URL = "https://jw.example.edu.cn/jwglxt/"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text("utf-8")


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    for var in (
        "CAMPUS_EDU_BASE_URL",
        "CAMPUS_EDU_COOKIE",
        "CAMPUS_EDU_COOKIE_FILE",
        "CAMPUS_EDU_MIN_INTERVAL",
        "CAMPUS_EDU_ALLOW_UNVERIFIED",
        "CAMPUS_EDU_VENDOR",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CAMPUS_EDU_DATA_DIR", str(tmp_path / "data"))
    yield


class MemoryKeyring:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.store.pop((service, username), None)

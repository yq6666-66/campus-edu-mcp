from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


check_adapters = load("check_adapters")
check_fixtures = load("check_fixtures")


def test_real_adapters_pass() -> None:
    assert check_adapters.main() == 0


BAD_SNIPPETS = [
    "import requests",
    "import urllib.request",
    "from http import client\nimport http.client",
    "import httpx as h\nh.Client()",
    "from httpx import Client as C",
    "import httpx\nhttpx.post('x')",
    "import socket",
    "def f(c):\n    return c._client.send(None)",
    "x = getattr(object, 'a')",
    "eval('1')",
    "import importlib",
    "from campus_edu_mcp.guard import GuardTransport",
]


def test_bad_snippets_detected() -> None:
    for snippet in BAD_SNIPPETS:
        assert check_adapters.check_source(snippet), snippet


def test_allowed_snippet() -> None:
    ok = (
        "import httpx\nfrom ..guard import GuardedClient, Rule\n"
        "def f(r: httpx.Response) -> None: ..."
    )
    assert check_adapters.check_source(ok) == []


def test_fixture_checker_flags_real_looking_data() -> None:
    assert check_fixtures.main() == 0
    assert check_fixtures.check_text('{"xh": "2021123456"}', "t")
    assert check_fixtures.check_text('{"xm": "李雷"}', "t")
    assert check_fixtures.check_text("身份证 11010119900307123X", "t")
    assert check_fixtures.check_text("JSESSIONID=ABCDEF1234567890", "t")
    assert check_fixtures.check_text('{"xh": "2099000001", "xm": "测试学生"}', "t") == []

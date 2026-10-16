from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_example-qiangzhi_school_yaml() -> None:
    text = (ROOT / "schools" / "example-qiangzhi.yaml").read_text("utf-8")
    assert "vendor: qiangzhi" in text
    assert "jw.example.edu.cn/jsxsd/" in text
    assert "last_verified: 2026-10-16" in text

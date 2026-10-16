from __future__ import annotations

from pathlib import Path

from tests._private_words import banned_words

ROOT = Path(__file__).resolve().parent.parent


def test_example_qiangzhi_school_yaml() -> None:
    text = (ROOT / "schools" / "example-qiangzhi.yaml").read_text("utf-8")
    assert "vendor: qiangzhi" in text
    assert "jw.example.edu.cn/jsxsd/" in text
    assert "last_verified: 2026-10-16" in text


def test_example_supwisdom_school_yaml() -> None:
    text = (ROOT / "schools" / "example-supwisdom-eams5.yaml").read_text("utf-8")
    assert "vendor: supwisdom_eams5" in text
    assert "jw.example.edu.cn/student/" in text
    lowered = text.lower()
    for word in banned_words():
        assert word not in lowered, word

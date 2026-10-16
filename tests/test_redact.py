from __future__ import annotations

import logging

import pytest

from campus_edu_mcp.redact import MASK, RedactingFilter, install_logging, redact, redact_url


@pytest.mark.parametrize(
    ("url", "absent"),
    [
        ("https://jw.example.edu.cn/jwglxt/x.html?xh=2099000001&gnmkdm=N1", "2099000001"),
        ("https://jw.example.edu.cn/jwglxt/x.html?su=2099000001", "2099000001"),
        ("https://user:FAKEPW@jw.example.edu.cn/a", "FAKEPW"),
        ("https://jw.example.edu.cn/a;jsessionid=FAKESID123?x=1", "FAKESID123"),
        ("https://jw.example.edu.cn/a?token=FAKETOKEN&q=12345678901", "FAKETOKEN"),
        ("https://jw.example.edu.cn/a?q=12345678901", "12345678901"),
    ],
)
def test_redact_url(url: str, absent: str) -> None:
    out = redact_url(url)
    assert absent not in out
    assert out.startswith("https://jw.example.edu.cn/")


def test_redact_url_keeps_safe_params() -> None:
    assert "gnmkdm=N305005" in redact_url("https://h/x?gnmkdm=N305005&xh=1")


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("Cookie: JSESSIONID=FAKEABC; route=FAKEROUTE", "FAKEABC"),
        ("set-cookie: JSESSIONID=FAKEABC", "FAKEABC"),
        ("JSESSIONID=FAKEABC route=FAKER", "FAKEABC"),
        ('{"xh": "2099000001", "xm": "测试学生"}', "测试学生"),
        ("password: 'FAKE PW'", "FAKE PW"),
        ("visit https://h/x?xh=FAKEXH now", "FAKEXH"),
        ("学号 2099000001 的成绩", "2099000001"),
    ],
)
def test_redact_text(text: str, secret: str) -> None:
    out = redact(text)
    assert secret not in out
    assert MASK in out


def test_redact_keeps_normal_text() -> None:
    assert redact("课表 共 6 门，第 1-16 周") == "课表 共 6 门，第 1-16 周"


def test_redacting_filter_and_logging(caplog: pytest.LogCaptureFixture) -> None:
    record = logging.LogRecord(
        "campus_edu_mcp", logging.INFO, "f", 1, "cookie=%s", ("FAKE123",), None
    )
    assert RedactingFilter().filter(record)
    assert "FAKE123" not in record.getMessage()
    install_logging(verbose=True)
    logger = logging.getLogger("campus_edu_mcp")
    assert logger.level == logging.DEBUG
    assert any(isinstance(f, RedactingFilter) for h in logger.handlers for f in h.filters)
    install_logging(verbose=False)
    assert logger.level == logging.WARNING


def test_install_logging_filters_httpx(capsys: pytest.CaptureFixture[str]) -> None:
    import logging

    from campus_edu_mcp.redact import install_logging

    install_logging(verbose=True)
    logging.getLogger("httpx").warning("Cookie: JSESSIONID=ABCDEF1234567890")
    err = capsys.readouterr().err
    assert "ABCDEF1234567890" not in err

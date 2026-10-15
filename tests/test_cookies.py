from __future__ import annotations

import pytest

from campus_edu_mcp.cookies import parse_cookie_text
from campus_edu_mcp.errors import ConfigError


def test_parse_header_format() -> None:
    text = "Cookie: token=FAKE_TOKEN; session=FAKE_SESSION"
    assert parse_cookie_text(text) == {"token": "FAKE_TOKEN", "session": "FAKE_SESSION"}


def test_parse_netscape_format() -> None:
    text = "example.com\tTRUE\t/\tFALSE\t0\ttoken\tFAKE_TOKEN"
    assert parse_cookie_text(text) == {"token": "FAKE_TOKEN"}


def test_parse_json_array_format() -> None:
    text = '[{"domain": "example.com", "name": "token", "value": "FAKE_TOKEN"}]'
    assert parse_cookie_text(text) == {"token": "FAKE_TOKEN"}


def test_parse_json_cookies_object() -> None:
    text = '{"cookies": [{"domain": "example.com", "name": "token", "value": "FAKE_TOKEN"}]}'
    assert parse_cookie_text(text) == {"token": "FAKE_TOKEN"}


def test_parse_json_dict_form() -> None:
    text = '{"token": "FAKE_TOKEN", "session": "FAKE_SESSION"}'
    assert parse_cookie_text(text) == {"token": "FAKE_TOKEN", "session": "FAKE_SESSION"}


def test_host_filtering_with_leading_dot() -> None:
    text = "\n".join(
        [
            ".example.edu.cn\tTRUE\t/\tFALSE\t0\twith_dot\tFAKE_DOT",
            "example.edu.cn\tTRUE\t/\tFALSE\t0\texact\tFAKE_EXACT",
            "other.com\tTRUE\t/\tFALSE\t0\tother\tFAKE_OTHER",
        ]
    )
    assert parse_cookie_text(text, host="sub.example.edu.cn") == {
        "with_dot": "FAKE_DOT",
        "exact": "FAKE_EXACT",
    }
    assert parse_cookie_text(text, host="example.edu.cn") == {
        "with_dot": "FAKE_DOT",
        "exact": "FAKE_EXACT",
    }


def test_httponly_prefix_line() -> None:
    text = "#HttpOnly_.example.edu.cn\tTRUE\t/\tFALSE\t0\ttoken\tFAKE_TOKEN"
    assert parse_cookie_text(text) == {"token": "FAKE_TOKEN"}


def test_empty_file_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        parse_cookie_text("")


def test_invalid_json_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        parse_cookie_text("[invalid json")


def test_invalid_cookie_names_are_filtered() -> None:
    text = "valid=FAKE_VALUE; bad name=FAKE_BAD"
    assert parse_cookie_text(text) == {"valid": "FAKE_VALUE"}


def test_utf8_bom_header() -> None:
    text = "\ufeffvalid=FAKE_VALUE; session=FAKE_SESSION"
    assert parse_cookie_text(text) == {"valid": "FAKE_VALUE", "session": "FAKE_SESSION"}

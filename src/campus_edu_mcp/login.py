"""实验性：强智 jsxsd 账号密码登录（仅 CLI，**未经 live 实测**）。

安全边界：

* 密码只通过 ``getpass`` 在终端读取，不接受命令行参数、环境变量或 MCP 调用；
  只存在于本函数的局部变量中，不写盘、不写日志。
* 登录使用独立的 :data:`LOGIN_RULES` 白名单，与数据查询白名单分开；
  MCP 服务进程不导入本模块。
* 验证码图片写入本地数据目录（权限 0600），由用户肉眼识别后手动输入，用完即删。
* 登录成功后得到的 Cookie 直接交给 :class:`SessionStore` 加密保存，不打印。

编码方式依据公开登录页脚本：``encoded = base64(账号) + "%%%" + base64(密码)``，
``userPassword`` 字段提交前被清空。不同学校可能使用另一种 scode/sxh 混淆，本实现不支持。
"""

from __future__ import annotations

import base64
import contextlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from .errors import ConfigError, SessionExpired, UpstreamError
from .guard import GuardedClient, Rule
from .htmlutil import looks_like_login

LOGIN_PAGE = ""
CAPTCHA_PATH = "verifycode.servlet"
LOGIN_POST = "xk/LoginToXk"
LANDING = "framework/xsMain.jsp"

_ACCOUNT = r"[A-Za-z0-9_]{1,32}"

LOGIN_RULES: tuple[Rule, ...] = (
    Rule("GET", LOGIN_PAGE, description="登录页（取初始 Cookie）"),
    Rule("GET", CAPTCHA_PATH, description="验证码图片"),
    Rule(
        "POST",
        LOGIN_POST,
        fixed={"loginMethod": frozenset({"LoginToXk"}), "userPassword": frozenset({""})},
        free={
            "userAccount": _ACCOUNT,
            "RANDOMCODE": r"[A-Za-z0-9]{0,8}",
            "encoded": r"[A-Za-z0-9+/=]{1,200}%%%[A-Za-z0-9+/=]{1,200}",
        },
        description="账号密码登录（仅 CLI）",
    ),
    Rule("GET", LANDING, description="登录成功后的主页（只用于确认）"),
)
# 登录 POST 之后被重定向回这些位置，视为失败
LOGIN_FAIL_MARKERS = ("LoginToXk", "Logon.do", "/login")


@dataclass(frozen=True)
class LoginResult:
    cookies: dict[str, str]


def encode_credentials(account: str, password: str) -> str:
    """与登录页 ``encodeInp`` 一致：逐字符 charCode 的标准 Base64。只接受 ASCII。"""
    if not account.isascii() or not password.isascii():
        raise ConfigError("账号或密码含非 ASCII 字符，实验性登录暂不支持")
    a = base64.b64encode(account.encode("ascii")).decode()
    p = base64.b64encode(password.encode("ascii")).decode()
    return f"{a}%%%{p}"


def _error_message(html_text: str) -> str:
    for pattern in (
        r'<font[^>]*color=["\']?red["\']?[^>]*>\s*([^<]{1,60})<',
        r'id=["\']showMsg["\'][^>]*>\s*([^<]{1,60})<',
    ):
        m = re.search(pattern, html_text, re.I)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return "登录失败（账号、密码或验证码错误，或学校使用了不支持的登录方式）"


def password_login(
    base_url: str,
    account: str,
    *,
    get_password: Callable[[], str],
    ask_captcha: Callable[[Path], str],
    captcha_dir: Path,
    transport: httpx.BaseTransport | None = None,
    min_interval: float = 2.0,
) -> LoginResult:
    if not re.fullmatch(_ACCOUNT, account):
        raise ConfigError("账号格式不支持（仅字母、数字、下划线，1-32 位）")
    client = GuardedClient(
        base_url,
        LOGIN_RULES,
        {},
        transport=transport,
        min_interval=min_interval,
        login_markers=LOGIN_FAIL_MARKERS,
    )
    captcha_file = captcha_dir / "captcha.img"
    try:
        page = client.get(LOGIN_PAGE)
        if page.status_code != 200:
            raise UpstreamError(f"登录页返回 HTTP {page.status_code}")
        if "LoginToXk" not in page.text:
            raise UpstreamError("登录页不是预期的 jsxsd 账号密码表单，实验性登录不支持该学校")
        image = client.get(CAPTCHA_PATH)
        if image.status_code != 200 or not image.headers.get("content-type", "").startswith(
            "image/"
        ):
            raise UpstreamError("获取验证码失败")
        captcha_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(captcha_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(image.content)
        code = ask_captcha(captcha_file).strip()
        if not re.fullmatch(r"[A-Za-z0-9]{1,8}", code):
            raise ConfigError("验证码格式不正确")
        password = get_password()
        if not password:
            raise ConfigError("密码不能为空")
        encoded = encode_credentials(account, password)
        del password
        try:
            response = client.post_form(
                LOGIN_POST,
                {},
                {
                    "loginMethod": "LoginToXk",
                    "userAccount": account,
                    "userPassword": "",
                    "RANDOMCODE": code,
                    "encoded": encoded,
                },
            )
        except SessionExpired as exc:
            raise UpstreamError("登录失败：被重定向回登录页") from exc
        del encoded
        if response.status_code != 200 or looks_like_login(response.text):
            raise UpstreamError(_error_message(response.text))
        if "xsMain" not in str(response.url) and "LoginToXk" in response.text:
            raise UpstreamError(_error_message(response.text))
        cookies = client.export_cookies()
        if not cookies:
            raise UpstreamError("登录后没有拿到会话 Cookie")
        return LoginResult(cookies=cookies)
    finally:
        with contextlib.suppress(OSError):
            captcha_file.unlink()
        client.close()

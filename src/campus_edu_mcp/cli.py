"""命令行入口。Cookie 只能通过这里（文件或环境变量）导入，永远不经过 MCP。

退出码：0 成功，1 发现问题，2 用法 / 配置错误，3 网络或认证错误。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx

from . import __version__
from .cookies import parse_cookie_text
from .errors import ConfigError, ProjectError
from .redact import install_logging, redact
from .service import Service
from .storage import Config, SessionStore, load_config, save_config

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="campus-edu-mcp", description="只读高校教务 MCP 服务")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--verbose", action="store_true", help="输出调试日志（已脱敏）")
    p.add_argument("--debug", action="store_true", help="出错时打印堆栈")
    sub = p.add_subparsers(dest="command")
    sv = sub.add_parser("serve", help="启动 MCP 服务（默认 stdio）")
    sv.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="http 为实验性 Streamable HTTP：仅 127.0.0.1，需 CAMPUS_EDU_HTTP_TOKEN",
    )
    sv.add_argument("--port", type=int, default=8848, help="http 传输端口（仅本机）")
    sc = sub.add_parser("schools", help="列出学校登记表及其验证状态")
    sc.add_argument("--dir", type=Path, default=None, help="登记表目录（默认仓库 schools/）")
    dv = sub.add_parser(
        "detect-vendor",
        help="只读探测教务厂商（仅公开 GET，不带 Cookie，不登录）",
    )
    dv.add_argument("--base-url", required=True, help="教务站点根，如 https://jw.example.edu.cn/")
    dv.add_argument("--json", action="store_true", help="输出 JSON")
    dv.add_argument("--min-interval", type=float, default=2.0, help="探针间隔秒数（默认 2）")
    c = sub.add_parser("configure", help="设置教务系统地址")
    c.add_argument("--base-url", required=True, help="如 https://jw.example.edu.cn/jsxsd/")
    c.add_argument(
        "--vendor",
        default="qiangzhi",
        choices=["qiangzhi", "zfsoft_v9", "supwisdom_eams5"],
        help="教务厂商",
    )
    c.add_argument("--school", default=None, help="学校配置 id，如 example-qiangzhi")
    c.add_argument("--min-interval", type=float, default=2.0, help="两次请求的最小间隔秒数")
    i = sub.add_parser("import-session", help="从浏览器导出的 Cookie 文件导入会话")
    src = i.add_mutually_exclusive_group(required=True)
    src.add_argument("--cookie-file", type=Path, help="Cookie 文件（请求头 / cookies.txt / JSON）")
    src.add_argument("--from-env", action="store_true", help="从环境变量 CAMPUS_EDU_COOKIE 读取")
    sub.add_parser("session-status", help="检查会话是否有效")
    sub.add_parser("clear-session", help="删除本地保存的会话与密钥")
    lg = sub.add_parser(
        "login", help="（实验性，未实测）强智账号密码登录；密码只在终端输入，不保存"
    )
    lg.add_argument("--username", required=True, help="学号 / 账号")
    d = sub.add_parser("doctor", help="本地自检（不输出 Cookie）")
    d.add_argument("--online", action="store_true", help="额外发 1 个只读请求检查会话是否有效")
    e = sub.add_parser("export-ics", help="（实验性）把课表导出为 .ics 日历文件")
    e.add_argument("--term-start", required=True, help="第 1 周任意一天，YYYY-MM-DD")
    e.add_argument("--periods", required=True, type=Path, help="作息时间 JSON 文件")
    e.add_argument("--out", required=True, type=Path, help="输出 .ics 路径")
    e.add_argument("--year", type=int, default=None)
    e.add_argument("--term", type=int, default=None)
    return p


def _import_session(args: argparse.Namespace) -> int:
    config = load_config()
    if args.from_env:
        text = os.environ.get("CAMPUS_EDU_COOKIE", "")
        if not text:
            raise ConfigError("环境变量 CAMPUS_EDU_COOKIE 为空")
    else:
        try:
            text = args.cookie_file.read_text("utf-8")
        except OSError as exc:
            raise ConfigError("无法读取 Cookie 文件") from exc
    host = httpx.URL(config.base_url).host
    cookies = parse_cookie_text(text, host)
    store = SessionStore()
    path = store.save(cookies, host=host)
    print(f"已导入 {len(cookies)} 个 Cookie，加密保存到 {path}")
    print("可以删除原始 Cookie 文件了。运行 campus-edu-mcp session-status 检查是否有效。")
    return 0


def _login(args: argparse.Namespace) -> int:
    import getpass

    from .login import password_login
    from .storage import data_dir

    config = load_config()
    if config.vendor != "qiangzhi":
        raise ConfigError("实验性登录只支持强智（qiangzhi）")
    store = SessionStore()
    if not store.persistent:
        raise ConfigError("系统 keyring 不可用，无法安全保存登录结果；请改用 import-session")
    print("实验性功能：尚未在真实学校验证。密码只用于本次登录，不会保存。", file=sys.stderr)

    def ask_captcha(path: Path) -> str:
        print(f"验证码图片已保存到 {path}，请打开查看后输入（用完自动删除）。", file=sys.stderr)
        return input("验证码：")

    result = password_login(
        config.base_url,
        args.username,
        get_password=lambda: getpass.getpass("密码（不回显）："),
        ask_captcha=ask_captcha,
        captcha_dir=data_dir(),
        min_interval=config.min_interval,
    )
    host = httpx.URL(config.base_url).host
    path = store.save(result.cookies, host=host)
    print(f"登录成功，已加密保存 {len(result.cookies)} 个 Cookie 到 {path}")
    return 0


def _export_ics(args: argparse.Namespace) -> int:
    import datetime as dt

    from .ics import build_ics, load_periods
    from .models import Course

    try:
        start = dt.date.fromisoformat(args.term_start)
    except ValueError as exc:
        raise ConfigError("--term-start 格式应为 YYYY-MM-DD") from exc
    periods = load_periods(args.periods)
    result = Service().timetable(args.year, args.term)
    courses = [Course(**c) for c in result["courses"]]
    text, events, skipped = build_ics(courses, start, periods)
    try:
        args.out.write_text(text, "utf-8", newline="")
    except OSError as exc:
        raise ConfigError("无法写入输出文件") from exc
    print(f"已导出 {events} 个日程到 {args.out}（跳过 {skipped} 门无法定位时间的课程）")
    print("提示：实验性功能，请核对作息时间；文件含课表信息，注意分享范围。")
    return 0


def _printable(text: str) -> str:
    """去掉控制字符，避免登记表内容干扰终端。"""
    return "".join(ch for ch in text if ch.isprintable())


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    install_logging(args.verbose)
    command = args.command or "serve"
    try:
        if command == "serve":
            if getattr(args, "transport", "stdio") == "http":
                from .http_transport import check_port, load_token, serve_http

                check_port(args.port)
                load_token()  # 先校验，避免启动后才报错
                print(
                    f"实验性 Streamable HTTP：http://127.0.0.1:{args.port}/mcp（需 Bearer token）",
                    file=sys.stderr,
                )
                serve_http(args.port)
                return 0
            from .server import build_server

            build_server().run("stdio")
            return 0
        if command == "detect-vendor":
            import json as _json

            from .detect_vendor import detect, format_human

            result = detect(args.base_url, min_interval=max(args.min_interval, 0.0))
            print(
                _json.dumps(result.as_dict(), ensure_ascii=False, indent=2)
                if args.json
                else format_human(result)
            )
            return 0
        if command == "schools":
            from .registry import list_schools

            entries = list_schools(args.dir)
            if not entries:
                print("没有找到学校登记表。")
                return 1
            for filename, school, error in entries:
                if school is None:
                    print(f"[无效] {filename}: {error}")
                else:
                    print(
                        "\t".join(
                            _printable(x)
                            for x in (
                                school.school_id,
                                school.vendor,
                                school.status(),
                                school.last_verified or "-",
                            )
                        )
                    )
            return 0
        if command == "configure":
            url = httpx.URL(args.base_url)
            if url.scheme not in {"http", "https"} or not url.host:
                raise ConfigError("base-url 必须是 http(s) 绝对地址")
            if url.username or url.password:
                raise ConfigError("base-url 不能包含用户名或密码")
            # 去掉可能残留的 userinfo，仅保存 scheme/host/port/path
            url = httpx.URL(scheme=url.scheme, host=url.host, port=url.port, path=url.path)
            if url.scheme == "http":
                print("警告：教务地址使用 http，Cookie 会明文传输。", file=sys.stderr)
            path = save_config(
                Config(
                    base_url=str(url),
                    vendor=args.vendor,
                    school_id=args.school,
                    min_interval=args.min_interval,
                )
            )
            print(f"已保存配置到 {path}")
            return 0
        if command == "import-session":
            return _import_session(args)
        if command == "session-status":
            status = Service().session_status()
            print(redact(status.message))
            return 0 if status.valid else 1
        if command == "login":
            return _login(args)
        if command == "doctor":
            from .doctor import render, run_checks

            text, code = render(run_checks(online=args.online))
            print(text)
            return code
        if command == "export-ics":
            return _export_ics(args)
        if command == "clear-session":
            removed = SessionStore().clear()
            print("已删除本地会话。" if removed else "本地没有保存的会话。")
            return 0
    except ProjectError as exc:
        if args.debug:
            logger.exception("命令失败")
        print(f"错误：{redact(str(exc))}", file=sys.stderr)
        return exc.exit_code
    return 2  # pragma: no cover


def main() -> None:  # pragma: no cover
    sys.exit(run())


if __name__ == "__main__":  # pragma: no cover
    main()

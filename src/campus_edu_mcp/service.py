"""工具层业务逻辑（与 MCP 传输解耦，便于测试）。"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .adapters.zfsoft_v9 import ZfsoftV9Adapter
from .cookies import parse_cookie_text
from .errors import ConfigError, ProjectError, SessionExpired, SessionMissing
from .guard import GuardedClient
from .models import PRIVACY_NOTICE, GradeSummary, SessionStatus, Term
from .storage import Config, SessionStore, load_config

ADAPTERS = {"zfsoft_v9": ZfsoftV9Adapter}
REIMPORT_HINT = "请在终端运行 `campus-edu-mcp import-session --cookie-file <文件>` 重新导入。"


def current_term(today: dt.date | None = None) -> Term:
    """按常见校历推断当前学期：8 月至次年 1 月为第一学期，2 至 7 月为第二学期。"""
    today = today or dt.date.today()
    if today.month >= 8:
        return Term(year=today.year, term=1)
    if today.month == 1:
        return Term(year=today.year - 1, term=1)
    return Term(year=today.year - 1, term=2)


def resolve_term(year: int | None, term: int | None, today: dt.date | None = None) -> Term:
    default = current_term(today)
    return Term(
        year=year if year is not None else default.year,
        term=term if term is not None else default.term,
    )


def load_cookies(host: str, store: SessionStore | None = None) -> dict[str, str] | None:
    store = store or SessionStore()
    cookies = store.load()
    if cookies:
        return cookies
    file = os.environ.get("CAMPUS_EDU_COOKIE_FILE")
    if file:
        try:
            text = Path(file).read_text("utf-8")
        except OSError as exc:
            raise ConfigError("无法读取 CAMPUS_EDU_COOKIE_FILE 指向的文件") from exc
        return parse_cookie_text(text, host)
    return None


class Service:
    def __init__(
        self,
        config: Config | None = None,
        cookies_loader: Callable[[str], dict[str, str] | None] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._cookies_loader = cookies_loader or load_cookies
        self._transport = transport

    def _adapter(self) -> tuple[ZfsoftV9Adapter, GuardedClient]:
        config = self._config or load_config()
        adapter_cls = ADAPTERS.get(config.vendor)
        if adapter_cls is None:
            raise ConfigError(f"不支持的厂商 {config.vendor}")
        host = httpx.URL(config.base_url).host
        cookies = self._cookies_loader(host)
        if not cookies:
            raise SessionMissing("尚未导入会话。" + REIMPORT_HINT)
        client = GuardedClient(
            config.base_url,
            adapter_cls.rules,
            cookies,
            transport=self._transport,
            min_interval=config.min_interval,
        )
        return adapter_cls(client), client

    def _run(self, fn: Callable[[ZfsoftV9Adapter], Any]) -> Any:
        adapter, client = self._adapter()
        try:
            return fn(adapter)
        except SessionExpired as exc:
            raise SessionExpired(f"{exc}。{REIMPORT_HINT}") from exc
        finally:
            client.close()

    def timetable(self, year: int | None = None, term: int | None = None) -> dict[str, Any]:
        t = resolve_term(year, term)
        courses = self._run(lambda a: a.timetable(t))
        return {
            "term": t.model_dump(),
            "courses": [c.model_dump() for c in courses],
            "privacy_notice": PRIVACY_NOTICE,
        }

    def exams(self, year: int | None = None, term: int | None = None) -> dict[str, Any]:
        t = resolve_term(year, term)
        exams = self._run(lambda a: a.exams(t))
        return {
            "term": t.model_dump(),
            "exams": [e.model_dump() for e in exams],
            "privacy_notice": PRIVACY_NOTICE,
        }

    def grades(
        self, year: int | None = None, term: int | None = None, include_scores: bool = False
    ) -> dict[str, Any]:
        t = None if year is None and term is None else resolve_term(year, term)
        details = self._run(lambda a: a.grades(t))
        if include_scores:
            items = [d.model_dump() for d in details]
        else:
            fields = set(GradeSummary.model_fields)
            items = [GradeSummary(**d.model_dump(include=fields)).model_dump() for d in details]
        failed = sum(1 for d in details if d.passed is False)
        return {
            "term": t.model_dump() if t else "全部学期",
            "include_scores": include_scores,
            "failed_count": failed,
            "grades": items,
            "privacy_notice": PRIVACY_NOTICE,
        }

    def session_status(self) -> SessionStatus:
        try:
            adapter, client = self._adapter()
        except SessionMissing:
            return SessionStatus(imported=False, message="尚未导入会话。" + REIMPORT_HINT)
        except ProjectError as exc:
            return SessionStatus(imported=False, message=str(exc))
        try:
            valid = adapter.check_session()
        except ProjectError as exc:
            return SessionStatus(imported=True, valid=None, message=f"无法确认会话状态：{exc}")
        finally:
            client.close()
        if valid:
            return SessionStatus(imported=True, valid=True, message="会话有效。")
        return SessionStatus(imported=True, valid=False, message="会话已失效。" + REIMPORT_HINT)

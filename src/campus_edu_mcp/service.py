"""工具层业务逻辑（与 MCP 传输解耦，便于测试）。"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import httpx

from .adapters.qiangzhi import QiangzhiAdapter
from .adapters.zfsoft_v9 import ZfsoftV9Adapter
from .cookies import parse_cookie_text
from .errors import ConfigError, ProjectError, SessionExpired, SessionMissing
from .guard import GuardedClient
from .models import PRIVACY_NOTICE, GradeSummary, SessionStatus, Term
from .storage import Config, SessionStore, load_config
from .verification import ALLOW_UNVERIFIED_ENV, UNVERIFIED_VENDORS, meta


class _AdapterFactory(Protocol):
    vendor: Any
    rules: Any
    login_markers: Any

    def __call__(self, client: GuardedClient, **kwargs: Any) -> Any: ...


ADAPTERS: dict[str, Any] = {"qiangzhi": QiangzhiAdapter, "zfsoft_v9": ZfsoftV9Adapter}
IMPORT_HINT = "请在终端运行 `campus-edu-mcp import-session --cookie-file <文件>` 导入会话。"
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
    cookies = store.load(host)
    if cookies:
        return cookies
    file = os.environ.get("CAMPUS_EDU_COOKIE_FILE")
    if file:
        try:
            text = Path(file).read_text("utf-8")
        except OSError as exc:
            raise ConfigError("无法读取 CAMPUS_EDU_COOKIE_FILE 指向的文件") from exc
        return parse_cookie_text(text, host)
    raw = os.environ.get("CAMPUS_EDU_COOKIE")
    if raw:
        return parse_cookie_text(raw, host)
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
        self._vendor = config.vendor if config else "qiangzhi"

    def _adapter(self) -> tuple[Any, GuardedClient]:
        config = self._config or load_config()
        adapter_cls = ADAPTERS.get(config.vendor)
        if adapter_cls is None:
            raise ConfigError(f"不支持的厂商 {config.vendor}")
        if config.vendor in UNVERIFIED_VENDORS and os.environ.get(ALLOW_UNVERIFIED_ENV) != "1":
            raise ConfigError(
                f"厂商 {config.vendor} 的适配器尚未做 live 实测，默认禁用；"
                f"确认要试用请设置环境变量 {ALLOW_UNVERIFIED_ENV}=1"
            )
        self._vendor = config.vendor
        host = httpx.URL(config.base_url).host
        cookies = self._cookies_loader(host)
        if not cookies:
            raise SessionMissing("尚未导入会话。" + IMPORT_HINT)
        markers = getattr(adapter_cls, "login_markers", ("login_slogin", "/cas/login", "/login"))
        client = GuardedClient(
            config.base_url,
            adapter_cls.rules,
            cookies,
            transport=self._transport,
            min_interval=config.min_interval,
            login_markers=markers,
        )
        if adapter_cls is QiangzhiAdapter:
            return QiangzhiAdapter(
                client, exams_path=config.exams_path or "xsks/xsksap_list"
            ), client
        return adapter_cls(client), client

    def _run(self, fn: Callable[[Any], Any]) -> Any:
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
            "meta": meta(self._vendor, "timetable"),
            "privacy_notice": PRIVACY_NOTICE,
        }

    def exams(self, year: int | None = None, term: int | None = None) -> dict[str, Any]:
        t = resolve_term(year, term)
        exams = self._run(lambda a: a.exams(t))
        return {
            "term": t.model_dump(),
            "exams": [e.model_dump() for e in exams],
            "meta": meta(self._vendor, "exams"),
            "privacy_notice": PRIVACY_NOTICE,
        }

    def terms(self) -> dict[str, Any]:
        def call(adapter: Any) -> Any:
            fn = getattr(adapter, "terms", None)
            if fn is None:
                raise ConfigError(f"厂商 {self._vendor} 暂不支持查询学期列表")
            return fn()

        terms = self._run(call)
        return {
            "terms": [t.model_dump() for t in terms],
            "meta": meta(self._vendor, "terms"),
            "privacy_notice": PRIVACY_NOTICE,
        }

    def empty_classrooms(
        self,
        week: int,
        weekday: int,
        periods: list[str] | None = None,
        campus: str | None = None,
        year: int | None = None,
        term: int | None = None,
        min_capacity: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if not 1 <= week <= 30:
            raise ConfigError("week 应在 1-30 之间")
        if not 1 <= weekday <= 7:
            raise ConfigError("weekday 应在 1-7 之间（1=周一）")
        campus = campus or None
        if campus is not None and not campus.isdigit():
            raise ConfigError("campus 应为校区编号（数字）")
        limit = max(1, min(limit, 200))
        t = None if year is None and term is None else resolve_term(year, term)

        def call(adapter: Any) -> Any:
            fn = getattr(adapter, "empty_classrooms", None)
            if fn is None:
                raise ConfigError(f"厂商 {self._vendor} 暂不支持空闲教室查询")
            return fn(t, week, weekday, campus)

        period_list, rooms = self._run(call)
        known = {p.code for p in period_list}
        wanted = [p for p in (periods or []) if p]
        unknown = [p for p in wanted if p not in known]
        if unknown:
            raise ConfigError(f"未知节次 {','.join(unknown)}；可选：{','.join(sorted(known))}")
        matched = [
            r
            for r in rooms
            if all(p in r.free_periods for p in wanted)
            and (min_capacity is None or (r.capacity or 0) >= min_capacity)
            and (wanted or r.free_periods)
        ]
        matched.sort(key=lambda r: (-len(r.free_periods), r.name))
        return {
            "term": t.model_dump() if t else None,
            "week": week,
            "weekday": weekday,
            "periods": [p.model_dump() for p in period_list],
            "required_free": wanted,
            "total_matched": len(matched),
            "rooms": [r.model_dump() for r in matched[:limit]],
            "truncated": len(matched) > limit,
            "meta": meta(self._vendor, "empty_classrooms"),
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
            "term": t.model_dump() if t else None,  # None = 全部学期
            "include_scores": include_scores,
            "failed_count": failed,
            "grades": items,
            "meta": meta(self._vendor, "grades"),
            "privacy_notice": PRIVACY_NOTICE,
        }

    def session_status(self) -> SessionStatus:
        from .redact import redact

        try:
            adapter, client = self._adapter()
        except SessionMissing:
            return SessionStatus(imported=False, message="尚未导入会话。" + IMPORT_HINT)
        except ProjectError as exc:
            return SessionStatus(imported=False, message=redact(str(exc)))
        try:
            valid = adapter.check_session()
        except ProjectError as exc:
            return SessionStatus(
                imported=True, valid=None, message=redact(f"无法确认会话状态：{exc}")
            )
        finally:
            client.close()
        if valid:
            return SessionStatus(imported=True, valid=True, message="会话有效。")
        return SessionStatus(imported=True, valid=False, message="会话已失效。" + REIMPORT_HINT)

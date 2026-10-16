"""实验性：把课表导出为 iCalendar（RFC 5545）。

作息时间因校而异，**必须由用户提供**（JSON：``{"1": ["08:00", "08:45"], ...}``），
本模块不内置任何学校的作息。生成的时间为本地浮动时间（不带时区）。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path

from .errors import ConfigError
from .models import Course

_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
MAX_WEEK = 30


def load_periods(path: Path) -> dict[int, tuple[dt.time, dt.time]]:
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError("无法读取作息时间文件（需要 JSON）") from exc
    if not isinstance(raw, dict) or not raw:
        raise ConfigError('作息时间文件应为非空对象，如 {"1": ["08:00", "08:45"]}')
    periods: dict[int, tuple[dt.time, dt.time]] = {}
    for key, value in raw.items():
        if not str(key).isdigit() or not isinstance(value, list) or len(value) != 2:
            raise ConfigError(f"作息时间第 {key!r} 项格式错误")
        times = []
        for item in value:
            m = _TIME.match(str(item))
            if not m:
                raise ConfigError(f"作息时间第 {key!r} 项时间格式应为 HH:MM")
            times.append(dt.time(int(m.group(1)), int(m.group(2))))
        if times[0] >= times[1]:
            raise ConfigError(f"作息时间第 {key!r} 项开始时间应早于结束时间")
        periods[int(key)] = (times[0], times[1])
    return periods


def parse_weeks(text: str | None) -> list[int]:
    """``1-16周``、``1-8,10-16(周)``、``1-15(单周)``、``2-16双周`` → 周次列表。"""
    if not text:
        return []
    odd = "单" in text
    even = "双" in text
    weeks: set[int] = set()
    for a, b in re.findall(r"(\d{1,2})(?:\s*[-—~]\s*(\d{1,2}))?", text):
        start = int(a)
        end = int(b) if b else start
        if start > end:
            start, end = end, start
        for w in range(start, min(end, MAX_WEEK) + 1):
            if (odd and w % 2 == 0) or (even and w % 2 == 1):
                continue
            weeks.add(w)
    return sorted(w for w in weeks if 1 <= w <= MAX_WEEK)


def parse_sessions(text: str | None) -> tuple[int, int] | None:
    nums = [int(n) for n in re.findall(r"\d{1,2}", text or "")]
    if not nums:
        return None
    return min(nums), max(nums)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > 73:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    out.append(cur)
    return "\r\n".join(out)


def build_ics(
    courses: Iterable[Course],
    term_start: dt.date,
    periods: dict[int, tuple[dt.time, dt.time]],
    *,
    now: dt.datetime | None = None,
) -> tuple[str, int, int]:
    """返回 ``(ics 文本, 事件数, 跳过的课程数)``。term_start 会对齐到所在周的周一。"""
    monday = term_start - dt.timedelta(days=term_start.weekday())
    stamp = (now or dt.datetime.now(dt.UTC)).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//campus-edu-mcp//timetable export (experimental)//ZH",
        "CALSCALE:GREGORIAN",
    ]
    events = skipped = 0
    for course in courses:
        span = parse_sessions(course.sessions)
        weeks = parse_weeks(course.weeks)
        if (
            course.weekday is None
            or span is None
            or not weeks
            or span[0] not in periods
            or span[1] not in periods
        ):
            skipped += 1
            continue
        start_t, end_t = periods[span[0]][0], periods[span[1]][1]
        for week in weeks:
            day = monday + dt.timedelta(weeks=week - 1, days=course.weekday - 1)
            start = dt.datetime.combine(day, start_t)
            end = dt.datetime.combine(day, end_t)
            uid_src = f"{course.name}|{course.weekday}|{course.sessions}|{start.isoformat()}"
            uid = hashlib.sha256(uid_src.encode("utf-8")).hexdigest()[:24]
            lines += [
                "BEGIN:VEVENT",
                f"UID:{uid}@campus-edu-mcp.invalid",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
                _fold(f"SUMMARY:{_escape(course.name)}"),
            ]
            if course.place:
                lines.append(_fold(f"LOCATION:{_escape(course.place)}"))
            desc = "；".join(x for x in (course.teacher, course.sessions, f"第{week}周") if x)
            lines += [_fold(f"DESCRIPTION:{_escape(desc)}"), "END:VEVENT"]
            events += 1
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n", events, skipped

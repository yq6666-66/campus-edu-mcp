"""每个厂商、每个接口的 live 验证状态（对外以 ``meta`` 字段返回）。

* ``verified``：在至少一所真实学校做过只读实测，且距今不超过 :data:`STALE_AFTER_DAYS`；
* ``stale``：做过实测但已超过期限，学校可能已升级页面；
* ``pending``：只在 fixture / mock 上验证过，尚未 live 实测。

状态只描述「本项目做过什么」，不保证你的学校一定兼容。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

STALE_AFTER_DAYS = 183

VERIFIED_ON: dict[str, dict[str, str | None]] = {
    "qiangzhi": {
        "timetable": "2026-10-16",
        "exams": None,  # 仅实测过「无考试」页面，有数据时的解析未实测
        "grades": "2026-10-16",
        "session_status": "2026-10-16",
        "terms": "2026-10-16",
        "empty_classrooms": "2026-10-16",
        "password_login": None,
    },
    "zfsoft_v9": {
        "timetable": None,
        "exams": None,
        "grades": None,
        "session_status": None,
    },
}

UNVERIFIED_VENDORS = frozenset({"zfsoft_v9"})
ALLOW_UNVERIFIED_ENV = "CAMPUS_EDU_ALLOW_UNVERIFIED"


def status_of(date_text: str | None, today: dt.date | None = None) -> str:
    if not date_text:
        return "pending"
    try:
        day = dt.date.fromisoformat(date_text)
    except ValueError:
        return "pending"
    today = today or dt.date.today()
    return "stale" if (today - day).days > STALE_AFTER_DAYS else "verified"


def meta(vendor: str, endpoint: str, today: dt.date | None = None) -> dict[str, Any]:
    last = VERIFIED_ON.get(vendor, {}).get(endpoint)
    return {
        "vendor": vendor,
        "endpoint": endpoint,
        "status": status_of(last, today),
        "last_verified": last,
    }

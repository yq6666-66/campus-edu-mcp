"""学校登记表：``schools/*.yaml``，只读取扁平的 ``key: value``（不引入 YAML 依赖）。

登记表只描述「某类部署」的公开信息；仓库内只放虚构的示例学校。
``last_verified`` 超过 :data:`~campus_edu_mcp.verification.STALE_AFTER_DAYS` 天视为 stale，
从未实测为 pending。
"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from .verification import status_of

REQUIRED = ("school_id", "vendor", "base_url")
_KEY = re.compile(r"^([a-z_]+):\s*(.*)$")


@dataclass(frozen=True)
class School:
    school_id: str
    vendor: str
    base_url: str
    name: str | None = None
    last_verified: str | None = None
    exams_path: str | None = None

    def status(self, today: dt.date | None = None) -> str:
        return status_of(self.last_verified, today)


def parse_school(text: str) -> School:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line[0] in " \t#":
            continue  # 注释与缩进的多行块（如 notes: |）一律跳过
        m = _KEY.match(line)
        if not m:
            continue
        raw = m.group(2).strip()
        if raw[:1] in ("'", '"') and raw.count(raw[0]) >= 2:
            value = raw[1 : raw.index(raw[0], 1)]
        else:
            value = raw.split(" #", 1)[0].strip()
        if value and value != "|":
            fields[m.group(1)] = value
    missing = [k for k in REQUIRED if k not in fields]
    if missing:
        raise ValueError(f"学校配置缺少字段 {','.join(missing)}")
    url = httpx.URL(fields["base_url"])
    if url.scheme not in {"http", "https"} or not url.host:
        raise ValueError("base_url 必须是 http(s) 绝对地址")
    return School(
        school_id=fields["school_id"],
        vendor=fields["vendor"],
        base_url=fields["base_url"],
        name=fields.get("name"),
        last_verified=fields.get("last_verified"),
        exams_path=fields.get("exams_path"),
    )


def schools_dir() -> Path | None:
    """``CAMPUS_EDU_SCHOOLS_DIR`` 优先；否则源码仓库根目录的 ``schools/``。

    pip 安装后仓库目录不存在，需要显式设置环境变量。
    """
    override = os.environ.get("CAMPUS_EDU_SCHOOLS_DIR")
    if override:
        return Path(override)
    dev = Path(__file__).resolve().parents[2] / "schools"
    return dev if dev.is_dir() else None


def list_schools(directory: Path | None = None) -> list[tuple[str, School | None, str | None]]:
    """返回 ``(文件名, School 或 None, 错误信息)``，坏文件不会中断整个列表。"""
    directory = directory or schools_dir()
    if directory is None or not directory.is_dir():
        return []
    result: list[tuple[str, School | None, str | None]] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            result.append((path.name, parse_school(path.read_text("utf-8")), None))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            result.append((path.name, None, str(exc)))
    return result


def find_school(school_id: str, directory: Path | None = None) -> School | None:
    for _name, school, _err in list_schools(directory):
        if school is not None and school.school_id == school_id:
            return school
    return None

"""对外返回的数据模型。默认模型刻意不含学号、姓名、排名与分数。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

PRIVACY_NOTICE = (
    "提示：本结果由你本机的 campus-edu-mcp 读取，但如果你使用的是云端模型，"
    "它已经作为对话内容发送给了模型服务商。"
)


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Course(_Base):
    name: str
    teacher: str | None = None
    weekday: int | None = Field(default=None, ge=1, le=7, description="1=周一 … 7=周日")
    sessions: str | None = Field(default=None, description="节次，如 1-2节")
    weeks: str | None = Field(default=None, description="上课周，如 1-16周")
    place: str | None = None
    campus: str | None = None
    credit: float | None = None


class Exam(_Base):
    name: str
    time: str | None = None
    place: str | None = None
    campus: str | None = None
    seat: str | None = None


class GradeSummary(_Base):
    """默认的成绩视图：只有是否通过与学分，不含分数、绩点、排名。"""

    course: str
    year: str | None = None
    term: str | None = None
    credit: float | None = None
    nature: str | None = Field(default=None, description="课程性质，如 必修")
    passed: bool | None = Field(default=None, description="None 表示无法判断")


class ScoreDetail(GradeSummary):
    """仅当调用方显式要求分数时返回。"""

    score: str | None = None
    grade_point: float | None = None


class Term(_Base):
    year: int = Field(ge=2000, le=2100, description="学年起始年，如 2025 表示 2025-2026 学年")
    term: int = Field(ge=1, le=3, description="1=第一学期 2=第二学期 3=小学期")


class SessionStatus(_Base):
    imported: bool
    valid: bool | None = None
    message: str


class TermOption(_Base):
    """教务系统学期下拉框中的一个学期。"""

    year: int = Field(ge=2000, le=2100, description="学年起始年")
    term: int = Field(ge=1, le=3)
    label: str
    current: bool = Field(default=False, description="是否为页面默认选中的学期")

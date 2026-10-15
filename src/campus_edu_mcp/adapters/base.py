"""适配器协议。新增厂商时实现 :class:`Adapter`，并声明自己的只读白名单。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Protocol

from ..guard import GuardedClient, Rule
from ..models import Course, Exam, ScoreDetail, Term


class Adapter(Protocol):
    vendor: ClassVar[str]
    rules: ClassVar[Sequence[Rule]]

    def __init__(self, client: GuardedClient) -> None: ...

    def check_session(self) -> bool: ...

    def timetable(self, term: Term) -> list[Course]: ...

    def exams(self, term: Term) -> list[Exam]: ...

    def grades(self, term: Term | None) -> list[ScoreDetail]:
        """返回完整成绩；是否裁剪为 GradeSummary 由工具层决定。"""
        ...

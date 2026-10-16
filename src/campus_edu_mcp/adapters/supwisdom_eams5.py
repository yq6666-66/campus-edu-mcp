"""树维 Supwisdom 新一代 EAMS（EAMS5）只读适配器骨架。

状态：**未 live 实测**（``pending``）。默认禁用，需 ``CAMPUS_EDU_ALLOW_UNVERIFIED=1``。

v1.1 只开放登录前公开 GET（登录页、``login-salt``）。课表 / 成绩 / 考试路径
（如 ``for-std/*``、``ws/schedule-table/datum``）已见公开文档，但**未登记进白名单**，
等用户贡献脱敏 HAR 后再加入。见 ``docs/har-contribution.md``、``docs/supported-vendors.md``。

不做密码登录（``POST login`` / sha1(salt+pwd)）；会话只能通过 ``import-session`` 导入 Cookie。
未复制任何 GPL 项目代码。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from httpx import Response

from ..errors import ConfigError, SessionExpired, UpstreamError
from ..guard import GuardedClient, Rule
from ..htmlutil import looks_like_login
from ..models import Course, Exam, ScoreDetail, Term

PREFIXES = ("student", "eams5-student")
PENDING = (
    "树维新 EAMS（supwisdom_eams5）适配器尚未 live 实测："
    "课表/成绩/考试路径待脱敏 HAR 确认后才会加入白名单。"
    "当前仅支持 Cookie 导入与公开路径探测（campus-edu-mcp detect-vendor）。"
)


def _rules_for(prefix: str) -> tuple[Rule, ...]:
    return (
        Rule("GET", "", description=f"{prefix} 根（登录页）"),
        Rule("GET", "login", description=f"{prefix} 登录页"),
        Rule("GET", "login-salt", description=f"{prefix} 登录盐（公开 GET，只读探测）"),
        Rule("GET", "home", description=f"{prefix} 首页（无会话时常重定向到登录）"),
    )


RULES_STUDENT: Sequence[Rule] = _rules_for("student")
RULES_EAMS5: Sequence[Rule] = _rules_for("eams5-student")


class SupwisdomEams5Adapter:
    vendor: ClassVar[str] = "supwisdom_eams5"
    rules: ClassVar[Sequence[Rule]] = RULES_STUDENT
    login_markers: ClassVar[tuple[str, ...]] = (
        "/login",
        "login-salt",
        "/cas/login",
        "authserver/login",
    )

    def __init__(self, client: GuardedClient, *, prefix: str = "student") -> None:
        if prefix not in PREFIXES:
            raise ConfigError(f"student_prefix 仅允许 student 或 eams5-student，当前为 {prefix!r}")
        self.client = client
        self.prefix = prefix
        # 相对路径与 ClassVar RULES 相同；前缀写在 base_url 里

    def _text(self, response: Response) -> str:
        if response.status_code in (401, 403):
            raise SessionExpired("会话已失效，请重新导入会话")
        if response.status_code != 200:
            raise UpstreamError(f"教务系统返回 HTTP {response.status_code}")
        text = response.text
        if looks_like_login(text):
            raise SessionExpired("会话已失效（返回了登录页），请重新导入会话")
        return text

    def check_session(self) -> bool:
        """用公开首页探测：有有效会话时多为 200 HTML；否则重定向到登录 → False。"""
        try:
            response = self.client.get("home")
        except SessionExpired:
            return False
        if response.is_redirect:
            return False
        try:
            self._text(response)
        except SessionExpired:
            return False
        except UpstreamError:
            return False
        return True

    def _pending(self, feature: str) -> None:
        raise ConfigError(f"{feature}：{PENDING}")

    def timetable(self, term: Term) -> list[Course]:
        self._pending("get_timetable")
        return []

    def exams(self, term: Term) -> list[Exam]:
        self._pending("get_exams")
        return []

    def grades(self, term: Term | None) -> list[ScoreDetail]:
        self._pending("get_grades")
        return []

    def terms(self) -> list[Term]:
        self._pending("get_terms")
        return []

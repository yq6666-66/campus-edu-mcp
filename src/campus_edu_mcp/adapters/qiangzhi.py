"""强智教务（jsxsd 学生端）只读适配器。

端点依据公开资料与一所强智校的只读实测整理（见 docs/qiangzhi-notes.md）。
部分部署同时存在根路径 ``/Logon.do`` 与 ``/jsxsd/`` 两套入口；本适配器面向
``/jsxsd/`` 学生端。

未复制任何 GPL / MPL 项目的代码；HTML 解析逻辑为自行实现。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import ClassVar

from httpx import Response

from ..errors import SessionExpired, UpstreamError
from ..gradesutil import judge_passed
from ..guard import GuardedClient, Rule
from ..htmlutil import (
    has_kb_table,
    looks_like_login,
    parse_kbcontent_blocks,
    select_options,
    selected_option,
    table_rows,
)
from ..models import Course, Exam, ScoreDetail, Term, TermOption

_TERM_ID = r"20\d{2}-20\d{2}-[123]"
_PARAM_TOKEN = r"[A-Za-z0-9_]{0,40}"  # noqa: S105
_TEXT = r"[\w\u4e00-\u9fff%+.\-]{0,40}"

TIMETABLE_PATH = "xskb/xskb_list.do"
GRADES_PATHS = ("kscj/cjcx_list", "kscj/cjcx_list.do")
EXAMS_PATHS = ("xsks/xsksap_list", "xsks/xsksap_list.do")  # 路径因校而异，需自测

RULES: Sequence[Rule] = (
    Rule(
        "GET",
        TIMETABLE_PATH,
        free={
            "xnxq01id": _TERM_ID,
            "Ves632DSdyV": _PARAM_TOKEN,
            "sfFD": r"[01]?",
            "cj0701id": _PARAM_TOKEN,
            "zc": r"(\d{1,2})?",
            "kbjcmsid": _PARAM_TOKEN,
        },
        description="学期理论课表（GET）",
    ),
    Rule(
        "POST",
        TIMETABLE_PATH,
        free={
            "xnxq01id": _TERM_ID,
            "Ves632DSdyV": _PARAM_TOKEN,
            "sfFD": r"[01]?",
            "cj0701id": _PARAM_TOKEN,
            "zc": r"(\d{1,2})?",
            "kbjcmsid": _PARAM_TOKEN,
        },
        description="学期理论课表（POST）",
    ),
    *(
        Rule(
            method,
            path,
            free={
                "kksj": rf"({_TERM_ID})?",
                "kcxz": _TEXT,
                "kcmc": _TEXT,
                "xsfs": r"(all|[A-Za-z]{0,10})",
            },
            description=f"成绩查询（{method} {path}）",
        )
        for path in GRADES_PATHS
        for method in ("GET", "POST")
    ),
    *(
        Rule(
            method,
            path,
            free={"xnxqid": _TERM_ID, "xnxq01id": _TERM_ID},
            description=f"考试安排（{method} {path}，路径因校而异）",
        )
        for path in EXAMS_PATHS
        for method in ("GET", "POST")
    ),
)


def term_id(term: Term) -> str:
    """把通用 Term 转成强智常见的 ``YYYY-YYYY-N``。"""
    return f"{term.year}-{term.year + 1}-{term.term}"


def _header_index(header: list[str], *names: str) -> int | None:
    for i, cell in enumerate(header):
        for name in names:
            if name in cell:
                return i
    return None


def _cell(row: list[str], index: int | None) -> str | None:
    if index is None or index >= len(row):
        return None
    value = row[index].strip()
    return value or None


class QiangzhiAdapter:
    vendor: ClassVar[str] = "qiangzhi"
    rules: ClassVar[Sequence[Rule]] = RULES
    login_markers: ClassVar[tuple[str, ...]] = (
        "LoginToXk",
        "Logon.do",
        "/login",
        "verifycode.servlet",
    )

    def __init__(self, client: GuardedClient, *, exams_path: str = EXAMS_PATHS[0]) -> None:
        self.client = client
        self.exams_path = exams_path if exams_path in EXAMS_PATHS else EXAMS_PATHS[0]
        self.grades_path = GRADES_PATHS[0]

    def _request(self, method: str, path: str, data: dict[str, str] | None = None) -> str:
        if method == "GET":
            response = self.client.get(path, params=data or {})
        else:
            response = self.client.post_form(path, params={}, data=data or {})
        return self._text(response)

    @staticmethod
    def _text(response: Response) -> str:
        if response.status_code in (401, 403):
            raise SessionExpired("会话已失效，请重新导入会话")
        if response.status_code != 200:
            raise UpstreamError(f"教务系统返回 HTTP {response.status_code}")
        text = response.text
        if looks_like_login(text):
            raise SessionExpired("会话已失效（返回了登录页），请重新导入会话")
        return text

    def check_session(self) -> bool:
        try:
            self._request("GET", TIMETABLE_PATH, {})
        except SessionExpired:
            return False
        return True

    def terms(self) -> list[TermOption]:
        """从课表页的 ``xnxq01id`` 下拉框读取可选学期（只读 GET，复用课表白名单）。"""
        html = self._request("GET", TIMETABLE_PATH, {})
        options = select_options(html, "xnxq01id")
        if not options:
            raise UpstreamError("课表页缺少学期下拉框 xnxq01id，页面结构可能已变更")
        result: list[TermOption] = []
        seen: set[str] = set()
        for value, label, selected in options:
            if value in seen or not re.fullmatch(_TERM_ID, value):
                continue
            seen.add(value)
            start, _end, num = value.split("-")
            result.append(
                TermOption(year=int(start), term=int(num), label=label or value, current=selected)
            )
        result.sort(key=lambda t: (t.year, t.term), reverse=True)
        return result

    def timetable(self, term: Term) -> list[Course]:
        # 先 GET 拿当前页（许多学校不带参数即当前学期），再按需 POST 切换学期。
        html = self._request("GET", TIMETABLE_PATH, {})
        selected = selected_option(html, "xnxq01id")
        wanted = term_id(term)
        if selected != wanted:
            html = self._request("POST", TIMETABLE_PATH, {"xnxq01id": wanted})
        if not has_kb_table(html):
            raise UpstreamError("课表页缺少 #timetable/#kbtable，页面结构可能已变更")
        courses = [
            Course(
                name=str(item["name"]),
                teacher=item["teacher"] if isinstance(item["teacher"], str) else None,
                weekday=item["weekday"] if isinstance(item["weekday"], int) else None,
                sessions=item["sessions"] if isinstance(item["sessions"], str) else None,
                weeks=item["weeks"] if isinstance(item["weeks"], str) else None,
                place=item["place"] if isinstance(item["place"], str) else None,
                campus=None,
                credit=None,
            )
            for item in parse_kbcontent_blocks(html)
        ]
        courses.sort(key=lambda c: (c.weekday or 8, _first_number(c.sessions)))
        return courses

    def exams(self, term: Term) -> list[Exam]:
        """考试安排路径与表头因校而异，当前按公开资料的 ``xsks/xsksap_list`` 实现。"""
        html = self._request("POST", self.exams_path, {"xnxqid": term_id(term)})
        rows = table_rows(html, "dataList")
        if not rows:
            # 有的部署表单参数名是 xnxq01id
            html = self._request("POST", self.exams_path, {"xnxq01id": term_id(term)})
            rows = table_rows(html, "dataList")
        if len(rows) < 2:
            return []
        header, body = rows[0], rows[1:]
        # 强智在无考试时常用一行 colspan 提示，而不是 0 行
        if len(body) == 1 and len(body[0]) <= 2:
            return []
        i_name = _header_index(header, "课程名称", "课程")
        if i_name is None:
            raise UpstreamError("考试表缺少「课程名称」列，页面结构可能已变更")
        i_time = _header_index(header, "考试时间", "时间")
        i_place = _header_index(header, "考场", "考试地点", "地点")
        i_campus = _header_index(header, "考试校区", "校区")
        i_seat = _header_index(header, "座位号", "座号", "座位")
        exams = []
        for row in body:
            name = _cell(row, i_name)
            if not name:
                continue
            exams.append(
                Exam(
                    name=name,
                    time=_cell(row, i_time),
                    place=_cell(row, i_place),
                    campus=_cell(row, i_campus),
                    seat=_cell(row, i_seat),
                )
            )
        exams.sort(key=lambda e: e.time or "~")
        return exams

    def grades(self, term: Term | None) -> list[ScoreDetail]:
        data = {
            "kksj": term_id(term) if term else "",
            "kcxz": "",
            "kcmc": "",
            "xsfs": "all",
        }
        html = self._request("POST", self.grades_path, data)
        rows = table_rows(html, "dataList")
        if len(rows) < 2:
            return []
        header, body = rows[0], rows[1:]
        i_term = _header_index(header, "开课学期", "学期")
        i_name = _header_index(header, "课程名称")
        if i_name is None:
            raise UpstreamError("成绩表缺少「课程名称」列，页面结构可能已变更")
        i_score = _header_index(header, "成绩")
        i_credit = _header_index(header, "学分")
        i_gp = _header_index(header, "绩点")
        i_nature = _header_index(header, "课程性质", "课程属性")
        result = []
        for row in body:
            name = _cell(row, i_name)
            if not name:
                continue
            score = _cell(row, i_score)
            term_text = _cell(row, i_term)
            year = term_num = None
            if term_text and re.fullmatch(_TERM_ID, term_text):
                year = term_text[:9]
                term_num = term_text.split("-")[-1]
            credit_s = _cell(row, i_credit)
            gp_s = _cell(row, i_gp)
            try:
                credit = float(credit_s) if credit_s else None
            except ValueError:
                credit = None
            try:
                grade_point = float(gp_s) if gp_s else None
            except ValueError:
                grade_point = None
            result.append(
                ScoreDetail(
                    course=name,
                    year=year,
                    term=term_num,
                    credit=credit,
                    nature=_cell(row, i_nature),
                    passed=judge_passed(score),
                    score=score,
                    grade_point=grade_point,
                )
            )
        return result


def _first_number(text: str | None) -> int:
    match = re.search(r"\d+", text or "")
    return int(match.group(0)) if match else 99

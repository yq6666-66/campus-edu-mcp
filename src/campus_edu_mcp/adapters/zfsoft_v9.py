"""正方教务 V9（新正方，路径通常形如 /jwglxt/）只读适配器。

接口路径与字段名来自对公开页面结构的观察（参考 openschoolcn/zfn_api 的协议说明，
未复制其代码）。各校部署可能不同，live 验证见 README。
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Sequence
from typing import Any, ClassVar

import httpx

from ..errors import SessionExpired, UpstreamError
from ..guard import GuardedClient, Rule
from ..models import Course, Exam, ScoreDetail, Term

TERM_CODE = {1: "3", 2: "12", 3: "16"}
_YEAR = r"20\d{2}"
_TERM = r"(3|12|16)?"
_COUNT = r"[1-9]\d{0,3}"

TIMETABLE_PATH = "kbcx/xskbcx_cxXsKb.html"
EXAMS_PATH = "kwgl/kscx_cxXsksxxIndex.html"
GRADES_PATH = "cjcx/cjcx_cxXsgrcj.html"

_PAGING = {
    "queryModel.showCount": _COUNT,
    "queryModel.currentPage": r"[1-9]\d{0,2}",
    "queryModel.sortName": r"[A-Za-z_ ]{0,20}",
    "queryModel.sortOrder": r"(asc|desc)?",
    "_search": r"(true|false)",
    "nd": r"\d{1,16}",
    "time": r"\d{1,3}",
}

RULES: Sequence[Rule] = (
    Rule(
        "POST",
        TIMETABLE_PATH,
        fixed={"gnmkdm": frozenset({"N2151"})},
        free={"xnm": _YEAR, "xqm": r"(3|12|16)", "kzlx": r"(ck)?", "xsdm": r"[0-9A-Za-z]{0,8}"},
        description="个人课表查询",
    ),
    Rule(
        "POST",
        EXAMS_PATH,
        fixed={"doType": frozenset({"query"}), "gnmkdm": frozenset({"N358105"})},
        free={"xnm": _YEAR, "xqm": _TERM, "ksmcdmb_id": r"[0-9A-Za-z]{0,40}", **_PAGING},
        description="个人考试安排查询",
    ),
    Rule(
        "POST",
        GRADES_PATH,
        fixed={"doType": frozenset({"query"}), "gnmkdm": frozenset({"N305005"})},
        free={"xnm": r"(20\d{2})?", "xqm": _TERM, **_PAGING},
        description="个人成绩查询",
    ),
)

_PASS_WORDS = ("优秀", "良好", "中等", "及格", "合格", "通过", "优", "良", "中", "A", "B", "C", "D")
_FAIL_WORDS = ("不及格", "不合格", "不通过", "未通过", "缺考", "F", "E")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _float(value: Any) -> float | None:
    s = _text(value)
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    f = _float(value)
    return int(f) if f is not None else None


def judge_passed(score: str | None, percent: str | None = None) -> bool | None:
    """根据成绩判断是否通过；无法判断时返回 None。"""
    for candidate in (percent, score):
        num = _float(candidate)
        if num is not None:
            return num >= 60
    if score is None:
        return None
    if any(score.startswith(w) for w in _FAIL_WORDS):
        return False
    if any(score.startswith(w) for w in _PASS_WORDS):
        return True
    return None


class ZfsoftV9Adapter:
    vendor: ClassVar[str] = "zfsoft_v9"
    rules: ClassVar[Sequence[Rule]] = RULES

    def __init__(self, client: GuardedClient) -> None:
        self.client = client

    # ---- 内部 ----
    def _post_json(self, path: str, params: dict[str, str], data: dict[str, str]) -> dict[str, Any]:
        response = self.client.post_form(path, params, data)
        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> dict[str, Any]:
        if response.status_code in (401, 403):
            raise SessionExpired("会话已失效，请重新导入会话")
        if response.status_code != 200:
            raise UpstreamError(f"教务系统返回 HTTP {response.status_code}")
        text = response.text
        ctype = response.headers.get("content-type", "")
        if "html" in ctype or text.lstrip().startswith("<"):
            if "用户登录" in text or "login_slogin" in text:
                raise SessionExpired("会话已失效（返回了登录页），请重新导入会话")
            raise UpstreamError("教务系统返回了非预期的 HTML 页面")
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise UpstreamError("教务系统返回的不是合法 JSON") from exc
        if not isinstance(payload, dict):
            raise UpstreamError("教务系统返回的 JSON 结构非预期")
        return payload

    @staticmethod
    def _term_data(term: Term | None) -> dict[str, str]:
        if term is None:
            return {"xnm": "", "xqm": ""}
        return {"xnm": str(term.year), "xqm": TERM_CODE[term.term]}

    # ---- 公开接口 ----
    def check_session(self) -> bool:
        """用当前学期课表查询探测会话（比成绩敏感度低）。"""
        today = dt.date.today()
        year = today.year if today.month >= 8 else today.year - 1
        try:
            self._post_json(
                TIMETABLE_PATH, {"gnmkdm": "N2151"}, {"xnm": str(year), "xqm": "3", "kzlx": "ck"}
            )
        except SessionExpired:
            return False
        return True

    def timetable(self, term: Term) -> list[Course]:
        payload = self._post_json(
            TIMETABLE_PATH, {"gnmkdm": "N2151"}, {**self._term_data(term), "kzlx": "ck"}
        )
        rows = payload.get("kbList") or []
        courses = []
        for row in rows:
            name = _text(row.get("kcmc"))
            if not name:
                continue
            weekday = _int(row.get("xqj"))
            courses.append(
                Course(
                    name=name,
                    teacher=_text(row.get("xm")),
                    weekday=weekday if weekday and 1 <= weekday <= 7 else None,
                    sessions=_text(row.get("jc")),
                    weeks=_text(row.get("zcd")),
                    place=_text(row.get("cdmc")),
                    campus=_text(row.get("xqmc")),
                    credit=_float(row.get("xf")),
                )
            )
        courses.sort(key=lambda c: (c.weekday or 8, _first_number(c.sessions)))
        return courses

    def exams(self, term: Term) -> list[Exam]:
        payload = self._post_json(
            EXAMS_PATH,
            {"doType": "query", "gnmkdm": "N358105"},
            {**self._term_data(term), "queryModel.showCount": "200"},
        )
        exams = []
        for row in payload.get("items") or []:
            name = _text(row.get("kcmc"))
            if not name:
                continue
            exams.append(
                Exam(
                    name=name,
                    time=_text(row.get("kssj")),
                    place=_text(row.get("cdmc")),
                    campus=_text(row.get("cdxqmc")),
                    seat=_text(row.get("zwh")),
                )
            )
        exams.sort(key=lambda e: e.time or "~")
        return exams

    def grades(self, term: Term | None) -> list[ScoreDetail]:
        payload = self._post_json(
            GRADES_PATH,
            {"doType": "query", "gnmkdm": "N305005"},
            {**self._term_data(term), "queryModel.showCount": "500"},
        )
        result = []
        for row in payload.get("items") or []:
            name = _text(row.get("kcmc"))
            if not name:
                continue
            score = _text(row.get("cj"))
            result.append(
                ScoreDetail(
                    course=name,
                    year=_text(row.get("xnmmc")),
                    term=_text(row.get("xqmmc")),
                    credit=_float(row.get("xf")),
                    nature=_text(row.get("kcxzmc")),
                    passed=judge_passed(score, _text(row.get("bfzcj"))),
                    score=score,
                    grade_point=_float(row.get("jd")),
                )
            )
        return result


def _first_number(text: str | None) -> int:
    match = re.search(r"\d+", text or "")
    return int(match.group(0)) if match else 99

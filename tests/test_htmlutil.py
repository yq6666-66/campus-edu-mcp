from __future__ import annotations

from pathlib import Path

from campus_edu_mcp.htmlutil import (
    looks_like_login,
    parse_kbcontent_blocks,
    parse_period_label,
    selected_option,
    table_rows,
)

FIX = Path(__file__).parent / "fixtures" / "qiangzhi"


def test_parse_period_label() -> None:
    assert parse_period_label("第1-2节") == "1-2节"
    assert parse_period_label("第一大节\xa0\n (01,02小节)") == "1-2节"
    assert parse_period_label("第五大节 (09,10,11小节)") == "9-10节"


def test_parse_timetable_fixture() -> None:
    html = (FIX / "timetable.html").read_text("utf-8")
    assert selected_option(html, "xnxq01id") == "2098-2099-1"
    courses = parse_kbcontent_blocks(html)
    assert len(courses) == 6
    assert {c["weekday"] for c in courses} <= set(range(1, 8))
    assert all(c.get("teacher") for c in courses)


def test_parse_classic_kbtable() -> None:
    html = """
    <table id="kbtable">
      <tr><th></th><th>星期一</th><th>星期二</th></tr>
      <tr>
        <th>第1-2节</th>
        <td><div class="kbcontent">测试课A<br/><font title="老师">张老师A</font>
        <br/><font title="周次(节次)">1-8周</font>
        <br/><font title="教室">虚构楼1</font></div></td>
        <td><div class="kbcontent">&nbsp;</div></td>
      </tr>
    </table>
    """
    courses = parse_kbcontent_blocks(html)
    assert len(courses) == 1
    assert courses[0]["name"] == "测试课A"
    assert courses[0]["teacher"] == "张老师A"
    assert courses[0]["sessions"] == "1-2节"


def test_table_rows_grades_and_exams() -> None:
    grades = table_rows((FIX / "grades.html").read_text("utf-8"), "dataList")
    assert grades[0][3] == "课程名称"
    assert any("58" in row for row in grades[1:])
    exams = table_rows((FIX / "exams.html").read_text("utf-8"), "dataList")
    assert len(exams) == 5


def test_looks_like_login() -> None:
    assert looks_like_login((FIX / "login_page.html").read_text("utf-8"))
    assert not looks_like_login((FIX / "timetable.html").read_text("utf-8"))

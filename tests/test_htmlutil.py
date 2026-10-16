from __future__ import annotations

from pathlib import Path

from campus_edu_mcp.htmlutil import (
    looks_like_login,
    parse_kbcontent_blocks,
    selected_option,
    table_rows,
)

FIX = Path(__file__).parent / "fixtures" / "qiangzhi"


def test_parse_timetable_fixture() -> None:
    html = (FIX / "timetable.html").read_text("utf-8")
    assert selected_option(html, "xnxq01id") == "2098-2099-1"
    courses = parse_kbcontent_blocks(html)
    assert len(courses) == 6
    names = {c["name"] for c in courses}
    assert "高等数学A（虚拟）" in names
    assert all(c["weekday"] in range(1, 8) for c in courses)
    assert all("老师" not in str(c["name"]) for c in courses)


def test_table_rows_grades_and_exams() -> None:
    grades = table_rows((FIX / "grades.html").read_text("utf-8"), "dataList")
    assert grades[0][3] == "课程名称"
    assert any("58" in row for row in grades[1:])
    exams = table_rows((FIX / "exams.html").read_text("utf-8"), "dataList")
    assert len(exams) == 5  # header + 4


def test_looks_like_login() -> None:
    assert looks_like_login((FIX / "login_page.html").read_text("utf-8"))
    assert not looks_like_login((FIX / "timetable.html").read_text("utf-8"))

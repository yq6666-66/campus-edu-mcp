"""检查 fixture 中没有真实学号、姓名、身份证号或 Cookie。CI 与 pre-commit 都会运行。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT / "tests" / "fixtures", ROOT / "mock_server"]
SUFFIXES = {".json", ".html", ".txt", ".py"}

ALLOWED_STUDENT_ID = re.compile(r"^2099\d{6}$")
ALLOWED_STUDENT_NAMES = {"测试学生"}
ALLOWED_TEACHER = re.compile(r"^[\u4e00-\u9fa5]老师[A-Z]$")

ID_FIELD = re.compile(r"""["'](xh|XH|xh_id|yhm|sid)["']\s*:\s*["']([^"']*)["']""")
NAME_FIELD = re.compile(r"""["'](xm|XM|xsxm)["']\s*:\s*["']([^"']*)["']""")
LONG_DIGITS = re.compile(r"(?<![\d.])\d{10,18}[\dXx]?(?![\d.])")
ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
SECRET = re.compile(
    r"(?i)(JSESSIONID|route)\s*[=:]\s*[\"']?(?!FAKE|fake|test|TEST)[0-9A-Za-z]{12,}"
)


def check_text(text: str, name: str) -> list[str]:
    problems: list[str] = []
    for m in ID_FIELD.finditer(text):
        if not ALLOWED_STUDENT_ID.match(m.group(2)):
            problems.append(f"{name}: 学号字段 {m.group(1)} 不是虚构号（须 2099 开头 10 位）")
    for m in NAME_FIELD.finditer(text):
        value = m.group(2)
        if value not in ALLOWED_STUDENT_NAMES and not ALLOWED_TEACHER.match(value):
            problems.append(f"{name}: 姓名字段 {m.group(1)}={value!r} 不在允许的虚构名单内")
    for m in LONG_DIGITS.finditer(text):
        if not m.group(0).startswith("2099") and not m.group(0).startswith("1" * 6):
            problems.append(f"{name}: 疑似真实证件号/学号 {m.group(0)[:4]}…")
    if ID_CARD.search(text):
        problems.append(f"{name}: 疑似身份证号")
    if SECRET.search(text):
        problems.append(f"{name}: 疑似真实会话 Cookie")
    return problems


def main() -> int:
    problems: list[str] = []
    count = 0
    for base in TARGETS:
        for path in sorted(base.rglob("*")):
            if path.suffix in SUFFIXES and path.is_file():
                count += 1
                problems.extend(check_text(path.read_text("utf-8"), str(path.relative_to(ROOT))))
    for line in problems:
        print(line)
    if problems:
        return 1
    print(f"fixture 隐私检查通过（{count} 个文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

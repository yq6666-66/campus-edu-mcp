"""极简 HTML 抽取，只覆盖强智课表 / 表格场景，避免引入额外依赖。"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser


class _TableParser(HTMLParser):
    def __init__(self, table_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.table_id = table_id
        self.in_table = False
        self.depth = 0
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._capture = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        if tag == "table" and attrs_d.get("id") == self.table_id:
            self.in_table = True
            self.depth = 1
            return
        if not self.in_table:
            return
        if tag == "table":
            self.depth += 1
        if self.depth != 1:
            return
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
            self._capture = True
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self.in_table:
            return
        if tag == "table":
            self.depth -= 1
            if self.depth <= 0:
                self.in_table = False
            return
        if self.depth != 1:
            return
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            text = re.sub(r"[ \t]+", " ", "".join(self._cell)).strip()
            self._row.append(text)
            self._cell = None
            self._capture = False
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._capture and self._cell is not None:
            self._cell.append(data)


def table_rows(html_text: str, table_id: str) -> list[list[str]]:
    parser = _TableParser(table_id)
    parser.feed(html_text)
    return parser.rows


_DIV_BLOCK = re.compile(
    r'<div\s+class=["\']kbcontent["\'][^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_FONT = re.compile(
    r'<font[^>]*title=["\']([^"\']+)["\'][^>]*>(.*?)</font>',
    re.IGNORECASE | re.DOTALL,
)
_TAG = re.compile(r"<[^>]+>")
_SEP = re.compile(r"-{8,}")


def _strip_tags(fragment: str) -> str:
    text = _TAG.sub(" ", fragment)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def parse_kbcontent_blocks(html_text: str) -> list[dict[str, str | int | None]]:
    """从强智 ``#kbtable`` 中抽出课程块。

    结构依据多个公开项目对 ``kbcontent`` / ``font[title]`` 的描述自行实现，
    未复制其代码。各校 HTML 细节可能不同，live 验证前视为**未核实**。
    """
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, flags=re.I | re.S)
    courses: list[dict[str, str | int | None]] = []
    for row in rows:
        th = re.search(r"<th[^>]*>(.*?)</th>", row, flags=re.I | re.S)
        if not th:
            continue
        th_text = _strip_tags(th.group(1))
        period = re.search(r"第\s*(\d+)\s*[-—~至到]\s*(\d+)\s*节", th_text)
        if not period:
            continue
        sessions = f"{period.group(1)}-{period.group(2)}节"
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.I | re.S)
        for day, td in enumerate(tds[:7], start=1):
            for block in _DIV_BLOCK.findall(td):
                if "kbcontent1" in block:  # 不应匹配到，防御
                    continue
                parts = _SEP.split(block)
                for part in parts:
                    name = ""
                    fonts: dict[str, str] = {}
                    for title, inner in _FONT.findall(part):
                        fonts[title.strip()] = _strip_tags(inner)
                    cleaned = _FONT.sub("", part)
                    cleaned = _TAG.sub("\n", cleaned)
                    for line in cleaned.splitlines():
                        text = html.unescape(line).strip()
                        text = re.sub(r"\s*[PO]\s*$", "", text).strip()
                        if text and text not in {"&nbsp;", "\xa0"}:
                            name = text
                            break
                    if not name:
                        continue
                    weeks = fonts.get("周次(节次)") or fonts.get("周次") or ""
                    weeks = re.sub(r"\[.*?\]", "", weeks).strip()
                    courses.append(
                        {
                            "name": name,
                            "teacher": fonts.get("老师") or fonts.get("教师"),
                            "place": fonts.get("教室") or fonts.get("地点"),
                            "weeks": weeks or None,
                            "sessions": sessions,
                            "weekday": day,
                        }
                    )
    return courses


def looks_like_login(html_text: str) -> bool:
    markers = (
        'name="loginForm"',
        "LoginToXk",
        "Logon.do?method=logon",
        "verifycode.servlet",
        ">用户登录<",
        ">登录</title>",
        'name="RANDOMCODE"',
    )
    low = html_text[:4000]
    return any(m in low for m in markers)


def selected_option(html_text: str, select_name: str) -> str | None:
    pattern = re.compile(
        rf'<select[^>]*name=["\']{re.escape(select_name)}["\'][^>]*>(.*?)</select>',
        re.I | re.S,
    )
    match = pattern.search(html_text)
    if not match:
        return None
    selected = re.search(
        r'<option[^>]*value=["\']([^"\']+)["\'][^>]*selected', match.group(1), re.I
    )
    if selected:
        return selected.group(1)
    first = re.search(r'<option[^>]*value=["\']([^"\']+)["\']', match.group(1), re.I)
    return first.group(1) if first else None

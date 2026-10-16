"""极简 HTML 抽取，覆盖强智课表 / 表格场景，避免引入额外依赖。"""

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


_PERIOD_CLASSIC = re.compile(r"第\s*(\d+)\s*[-—~至到]\s*(\d+)\s*节")
_PERIOD_DAJIE = re.compile(
    r"第\s*([一二三四五六七八九十\d]+)\s*大节[\s\S]*?[\(（]\s*(\d+)\s*[,，、]\s*(\d+)(?:\s*[,，、]\s*(\d+))?\s*小节[\)）]"
)
_PERIOD_DAJIE_LOOSE = re.compile(r"第\s*([一二三四五六七八九十\d]+)\s*大节")
# 无「小节」括号时的常见映射（两小节一大节）
_DAJIE_DEFAULT_SESSIONS = {
    1: (1, 2),
    2: (3, 4),
    3: (5, 6),
    4: (7, 8),
    5: (9, 10),
    6: (11, 12),
    7: (13, 14),
    8: (15, 16),
}
_CN_NUM = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_TEACHER_TITLES = frozenset({"老师", "教师"})
_PLACE_TITLES = frozenset({"教室", "地点"})
_WEEK_TITLES = frozenset({"周次(节次)", "周次"})
_SEP = re.compile(r"-{8,}")


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _cn_or_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _CN_NUM.get(token)


def parse_period_label(text: str) -> str | None:
    """把表头节次文字规范成 ``1-2节``。"""
    text = html.unescape(text)
    m = _PERIOD_CLASSIC.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}节"
    m = _PERIOD_DAJIE.search(text)
    if m:
        start, end = m.group(2), m.group(3)
        return f"{int(start)}-{int(end)}节"
    m = _PERIOD_DAJIE_LOOSE.search(text)
    if m:
        n = _cn_or_int(m.group(1))
        if n is not None and n in _DAJIE_DEFAULT_SESSIONS:
            a, b = _DAJIE_DEFAULT_SESSIONS[n]
            return f"{a}-{b}节"
    return None


def has_kb_table(html_text: str) -> bool:
    """页面是否含强智课表表格（``#timetable`` / ``#kbtable``）。"""
    return bool(re.search(r"""id\s*=\s*['"](?:timetable|kbtable)['"]""", html_text, re.I))


class _KbParser(HTMLParser):
    """解析强智课表：支持 ``#timetable`` / ``#kbtable``，兼容 ``display:none`` 的 kbcontent。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.courses: list[dict[str, str | int | None]] = []
        self._in_table = False
        self._table_depth = 0
        self._row_period: str | None = None
        self._day = 0
        self._in_th = False
        self._th_bits: list[str] = []
        self._kb_depth = 0
        self._kb_fonts: dict[str, str] = {}
        self._kb_texts: list[str] = []
        self._font_title: str | None = None
        self._font_bits: list[str] = []
        self._skip_kbcontent1 = False
        self._in_period_td = False
        self._period_td_bits: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        if tag == "table":
            tid = d.get("id") or ""
            # 只认明确的课表 id；避免误吃页面其它表
            if tid in {"timetable", "kbtable"}:
                self._in_table = True
                self._table_depth = 1
                return
            if self._in_table:
                self._table_depth += 1
            return
        if not self._in_table or self._table_depth != 1:
            return
        if tag == "tr":
            self._row_period = None
            self._day = 0
        elif tag == "th":
            self._in_th = True
            self._th_bits = []
        elif tag == "td":
            # 节次列偶发为 <td>：先缓冲首格，结束时再判定
            if self._row_period is None and self._day == 0 and not self._in_period_td:
                self._in_period_td = True
                self._period_td_bits = []
            else:
                self._day += 1
        elif tag == "br":
            if self._in_th:
                self._th_bits.append(" ")
            elif self._in_period_td:
                self._period_td_bits.append(" ")
            elif self._kb_depth:
                self._kb_texts.append("\n")
        elif tag == "div":
            classes = (d.get("class") or "").split()
            if self._kb_depth:
                self._kb_depth += 1
            elif "kbcontent1" in classes:
                self._skip_kbcontent1 = True
                self._kb_depth = 1
            elif "kbcontent" in classes:
                self._kb_depth = 1
                self._kb_fonts = {}
                self._kb_texts = []
                self._skip_kbcontent1 = False
        elif tag == "font" and self._kb_depth and not self._skip_kbcontent1:
            self._font_title = d.get("title")
            self._font_bits = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table:
            self._table_depth -= 1
            if self._table_depth <= 0:
                self._in_table = False
            return
        if not self._in_table or self._table_depth != 1:
            return
        if tag == "th" and self._in_th:
            label = parse_period_label("".join(self._th_bits))
            if label:
                self._row_period = label
            self._in_th = False
        elif tag == "td" and self._in_period_td:
            label = parse_period_label("".join(self._period_td_bits))
            if label:
                self._row_period = label
            else:
                # 首格不是节次，按星期一计
                self._day = 1
            self._in_period_td = False
            self._period_td_bits = []
        elif tag == "font" and self._font_title is not None:
            self._kb_fonts[self._font_title] = "".join(self._font_bits).strip()
            self._font_title = None
            self._font_bits = []
        elif tag == "div" and self._kb_depth:
            self._kb_depth -= 1
            if self._kb_depth == 0 and not self._skip_kbcontent1:
                self._flush_kb()
            if self._kb_depth == 0:
                self._skip_kbcontent1 = False

    def handle_data(self, data: str) -> None:
        if self._in_th:
            self._th_bits.append(data)
        elif self._in_period_td:
            self._period_td_bits.append(data)
        elif self._font_title is not None:
            self._font_bits.append(data)
        elif self._kb_depth and not self._skip_kbcontent1:
            self._kb_texts.append(data)

    def _flush_kb(self) -> None:
        if not self._row_period or not (1 <= self._day <= 7):
            return
        raw = "".join(self._kb_texts)
        chunks = _SEP.split(raw) if _SEP.search(raw) else [raw]
        # 也按「有字体元数据的整块」处理：多数学校一块一课
        if len(chunks) == 1 and self._kb_fonts:
            chunks = [raw]
        for chunk in chunks:
            name = ""
            for line in chunk.splitlines():
                text = line.replace("\xa0", " ").strip()
                text = re.sub(r"\s*[PO]\s*$", "", text).strip()
                if text and text not in {"&nbsp;"}:
                    name = text
                    break
            if not name and self._kb_fonts:
                # 有的页面课程名在无 title 的 font 里，已并入 texts；若仍空则跳过
                continue
            if not name:
                continue
            teacher = next(
                (self._kb_fonts[t] for t in _TEACHER_TITLES if self._kb_fonts.get(t)), None
            )
            place = next((self._kb_fonts[t] for t in _PLACE_TITLES if self._kb_fonts.get(t)), None)
            building = self._kb_fonts.get("教学楼")
            if building and place and building not in place:
                place = f"{building} {place}"
            elif building and not place:
                place = building
            weeks = next((self._kb_fonts[t] for t in _WEEK_TITLES if self._kb_fonts.get(t)), None)
            if weeks:
                weeks = re.sub(r"\[.*?\]", "", weeks).strip() or None
            self.courses.append(
                {
                    "name": name,
                    "teacher": teacher or None,
                    "place": place or None,
                    "weeks": weeks,
                    "sessions": self._row_period,
                    "weekday": self._day,
                }
            )


def parse_kbcontent_blocks(html_text: str) -> list[dict[str, str | int | None]]:
    """从强智课表 HTML 抽出课程块（``#timetable`` 或 ``#kbtable``）。"""
    parser = _KbParser()
    parser.feed(html_text)
    return parser.courses


_JSON_LOGIN_FLAG = re.compile(r'"flag1"\s*:\s*"?2"?')


def looks_like_login(html_text: str) -> bool:
    """识别登录页，以及强智会话过期时返回的 JSON（``{"flag1":2,...请先登录系统}``）。"""
    head = html_text.lstrip()[:4000]
    if head.startswith("{") and ("请先登录" in head or _JSON_LOGIN_FLAG.search(head)):
        return True
    markers = (
        'name="loginForm"',
        "LoginToXk",
        "Logon.do?method=logon",
        "verifycode.servlet",
        ">用户登录<",
        ">登录</title>",
        'name="RANDOMCODE"',
        "请先登录系统",
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


def select_options(html_text: str, select_name: str) -> list[tuple[str, str, bool]]:
    """返回某个 ``<select>`` 的全部选项 ``(value, label, selected)``，找不到则为空列表。"""
    pattern = re.compile(
        rf'<select[^>]*name=["\']{re.escape(select_name)}["\'][^>]*>(.*?)</select>',
        re.I | re.S,
    )
    match = pattern.search(html_text)
    if not match:
        return []
    options = []
    for opt in re.finditer(r"<option([^>]*)>(.*?)(?=<option|$)", match.group(1), re.I | re.S):
        attrs, label = opt.group(1), opt.group(2)
        value = re.search(r'value=["\']([^"\']*)["\']', attrs, re.I)
        if not value:
            continue
        text = _strip_tags(re.sub(r"</option>.*", "", label, flags=re.I | re.S)).strip()
        options.append((value.group(1), text, bool(re.search(r"\bselected\b", attrs, re.I))))
    return options

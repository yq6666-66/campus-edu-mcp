"""成绩是否通过的共享判断逻辑。"""

from __future__ import annotations

_PASS_WORDS = ("优秀", "良好", "中等", "及格", "合格", "通过", "优", "良", "中", "A", "B", "C", "D")
_FAIL_WORDS = ("不及格", "不合格", "不通过", "未通过", "缺考", "F", "E")


def judge_passed(score: str | None, percent: str | None = None) -> bool | None:
    """根据成绩判断是否通过；无法判断时返回 None。"""
    for candidate in (percent, score):
        if candidate is None:
            continue
        try:
            return float(candidate.strip()) >= 60
        except ValueError:
            pass
    if score is None:
        return None
    if any(score.startswith(w) for w in _FAIL_WORDS):
        return False
    if any(score.startswith(w) for w in _PASS_WORDS):
        return True
    return None

"""核心模块覆盖率门槛（整体门槛 70% 由 pytest --cov-fail-under 保证）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CORE = (
    "guard.py",
    "redact.py",
    "cookies.py",
    "service.py",
    "adapters/qiangzhi.py",
    "adapters/zfsoft_v9.py",
    "htmlutil.py",
)
THRESHOLD = 80.0


def main(path: str = "coverage.json") -> int:
    data = json.loads(Path(path).read_text("utf-8"))
    failed = False
    for name, info in data["files"].items():
        norm = name.replace("\\", "/")
        if norm.endswith(CORE):
            pct = float(info["summary"]["percent_covered"])
            mark = "OK " if pct >= THRESHOLD else "LOW"
            print(f"{mark} {pct:5.1f}%  {norm}")
            failed |= pct < THRESHOLD
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))

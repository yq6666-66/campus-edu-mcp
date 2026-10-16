"""Load private banned words without committing them to the repository.

Sources, merged: env CAMPUS_EDU_BANNED_WORDS (comma-separated) and the
gitignored file tests/.banned-words.local (one word per line).
Tests that need the list skip when neither source is present.
"""

from __future__ import annotations

import os
from pathlib import Path

LOCAL_FILE = Path(__file__).parent / ".banned-words.local"


def banned_words() -> tuple[str, ...]:
    words: list[str] = []
    env = os.environ.get("CAMPUS_EDU_BANNED_WORDS", "")
    words += [w.strip() for w in env.split(",")]
    if LOCAL_FILE.is_file():
        words += [w.strip() for w in LOCAL_FILE.read_text("utf-8").splitlines()]
    return tuple(w.lower() for w in words if w and not w.startswith("#"))

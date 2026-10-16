"""公开路径厂商探测：只 GET、不带 Cookie、不跟随到登录后业务页。

路径 / 正文指纹优先于主机名。hostname 含 ``jwglxt`` **不会**给正方加分
（已有真实案例：主机名像正方，实际是树维新 EAMS）。
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import httpx

from .errors import ConfigError

ProbeTransport = httpx.BaseTransport | None


@dataclass(frozen=True)
class Probe:
    path: str
    vendor: str
    weight: int  # 3=high, 2=med, 1=low
    patterns: tuple[str, ...]
    max_bytes: int | None = None  # 若设置，正文须短于此（login-salt）


PROBES: tuple[Probe, ...] = (
    Probe(
        "/jsxsd/",
        "qiangzhi",
        3,
        ("jsxsd", "LoginToXk", "verifycode.servlet", "xk/LoginToXk"),
    ),
    Probe("/jsxsd/xk/LoginToXk", "qiangzhi", 2, ("LoginToXk", "userAccount", "RANDOMCODE")),
    Probe(
        "/jwglxt/xtgl/login_slogin.html",
        "zfsoft_v9",
        3,
        ("login_slogin", "jwglxt", "zfsoft", "N000000"),
    ),
    Probe("/jwglxt/", "zfsoft_v9", 2, ("jwglxt", "xtgl/login", "login_slogin")),
    Probe(
        "/student/login",
        "supwisdom_eams5",
        3,
        ("login-salt", "eams-ui", "CONTEXT_PATH", "supwisdom", "eams5"),
    ),
    Probe(
        "/student/",
        "supwisdom_eams5",
        2,
        ("login-salt", "eams-ui", "CONTEXT_PATH", "supwisdom", "/student/"),
    ),
    Probe("/student/login-salt", "supwisdom_eams5", 3, (), max_bytes=256),
    Probe(
        "/eams5-student/login",
        "supwisdom_eams5",
        3,
        ("login-salt", "eams-ui", "CONTEXT_PATH", "supwisdom", "eams5"),
    ),
    Probe("/eams5-student/login-salt", "supwisdom_eams5", 3, (), max_bytes=256),
    Probe(
        "/eams/login.action",
        "supwisdom_eams",
        3,
        ("eams", "login.action", "supwisdom", "beangle"),
    ),
    Probe("/eams/", "supwisdom_eams", 2, ("eams", "homeExt.action", "beangle")),
    Probe(
        "/jwweb/",
        "kingosoft",
        2,
        ("kingosoft", "jwweb", "SetKingoEncrypt", "cas/logon"),
    ),
    Probe(
        "/loginAction.do",
        "urp",
        2,
        ("loginAction", "j_spring_security", "学分制综合教务", "v_yzm"),
    ),
    Probe(
        "/j_spring_security_check",
        "urp",
        1,
        ("j_username", "j_password", "spring"),
    ),
    Probe(
        "/authserver/login",
        "wisedu",
        2,
        ("pwdDefaultEncryptSalt", "authserver", "wisedu", "encryptAES"),
    ),
)


@dataclass
class ProbeHit:
    path: str
    vendor: str
    weight: int
    status: int | None
    matched: bool
    reason: str


@dataclass
class DetectResult:
    winner: str | None
    confidence: str
    scores: dict[str, int] = field(default_factory=dict)
    hits: list[ProbeHit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner,
            "confidence": self.confidence,
            "scores": self.scores,
            "hits": [
                {
                    "path": h.path,
                    "vendor": h.vendor,
                    "weight": h.weight,
                    "status": h.status,
                    "matched": h.matched,
                    "reason": h.reason,
                }
                for h in self.hits
            ],
            "notes": self.notes,
        }


def _match(probe: Probe, status: int, text: str, ctype: str) -> tuple[bool, str]:
    if status < 200 or status >= 300:
        return False, f"status={status}"
    body = text[:8000]
    low = body.lower()
    if probe.max_bytes is not None:
        if len(text) > probe.max_bytes:
            return False, "body_too_long_for_salt"
        if "<html" in low or "<form" in low:
            return False, "salt_looks_like_html"
        if text.strip():
            return True, "short_non_html"
        return False, "empty_body"
    if not probe.patterns:
        return False, "no_patterns"
    for pat in probe.patterns:
        if pat.lower() in low:
            return True, f"pattern:{pat}"
    if "text/html" in ctype and "<form" in low and 'type="password"' in low.replace("'", '"'):
        # 弱信号：有密码表单但未命中厂商词
        return False, "login_form_without_vendor_marker"
    return False, "no_pattern"


def detect(
    base_url: str,
    *,
    transport: ProbeTransport = None,
    min_interval: float = 2.0,
    timeout: float = 8.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> DetectResult:
    url = httpx.URL(base_url if base_url.endswith("/") else base_url + "/")
    if url.scheme not in {"http", "https"} or not url.host:
        raise ConfigError("base-url 必须是 http(s) 绝对地址")
    notes: list[str] = []
    if re.search(r"(^|\.|-)jwglxt([\.-]|$)", url.host, re.I):
        notes.append("主机名含 jwglxt，但主机名不等于厂商；以路径/正文指纹为准，不因此给正方加分")
    scores: dict[str, int] = {}
    hits: list[ProbeHit] = []
    last = float("-inf")
    with httpx.Client(
        transport=transport,
        follow_redirects=False,
        timeout=timeout,
        headers={"User-Agent": "campus-edu-mcp-detect (read-only public probe)"},
    ) as client:
        for probe in PROBES:
            wait = last + min_interval - clock()
            if wait > 0:
                sleep(wait)
            target = urljoin(str(url), probe.path.lstrip("/"))
            # 允许相对路径挂在 base 上：/student/login 相对 host 根
            if probe.path.startswith("/"):
                target = (
                    f"{url.scheme}://{url.host}" + (f":{url.port}" if url.port else "") + probe.path
                )
            status: int | None = None
            text = ""
            ctype = ""
            try:
                response = client.get(target)
                # 同主机最多跟 2 次重定向（仍不计业务 Cookie）
                hops = 0
                while response.is_redirect and hops < 2:
                    loc = response.headers.get("location", "")
                    next_url = response.url.join(loc)
                    if (next_url.host, next_url.port) != (url.host, url.port):
                        break
                    wait = last + min_interval - clock()
                    if wait > 0:
                        sleep(wait)
                    response = client.get(next_url)
                    hops += 1
                status = response.status_code
                ctype = response.headers.get("content-type", "")
                text = response.text
            except httpx.HTTPError as exc:
                hits.append(
                    ProbeHit(
                        probe.path, probe.vendor, probe.weight, None, False, type(exc).__name__
                    )
                )
                last = clock()
                continue
            matched, reason = _match(probe, status, text, ctype)
            hits.append(ProbeHit(probe.path, probe.vendor, probe.weight, status, matched, reason))
            if matched:
                scores[probe.vendor] = scores.get(probe.vendor, 0) + probe.weight
            last = clock()

    # 纠偏：正方登录页不存在而树维新 EAMS 有命中 → 强制树维
    zfsoft_login = any(h.path == "/jwglxt/xtgl/login_slogin.html" and h.matched for h in hits)
    zfsoft_root_ok = any(h.path == "/jwglxt/" and h.matched for h in hits)
    eams5_score = scores.get("supwisdom_eams5", 0)
    if eams5_score > 0 and not zfsoft_login and not zfsoft_root_ok:
        scores["supwisdom_eams5"] = max(eams5_score, 6)
        notes.append("正方入口未命中而树维新 EAMS 公开路径命中，winner 定为 supwisdom_eams5")

    if not scores:
        return DetectResult(None, "unknown", {}, hits, notes)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    winner, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    # 双方 P0（weight 3）冲突 → unknown
    p0_vendors = {
        h.vendor
        for h in hits
        if h.matched
        and h.weight >= 3
        and h.vendor in {winner, ranked[1][0] if len(ranked) > 1 else ""}
    }
    if len(ranked) > 1 and ranked[1][1] >= 3 and top - second < 2 and len(p0_vendors) >= 2:
        notes.append("多个厂商出现强证据且分差过小，标为 unknown")
        return DetectResult(None, "unknown", scores, hits, notes)
    if top >= 6 and top - second >= 3:
        conf = "high"
    elif top >= 4 and top - second >= 2:
        conf = "medium"
    elif top >= 2:
        conf = "low"
    else:
        return DetectResult(None, "unknown", scores, hits, notes)
    return DetectResult(winner, conf, scores, hits, notes)


def format_human(result: DetectResult) -> str:
    lines = [
        f"winner: {result.winner or 'unknown'}",
        f"confidence: {result.confidence}",
        "scores: "
        + (
            ", ".join(f"{k}={v}" for k, v in sorted(result.scores.items(), key=lambda x: -x[1]))
            or "(none)"
        ),
    ]
    for note in result.notes:
        lines.append(f"note: {note}")
    matched = [h for h in result.hits if h.matched]
    if matched:
        lines.append("hits:")
        for h in matched:
            lines.append(f"  - {h.path} → {h.vendor} (+{h.weight}) [{h.reason}]")
    return "\n".join(lines)

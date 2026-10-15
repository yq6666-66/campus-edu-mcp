"""只读守卫：在 HTTP 客户端最底层（transport）拦截所有出站请求。

设计要点（见 docs/compliance.md）：

* 白名单按「方法 + 路径 + 参数」逐条声明，查询串与 form 表单参数一起校验；
  固定参数（如 ``doType=query``、``gnmkdm``）必须精确等于枚举值，
  自由参数（如学年 ``xnm``）必须匹配正则，未声明的参数一律拒绝。
* 客户端关闭自动重定向；3xx 由 :class:`GuardedClient` 手动处理，
  每一跳都重新经过 transport 校验，跳到登录页视为会话失效。
* 适配器只能拿到 :class:`GuardedClient`，不能自己创建 HTTP 客户端
  （由 ``scripts/check_adapters.py`` 静态检查保证）。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from urllib.parse import parse_qsl

import httpx

from .errors import GuardViolation, SessionExpired, UpstreamError
from .redact import redact_url

logger = logging.getLogger(__name__)

FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
MAX_REDIRECTS = 3


@dataclass(frozen=True)
class Rule:
    """一条白名单规则。``path`` 相对于学校 base_url 的路径前缀。"""

    method: str
    path: str
    fixed: Mapping[str, frozenset[str]] = field(default_factory=dict)
    free: Mapping[str, str] = field(default_factory=dict)
    description: str = ""

    def allowed_keys(self) -> frozenset[str]:
        return frozenset(self.fixed) | frozenset(self.free)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    rule: Rule | None = None


class Whitelist:
    """某个学校实例的白名单：绑定 scheme、host、base path。"""

    def __init__(self, base_url: str, rules: Iterable[Rule]) -> None:
        base = httpx.URL(base_url)
        if base.scheme not in {"http", "https"} or not base.host:
            raise ValueError("base_url 必须是 http(s) 绝对地址")
        self.scheme = base.scheme
        self.host = base.host
        self.port = base.port
        self.base_path = base.path.rstrip("/") + "/"
        self.rules = tuple(rules)
        self._compiled = {id(r): {k: re.compile(v) for k, v in r.free.items()} for r in self.rules}

    def check(self, request: httpx.Request) -> Decision:
        url = request.url
        if (url.scheme, url.host, url.port) != (self.scheme, self.host, self.port):
            return Decision(False, "host 不在白名单")
        path = url.path
        if not path.startswith(self.base_path):
            return Decision(False, "路径不在 base_url 之下")
        raw_path = url.raw_path.split(b"?", 1)[0]
        if b"%" in raw_path or b";" in raw_path or "\x00" in path:
            return Decision(False, "路径含编码字符或矩阵参数")
        rel = path[len(self.base_path) :]
        try:
            params = _collect_params(request)
        except GuardViolation as exc:
            return Decision(False, str(exc))
        candidates = [r for r in self.rules if r.method == request.method and r.path == rel]
        if not candidates:
            return Decision(False, f"未登记的接口 {request.method} {rel}")
        reasons: list[str] = []
        for rule in candidates:
            reason = self._match_params(rule, params)
            if reason is None:
                return Decision(True, "ok", rule)
            reasons.append(reason)
        return Decision(False, "; ".join(reasons))

    def _match_params(self, rule: Rule, params: list[tuple[str, str]]) -> str | None:
        seen: dict[str, str] = {}
        allowed = rule.allowed_keys()
        for key, value in params:
            if key not in allowed:
                return f"未登记的参数 {key}"
            if key in seen and seen[key] != value:
                return f"参数 {key} 重复且取值不同"
            seen[key] = value
            if key in rule.fixed and value not in rule.fixed[key]:
                return f"参数 {key} 取值不在枚举内"
            pattern = self._compiled[id(rule)].get(key)
            if pattern is not None and not pattern.fullmatch(value):
                return f"参数 {key} 取值格式不符"
        missing = [k for k in rule.fixed if k not in seen]
        if missing:
            return f"缺少固定参数 {','.join(sorted(missing))}"
        return None


def _collect_params(request: httpx.Request) -> list[tuple[str, str]]:
    params = list(request.url.params.multi_items())
    body = request.content
    if body:
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype != FORM_CONTENT_TYPE:
            raise GuardViolation(f"不允许的请求体类型 {ctype or '未知'}")
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GuardViolation("请求体不是 UTF-8 表单") from exc
        params.extend(parse_qsl(text, keep_blank_values=True, strict_parsing=False))
    return params


class GuardTransport(httpx.BaseTransport):
    """包装真实 transport，每个请求发出前都做白名单校验。"""

    def __init__(self, whitelist: Whitelist, inner: httpx.BaseTransport | None = None) -> None:
        self.whitelist = whitelist
        self.inner = inner if inner is not None else httpx.HTTPTransport(retries=0)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        decision = self.whitelist.check(request)
        if not decision.allowed:
            logger.warning(
                "guard 拦截 %s %s: %s",
                request.method,
                redact_url(str(request.url)),
                decision.reason,
            )
            raise GuardViolation(f"只读守卫拦截了请求：{decision.reason}")
        logger.debug("guard 放行 %s %s", request.method, redact_url(str(request.url)))
        return self.inner.handle_request(request)

    def close(self) -> None:
        self.inner.close()


class GuardedClient:
    """适配器唯一可用的 HTTP 入口。

    不继承 httpx.Client，避免暴露 ``stream``/``send`` 等可绕开重定向处理的接口。
    """

    def __init__(
        self,
        base_url: str,
        rules: Iterable[Rule],
        cookies: Mapping[str, str] | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        min_interval: float = 2.0,
        timeout: float = 15.0,
        login_markers: Iterable[str] = ("login_slogin", "/cas/login", "/login"),
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.whitelist = Whitelist(self.base_url, rules)
        self._client = httpx.Client(
            base_url=self.base_url,
            transport=GuardTransport(self.whitelist, transport),
            follow_redirects=False,
            cookies=dict(cookies or {}),
            timeout=timeout,
            headers={
                "User-Agent": "campus-edu-mcp (read-only)",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        self.min_interval = min_interval
        self.login_markers = tuple(login_markers)
        self._clock = clock
        self._sleep = sleep
        self._last = float("-inf")
        self._lock = threading.Lock()

    def post_form(
        self, path: str, params: Mapping[str, str], data: Mapping[str, str]
    ) -> httpx.Response:
        return self._request("POST", path, params=params, data=data)

    def get(self, path: str, params: Mapping[str, str] | None = None) -> httpx.Response:
        return self._request("GET", path, params=params or {}, data=None)

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last + self.min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str],
        data: Mapping[str, str] | None,
    ) -> httpx.Response:
        if "://" in path or path.startswith("//"):
            raise GuardViolation("适配器只能使用相对路径")
        self._throttle()
        request = self._client.build_request(method, path.lstrip("/"), params=params, data=data)
        for _hop in range(MAX_REDIRECTS + 1):
            response = self._client.send(request)
            if not response.is_redirect:
                return response
            if response.status_code in (307, 308):
                # 307/308 要求保持方法和请求体，只读客户端不跟随
                raise UpstreamError(f"教务系统返回了 {response.status_code} 重定向，已拒绝跟随")
            location = response.headers.get("location", "")
            target = request.url.join(location)
            if any(marker in target.path for marker in self.login_markers):
                raise SessionExpired("会话已失效（被重定向到登录页），请重新导入会话")
            # 重定向一律降级为不带请求体的 GET，并重新走 guard
            self._throttle()
            request = self._client.build_request("GET", target)
        raise UpstreamError("重定向次数过多")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GuardedClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

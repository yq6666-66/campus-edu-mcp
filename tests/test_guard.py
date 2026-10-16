"""guard 的四类核心用例：查询放行、参数不符被拒、未知请求被拒、重定向逐跳复查。"""

from __future__ import annotations

import httpx
import pytest

from campus_edu_mcp.adapters.zfsoft_v9 import RULES
from campus_edu_mcp.errors import GuardViolation, SessionExpired, UpstreamError
from campus_edu_mcp.guard import GuardedClient, GuardTransport, Rule, Whitelist

from .conftest import BASE_URL

GRADES = ("cjcx/cjcx_cxXsgrcj.html", {"doType": "query", "gnmkdm": "N305005"})


class Recorder:
    def __init__(self, responder: object = None) -> None:
        self.requests: list[httpx.Request] = []
        self.responder = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if callable(self.responder):
            result = self.responder(request)
            assert isinstance(result, httpx.Response)
            return result
        return httpx.Response(200, json={"items": []})


def make_client(recorder: Recorder, rules: tuple[Rule, ...] = tuple(RULES)) -> GuardedClient:
    return GuardedClient(
        BASE_URL,
        rules,
        {"JSESSIONID": "FAKE"},
        transport=httpx.MockTransport(recorder),
        min_interval=0,
    )


# ---- 1. 查询类 POST 放行 ----
@pytest.mark.parametrize(
    ("path", "params", "data"),
    [
        ("kbcx/xskbcx_cxXsKb.html", {"gnmkdm": "N2151"}, {"xnm": "2025", "xqm": "3", "kzlx": "ck"}),
        (
            "kwgl/kscx_cxXsksxxIndex.html",
            {"doType": "query", "gnmkdm": "N358105"},
            {"xnm": "2025", "xqm": "12", "queryModel.showCount": "200"},
        ),
        (*GRADES, {"xnm": "", "xqm": "", "queryModel.showCount": "500"}),
    ],
)
def test_query_post_allowed(path: str, params: dict[str, str], data: dict[str, str]) -> None:
    rec = Recorder()
    with make_client(rec) as client:
        assert client.post_form(path, params, data).status_code == 200
    assert len(rec.requests) == 1
    assert rec.requests[0].method == "POST"


# ---- 2. 路径对、参数不符被拒 ----
@pytest.mark.parametrize(
    ("params", "data"),
    [
        ({"doType": "delete", "gnmkdm": "N305005"}, {}),  # 固定参数取值不在枚举
        ({"doType": "query", "gnmkdm": "N999999"}, {}),  # 功能模块代码不对
        ({"gnmkdm": "N305005"}, {}),  # 缺少固定参数
        ({"doType": "query", "gnmkdm": "N305005"}, {"xnm": "2025;drop"}),  # 自由参数格式不符
        ({"doType": "query", "gnmkdm": "N305005"}, {"kch_id": "K1"}),  # 未登记参数
        ({"doType": "query", "gnmkdm": "N305005"}, {"doType": "save"}),  # body 里覆盖固定参数
    ],
)
def test_wrong_params_rejected(params: dict[str, str], data: dict[str, str]) -> None:
    rec = Recorder()
    with make_client(rec) as client, pytest.raises(GuardViolation):
        client.post_form(GRADES[0], params, data)
    assert rec.requests == []


def test_duplicate_param_with_different_value_rejected() -> None:
    wl = Whitelist(BASE_URL, RULES)
    req = httpx.Request(
        "POST",
        BASE_URL + "cjcx/cjcx_cxXsgrcj.html?doType=query&gnmkdm=N305005&doType=save",
    )
    decision = wl.check(req)
    assert not decision.allowed
    assert "重复" in decision.reason


# ---- 3. 未知请求被拒 ----
@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("POST", BASE_URL + "xsxk/zzxkyzb_xkBcZyZzxkYzb.html?gnmkdm=N253512"),  # 选课
        ("POST", BASE_URL + "xspjgl/xspj_bcXspj.html?gnmkdm=N401605"),  # 评教保存
        ("GET", BASE_URL + "cjcx/cjcx_cxXsgrcj.html?doType=query&gnmkdm=N305005"),  # 方法不对
        ("POST", "https://evil.example.com/jwglxt/cjcx/cjcx_cxXsgrcj.html"),  # 其他主机
        ("POST", "http://jw.example.edu.cn/jwglxt/cjcx/cjcx_cxXsgrcj.html"),  # 降级 http
        ("POST", "https://jw.example.edu.cn:8443/jwglxt/cjcx/cjcx_cxXsgrcj.html"),  # 其他端口
        ("POST", "https://jw.example.edu.cn/other/cjcx/cjcx_cxXsgrcj.html"),  # base 之外
        ("POST", BASE_URL + "cjcx/cjcx_cxXsgrcj.html;jsessionid=x?doType=query&gnmkdm=N305005"),
    ],
)
def test_unknown_requests_rejected(method: str, url: str) -> None:
    rec = Recorder()
    transport = GuardTransport(Whitelist(BASE_URL, RULES), httpx.MockTransport(rec))
    with pytest.raises(GuardViolation):
        transport.handle_request(httpx.Request(method, url))
    assert rec.requests == []


def test_absolute_url_from_adapter_rejected() -> None:
    rec = Recorder()
    with make_client(rec) as client, pytest.raises(GuardViolation):
        client.get("https://evil.example.com/x")
    with make_client(rec) as client, pytest.raises(GuardViolation):
        client.get("//evil.example.com/x")
    assert rec.requests == []


def test_non_form_body_rejected() -> None:
    wl = Whitelist(BASE_URL, RULES)
    req = httpx.Request(
        "POST",
        BASE_URL + "cjcx/cjcx_cxXsgrcj.html?doType=query&gnmkdm=N305005",
        json={"xnm": "2025"},
    )
    assert not wl.check(req).allowed
    bad = httpx.Request(
        "POST",
        BASE_URL + "cjcx/cjcx_cxXsgrcj.html?doType=query&gnmkdm=N305005",
        content=b"\xff\xfe",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert "UTF-8" in wl.check(bad).reason


# ---- 4. 重定向：不自动跟随，每跳复查 ----
def test_redirect_to_write_endpoint_blocked() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "../xsxk/zzxkyzb_xkBcZyZzxkYzb.html"})

    rec = Recorder(responder)
    with make_client(rec) as client, pytest.raises(GuardViolation):
        client.post_form(GRADES[0], GRADES[1], {})
    assert len(rec.requests) == 1  # 写接口从未被请求


def test_redirect_to_other_host_blocked() -> None:
    rec = Recorder(lambda r: httpx.Response(301, headers={"location": "https://evil.example.com/"}))
    with make_client(rec) as client, pytest.raises(GuardViolation):
        client.post_form(GRADES[0], GRADES[1], {})
    assert len(rec.requests) == 1


def test_redirect_to_login_means_session_expired() -> None:
    rec = Recorder(
        lambda r: httpx.Response(302, headers={"location": "/jwglxt/xtgl/login_slogin.html"})
    )
    with make_client(rec) as client, pytest.raises(SessionExpired):
        client.post_form(GRADES[0], GRADES[1], {})
    assert len(rec.requests) == 1


def test_whitelisted_redirect_followed_as_get() -> None:
    rules = (*RULES, Rule("GET", "cjcx/ok.html"))
    calls: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(request.method + " " + request.url.path)
        if request.url.path.endswith("ok.html"):
            return httpx.Response(200, text="done")
        return httpx.Response(302, headers={"location": "ok.html"})

    with make_client(Recorder(responder), rules) as client:
        assert client.post_form(GRADES[0], GRADES[1], {}).text == "done"
    assert calls == ["POST /jwglxt/cjcx/cjcx_cxXsgrcj.html", "GET /jwglxt/cjcx/ok.html"]


def test_redirect_loop_stops() -> None:
    rules = (*RULES, Rule("GET", "loop.html"))
    rec = Recorder(lambda r: httpx.Response(302, headers={"location": "/jwglxt/loop.html"}))
    with make_client(rec, rules) as client, pytest.raises(UpstreamError):
        client.get("loop.html")


# ---- 其他 ----
def test_throttle_waits_between_requests() -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    client = GuardedClient(
        BASE_URL,
        RULES,
        transport=httpx.MockTransport(Recorder()),
        min_interval=2.0,
        clock=lambda: now[0],
        sleep=sleep,
    )
    client.post_form(GRADES[0], GRADES[1], {})
    client.post_form(GRADES[0], GRADES[1], {})
    client.close()
    assert slept == [2.0]


def test_invalid_base_url() -> None:
    with pytest.raises(ValueError):
        Whitelist("ftp://x/", RULES)


def test_every_zfsoft_rule_is_post_with_fixed_gnmkdm() -> None:
    for rule in RULES:
        assert rule.method == "POST"
        assert "gnmkdm" in rule.fixed
        assert not rule.allowed_keys() & {"kch_id", "jxb_id", "do_jxb_id"}  # 选课相关参数


@pytest.mark.parametrize(
    "suffix",
    [
        "xsxk/%2e%2e/cjcx/cjcx_cxXsgrcj.html",
        "cjcx%2Fcjcx_cxXsgrcj.html",
        "cjcx/CJCX_cxXsgrcj.html",
        "cjcx//cjcx_cxXsgrcj.html",
    ],
)
def test_path_tricks_rejected(suffix: str) -> None:
    wl = Whitelist(BASE_URL, RULES)
    req = httpx.Request("POST", BASE_URL + suffix + "?doType=query&gnmkdm=N305005")
    assert not wl.check(req).allowed


def test_uppercase_param_name_rejected() -> None:
    wl = Whitelist(BASE_URL, RULES)
    url = BASE_URL + "cjcx/cjcx_cxXsgrcj.html?doType=query&gnmkdm=N305005&DOTYPE=save"
    assert not wl.check(httpx.Request("POST", url)).allowed


@pytest.mark.parametrize("status", [307, 308])
def test_method_preserving_redirect_refused(status: int) -> None:
    rec = Recorder(lambda r: httpx.Response(status, headers={"location": "/jwglxt/x.html"}))
    with make_client(rec) as client, pytest.raises(UpstreamError):
        client.post_form(GRADES[0], GRADES[1], {})
    assert len(rec.requests) == 1


def test_encoded_login_redirect_detected() -> None:
    rec = Recorder(lambda r: httpx.Response(302, headers={"location": "/%6cogin"}))
    with make_client(rec) as client, pytest.raises(SessionExpired):
        client.post_form(GRADES[0], GRADES[1], {})


def test_encoded_dotdot_rejected() -> None:
    wl = Whitelist(BASE_URL, RULES)
    req = httpx.Request("POST", "https://jw.example.edu.cn/jwglxt/%2e%2e/cjcx/cjcx_cxXsgrcj.html")
    decision = wl.check(req)
    assert not decision.allowed
    assert "编码" in decision.reason


def test_normalized_parent_path_stays_under_base() -> None:
    wl = Whitelist(BASE_URL, RULES)
    req = httpx.Request("POST", "https://jw.example.edu.cn/jwglxt/a/../cjcx/cjcx_cxXsgrcj.html")
    # httpx 规范化后路径仍在 base 下；不得因异常失败
    decision = wl.check(req)
    assert decision.allowed or "白名单" in decision.reason or "参数" in decision.reason


def test_pacer_shared_across_clients_for_same_host() -> None:
    from campus_edu_mcp.guard import shared_pacer

    a = GuardedClient("https://pace.example.edu.cn/jwglxt/", RULES, {})
    b = GuardedClient("https://pace.example.edu.cn/other/", RULES, {})
    c = GuardedClient("https://other.example.edu.cn/jwglxt/", RULES, {})
    assert a._pacer is b._pacer is shared_pacer("https://pace.example.edu.cn/")
    assert a._pacer is not c._pacer
    custom = GuardedClient("https://pace.example.edu.cn/jwglxt/", RULES, {}, clock=lambda: 0.0)
    assert custom._pacer is not a._pacer

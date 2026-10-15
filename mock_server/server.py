"""用法：``uv run python -m mock_server --port 8765``

* 基础路径 ``/jwglxt/``，有效 Cookie 为 ``JSESSIONID=FAKE-MOCK-SESSION``；
* 三个查询接口返回 tests/fixtures/zfsoft_v9 下的虚构数据；
* Cookie 无效时，按正方的常见行为 302 跳转到 ``xtgl/login_slogin.html``；
* 另有一个模拟“选课”写接口，只用来证明 guard 会拦截它——它记录被调用次数，
  可通过 ``GET /__hits`` 查看（正常情况下永远是 0）。
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "zfsoft_v9"
BASE = "/jwglxt/"
VALID_COOKIE = "FAKE-MOCK-SESSION"
WRITE_PATH = BASE + "xsxk/zzxkyzb_xkBcZyZzxkYzb.html"

ROUTES = {
    BASE + "kbcx/xskbcx_cxXsKb.html": ("timetable.json", {"gnmkdm": "N2151"}),
    BASE + "kwgl/kscx_cxXsksxxIndex.html": ("exams.json", {"doType": "query", "gnmkdm": "N358105"}),
    BASE + "cjcx/cjcx_cxXsgrcj.html": ("grades.json", {"doType": "query", "gnmkdm": "N305005"}),
}


class State:
    def __init__(self) -> None:
        self.write_hits = 0
        self.lock = threading.Lock()


def make_handler(state: State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "MockZfsoft/0.1"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def _send(
            self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _cookie_ok(self) -> bool:
            raw = self.headers.get("Cookie", "")
            pairs = dict(p.strip().split("=", 1) for p in raw.split(";") if "=" in p)
            return pairs.get("JSESSIONID") == VALID_COOKIE

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/__hits":
                self._send(
                    200, json.dumps({"write_hits": state.write_hits}).encode(), "application/json"
                )
            elif path == BASE + "xtgl/login_slogin.html":
                self._send(
                    200, (FIXTURES / "login_page.html").read_bytes(), "text/html; charset=utf-8"
                )
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            length = int(self.headers.get("Content-Length", "0") or 0)
            self.rfile.read(length)
            if parts.path == WRITE_PATH:
                with state.lock:
                    state.write_hits += 1
                self._send(200, b'{"flag":"1","msg":"mock write"}', "application/json")
                return
            route = ROUTES.get(parts.path)
            if route is None:
                self._send(404, b"not found", "text/plain")
                return
            if not self._cookie_ok():
                self._send(302, b"", "text/html", {"Location": BASE + "xtgl/login_slogin.html"})
                return
            filename, required = route
            query = dict(parse_qsl(parts.query))
            if any(query.get(k) != v for k, v in required.items()):
                self._send(400, b"bad params", "text/plain")
                return
            self._send(200, (FIXTURES / filename).read_bytes(), "application/json;charset=UTF-8")

    return Handler


def serve(port: int = 8765, host: str = "127.0.0.1") -> tuple[ThreadingHTTPServer, State]:
    state = State()
    httpd = ThreadingHTTPServer((host, port), make_handler(state))
    return httpd, state


def main() -> None:
    parser = argparse.ArgumentParser(description="模拟正方 V9 教务服务器（虚构数据）")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    httpd, _ = serve(args.port, args.host)
    print(
        f"mock 教务: http://{args.host}:{httpd.server_address[1]}{BASE}  "
        f"Cookie: JSESSIONID={VALID_COOKIE}"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

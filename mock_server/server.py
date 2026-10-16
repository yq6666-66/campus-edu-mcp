"""用法：``uv run python -m mock_server --port 8765 [--vendor qiangzhi|zfsoft_v9]``

默认模拟强智 jsxsd。有效 Cookie：``JSESSIONID=FAKE-MOCK-SESSION``。
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parent.parent
QZ = ROOT / "tests" / "fixtures" / "qiangzhi"
ZF = ROOT / "tests" / "fixtures" / "zfsoft_v9"
VALID_COOKIE = "FAKE-MOCK-SESSION"

QZ_BASE = "/jsxsd/"
ZF_BASE = "/jwglxt/"
WRITE_QZ = QZ_BASE + "xsxk/xk_apply.do"
WRITE_ZF = ZF_BASE + "xsxk/zzxkyzb_xkBcZyZzxkYzb.html"

QZ_ROUTES: dict[str, tuple[str, dict[str, str]]] = {
    QZ_BASE + "xskb/xskb_list.do": ("timetable.html", {}),
    QZ_BASE + "kscj/cjcx_list": ("grades.html", {}),
    QZ_BASE + "kscj/cjcx_list.do": ("grades.html", {}),
    QZ_BASE + "xsks/xsksap_list": ("exams.html", {}),
    QZ_BASE + "xsks/xsksap_list.do": ("exams.html", {}),
}
ZF_ROUTES: dict[str, tuple[str, dict[str, str]]] = {
    ZF_BASE + "kbcx/xskbcx_cxXsKb.html": ("timetable.json", {"gnmkdm": "N2151"}),
    ZF_BASE + "kwgl/kscx_cxXsksxxIndex.html": (
        "exams.json",
        {"doType": "query", "gnmkdm": "N358105"},
    ),
    ZF_BASE + "cjcx/cjcx_cxXsgrcj.html": ("grades.json", {"doType": "query", "gnmkdm": "N305005"}),
}


class State:
    def __init__(self) -> None:
        self.write_hits = 0
        self.lock = threading.Lock()


def make_handler(state: State, vendor: str) -> type[BaseHTTPRequestHandler]:
    base = QZ_BASE if vendor == "qiangzhi" else ZF_BASE
    fixtures = QZ if vendor == "qiangzhi" else ZF
    routes = QZ_ROUTES if vendor == "qiangzhi" else ZF_ROUTES
    write_path = WRITE_QZ if vendor == "qiangzhi" else WRITE_ZF
    login_path = base + ("xk/LoginToXk" if vendor == "qiangzhi" else "xtgl/login_slogin.html")
    login_file = "login_page.html"

    class Handler(BaseHTTPRequestHandler):
        server_version = "MockEdu/0.1"

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
                return
            if path in {login_path, base + "Logon.do"}:
                self._send(200, (fixtures / login_file).read_bytes(), "text/html; charset=utf-8")
                return
            self._handle(path, urlsplit(self.path).query, is_get=True)

        def do_POST(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length)
            if parts.path == write_path:
                with state.lock:
                    state.write_hits += 1
                self._send(200, b'{"flag":"1","msg":"mock write"}', "application/json")
                return
            self._handle(parts.path, parts.query, is_get=False, body=body)

        def _handle(self, path: str, query: str, *, is_get: bool, body: bytes = b"") -> None:
            route = routes.get(path)
            if route is None:
                self._send(404, b"not found", "text/plain")
                return
            if not self._cookie_ok():
                self._send(302, b"", "text/html", {"Location": login_path})
                return
            filename, required = route
            params = dict(parse_qsl(query))
            if body:
                params.update(dict(parse_qsl(body.decode("utf-8", errors="replace"))))
            if any(params.get(k) != v for k, v in required.items()):
                self._send(400, b"bad params", "text/plain")
                return
            ctype = (
                "application/json;charset=UTF-8"
                if filename.endswith(".json")
                else "text/html; charset=utf-8"
            )
            # GET/POST 都允许
            _ = is_get
            self._send(200, (fixtures / filename).read_bytes(), ctype)

    return Handler


def serve(
    port: int = 8765, host: str = "127.0.0.1", vendor: str = "qiangzhi"
) -> tuple[ThreadingHTTPServer, State]:
    state = State()
    httpd = ThreadingHTTPServer((host, port), make_handler(state, vendor))
    return httpd, state


def main() -> None:
    parser = argparse.ArgumentParser(description="模拟教务服务器（虚构数据）")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--vendor", choices=["qiangzhi", "zfsoft_v9"], default="qiangzhi")
    args = parser.parse_args()
    httpd, _ = serve(args.port, args.host, args.vendor)
    base = QZ_BASE if args.vendor == "qiangzhi" else ZF_BASE
    print(
        f"mock ({args.vendor}): http://{args.host}:{httpd.server_address[1]}{base}  "
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

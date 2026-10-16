# campus-edu-mcp

`campus-edu-mcp` is a read-only MCP (Model Context Protocol) server for interacting with campus academic systems. It defaults to the Qiangzhi (强智) `jsxsd` student portal. A Zhengfang V9 adapter is also included but has not been live-tested. Example school config: `schools/example-qiangzhi.yaml` (replace with your campus URL). Verified on one Qiangzhi school (2026-10-16).

The server is built with the official MCP SDK (`mcp` 2.3.0, `MCPServer`, stdio transport only). It exposes course timetables, exam schedules, and grade summaries to MCP clients without exposing sensitive personal identifiers.

## Features

- Read-only MCP tools:
  - `get_timetable(year?, term?)` – fetch class timetable.
  - `get_exams(year?, term?)` – fetch exam schedule.
  - `get_grades(year?, term?, include_scores=false)` – fetch grades. By default returns only course name, credits, course nature, and pass/fail status; set `include_scores=true` to also include scores and grade points.
  - `get_terms()` – list selectable terms (live-verified on one Qiangzhi school).
  - `get_empty_classrooms(week, weekday, periods?, campus?, min_capacity?, year?, term?, limit=50)` – free classrooms for one teaching week/day (read-only room-occupancy grid; never submits a borrowing request; live-verified on one Qiangzhi school).
  - `session_status()` – check whether the imported session is still valid.
- Every tool result includes a `privacy_notice`.
- Privacy-preserving: student ID, name, and ranking are never returned.
- Session import from browser-exported cookies only (request header string, Netscape `cookies.txt`, or JSON array). No account/password login, no captcha solving.
- Encrypted cookie storage using Fernet with a key stored in the system keyring. If keyring is unavailable, no session is written to disk; use the `CAMPUS_EDU_COOKIE_FILE` environment variable to load a cookie file at startup.
- Read-only guard at the HTTP transport layer: allowlists methods, paths, and parameters (fixed-value enums or free-parameter regexes), rejects unregistered parameters, disables automatic redirects and re-checks every hop, treats redirects to the login page as session expiration, and enforces a default rate limit of at most 1 request per 2 seconds.
- CLI for configuration, session management, and serving:
  - `campus-edu-mcp configure --base-url URL [--min-interval 2]`
  - `campus-edu-mcp import-session --cookie-file FILE | --from-env (CAMPUS_EDU_COOKIE)`
  - `campus-edu-mcp session-status`
  - `campus-edu-mcp clear-session`
  - `campus-edu-mcp serve` (default)
- Exit codes: `0` for success, `1` when a problem was found, `2` for usage errors, `3` for session/auth errors.

## Status and limitations

- Version: `0.3.0` (local development)
- Experimental `campus-edu-mcp login --username ID` (Qiangzhi only, CLI only, **not live-verified**): manual captcha from a local image file, password via getpass only, never stored and never through MCP; requires a system keyring.
- `campus-edu-mcp doctor [--online]` self-check (reports presence only, never cookie values).
- Every result carries `meta.status` (verified / stale / pending). Zhengfang V9 is disabled unless `CAMPUS_EDU_ALLOW_UNVERIFIED=1`.
- Experimental CLI: `export-ics --term-start --periods --out` (you supply the period times).
- License: MIT
- Python: `>=3.11`
- Managed with `uv`
- Default vendor is Qiangzhi jsxsd; Zhengfang V9 is optional. Live verification against a real school cookie is still pending. Exam endpoint path for Qiangzhi is less certain than timetable/grades.
- No account/password login and no CAPTCHA recognition. Planned for `v0.2`.
- No write operations are supported. Pull requests for course grabbing, course selection/drop, or proxy-filling teaching evaluations will not be accepted.

## Quick start

### Prerequisites

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)

### Install

Clone the repository and synchronize dependencies:

#### Windows PowerShell

```powershell
git clone <repo-url>
cd campus-edu-mcp
uv sync
```

#### macOS / Linux

```bash
git clone <repo-url>
cd campus-edu-mcp
uv sync
```

### Configure and import a session

You need a valid browser session cookie from the target educational system. You can obtain it by logging in to the educational system in your browser and exporting the cookie as a request header string, Netscape `cookies.txt`, or JSON array.

#### Windows PowerShell

```powershell
uv run campus-edu-mcp configure --base-url https://jw.example.edu.cn/jsxsd/
uv run campus-edu-mcp import-session --cookie-file .\cookies.txt
uv run campus-edu-mcp session-status
```

#### macOS / Linux

```bash
uv run campus-edu-mcp configure --base-url https://jw.example.edu.cn/jsxsd/
uv run campus-edu-mcp import-session --cookie-file cookies.txt
uv run campus-edu-mcp session-status
```

You can also import from the `CAMPUS_EDU_COOKIE` environment variable:

```bash
uv run campus-edu-mcp import-session --from-env
```

If your system keyring is unavailable, set `CAMPUS_EDU_COOKIE_FILE` to a cookie file that will be loaded each time the server starts.

### MCP client configuration

The default `campus-edu-mcp` command starts the MCP server over stdio. Add a configuration like this to your MCP client:

```json
{
  "mcpServers": {
    "campus-edu-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "<path>",
        "run",
        "campus-edu-mcp"
      ]
    }
  }
}
```

Replace `<path>` with the absolute path to your local `campus-edu-mcp` repository.

## Privacy & cloud models

**Important:** stdio only means the MCP server talks to your MCP client locally. If your client uses a
cloud model (e.g. Codex, ChatGPT, Claude), every tool result **is sent to that model provider** as part
of the conversation. This project cannot prevent that; it can only minimise what is returned:

- Cookies are imported only via the CLI (file or environment variable) and never pass through MCP or the model.
- Cookies are encrypted at rest with Fernet; the key lives in the system keyring. Without a usable
  keyring nothing is written to disk (use `CAMPUS_EDU_COOKIE_FILE`).
- Tool results never include student ID, name or ranking; grades default to pass/fail + credits.
- Every result carries a `privacy_notice` reminding you that the data may have reached a cloud model.
- Logs are redacted (cookies, tokens, student IDs, sensitive URL parameters).

## Read-only guarantee

The repository enforces a strict read-only network policy for adapters:

- A guard at the `httpx` transport layer validates every outgoing request against an allowlist of method + path + parameters.
- Fixed-value enum parameters must match registered values exactly.
- Free-parameter values must match registered regex patterns.
- Any unregistered parameter is rejected before the request is sent.
- Automatic redirects are disabled. Each redirect hop is re-validated against the allowlist.
- Redirects to the login page are treated as session expiration.
- Default request rate limit: at most 1 request per 2 seconds.
- `scripts/check_adapters.py` statically checks adapter code with AST to prevent adapters from making network requests directly. It forbids imports such as `requests`, `urllib.request`, `http.client`, `aiohttp`, and `socket`, as well as direct creation of `httpx.Client` and similar clients.

## Try it without a school account

```bash
uv run python -m mock_server --port 8765            # terminal 1: fictional zfsoft V9
# terminal 2
uv run campus-edu-mcp configure --base-url http://127.0.0.1:8765/jsxsd/ --min-interval 0
echo "JSESSIONID=FAKE-MOCK-SESSION" > mock-cookie.txt
uv run campus-edu-mcp import-session --cookie-file mock-cookie.txt
uv run campus-edu-mcp session-status
```

## Development

Install dependencies:

```bash
uv sync
```

Run the main checks:

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
uv run python scripts/check_adapters.py
uv run python scripts/check_fixtures.py
```

Coverage requirements:

- Core modules: `>=80%`
- Overall project: `>=70%`

A mock server that provides fictional Zhengfang V9 endpoints is available:

```bash
uv run python -m mock_server --port 8765
```

Test fixtures must never contain real student IDs or names. Student IDs must use only fictional numbers starting with `2099`; student names must be exactly `测试学生`.

## License

MIT

## Disclaimer

This project is unofficial and is not affiliated with any school or vendor. Use it only with your own account and for lawful, read-only access to your own academic data. The maintainers are not responsible for misuse or for any consequences of using this software.

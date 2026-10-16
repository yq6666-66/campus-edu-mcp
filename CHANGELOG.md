# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-10-16

### Added

- School registry (`schools/*.yaml`, flat `key: value`, no YAML dependency): `campus-edu-mcp schools [--dir]`, status `verified` / `stale` (last_verified older than 183 days) / `pending`; `doctor` reports the configured school. Repository entries must be fictional (`*.example.edu.cn`, tested).
- Experimental Streamable HTTP transport: `serve --transport http --port N`. Binds 127.0.0.1 only (no host option), requires `CAMPUS_EDU_HTTP_TOKEN` (≥32 chars) as a Bearer token checked in constant time, and uses the SDK's DNS-rebinding protection with localhost-only Host/Origin. Not covered by semver.

### Changed

- Guard pacing is now shared per school host across all `GuardedClient`s in the process, so concurrent tool calls (e.g. over HTTP) cannot bypass `min_interval`.
- HTTP transport rejects requests with duplicate `Authorization` headers; port is validated before startup output.
- Registry validates `base_url` (http/https with host), handles quoted values, and `schools` output strips control characters.

## [0.4.0] - 2026-10-16

### Added

- Experimental `campus-edu-mcp login --username ID` (Qiangzhi, CLI only). **Not live-verified (pending)**; only the public login page, captcha image and the page script were inspected read-only.
  - `encoded = base64(account) + "%%%" + base64(password)`, `userPassword` sent empty, as in the public page script; the alternative scode/sxh obfuscation is not supported.
  - Password read with `getpass` only (no argv/env/MCP), never written to disk or logs; captcha image stored with mode 0600 and deleted afterwards; resulting cookies go straight into the encrypted `SessionStore` (refuses to run without a keyring).
  - Separate `LOGIN_RULES` whitelist (login page, captcha, `POST xk/LoginToXk` with fixed `loginMethod` and empty `userPassword`, landing page); the MCP server does not import the login module (tested).
- Login hardening after review: https only; captcha file via `mkstemp` (random name, O_EXCL, 0600) in a 0700 dir, capped at 256 KiB, removed even on Ctrl-C; success only when the redirect lands on the main page; server error text is scrubbed of account numbers and encoded credentials.
- `GuardedClient.export_cookies()` returns only cookies for the configured host.
- Mock server: fictional login flow for tests.

## [0.3.0] - 2026-10-16

### Added

- `get_empty_classrooms(week, weekday, periods?, campus?, min_capacity?, year?, term?, limit=50)` (Qiangzhi): `GET kbxx/jsjy_query` reads the time-mode/term defaults, then `POST kbxx/jsjy_query2` (`typewhere=jszq`, single week + single weekday) returns the room-occupancy grid; empty cell = free. Live-verified read-only on one Qiangzhi school (2026-10-16).
- Guard: only those two requests are whitelisted with strict params; the borrowing/ajax endpoints on the same page (`jsjy_processAjax`, `jsjy_rqAjax`, `kxjsgl.do`, `initJc`, any add/save) stay blocked, with guard tests.
- `campus-edu-mcp doctor [--online]`: Python, config, https, rate limit, vendor gate, keyring, session sources (presence only) and, with `--online`, one read-only session check.

### Changed

- `get_empty_classrooms`: `term` is `null` when the system default term is used; `campus=""` means all campuses; a grid whose columns do not match the period header raises `UpstreamError`; guard limits weeks to 1-30 and requires `kbjcmsid`.
- Expired-session detection: a response that starts with `{` is judged only by its JSON login message, never by HTML markers.

## [0.2.0] - 2026-10-16

### Fixed

- Qiangzhi: an expired session answered with HTTP 200 JSON (`{"flag1":2,"msgContent":"请先登录系统"}`) was treated as a normal page; it now raises `SessionExpired` with the re-import hint (fixture `expired_json.json`, unit + stdio e2e tests).

### Added

- `get_terms()` tool (Qiangzhi): reads the `xnxq01id` term select on the timetable page via the existing whitelisted GET. Live-verified read-only on one Qiangzhi school (2026-10-16).
- `meta` block on every data tool result (not on `session_status`): `vendor`, `endpoint`, `status` (`verified` / `stale` after 183 days / `pending`), `last_verified`. Qiangzhi exams stay `pending` (only the empty-exam page was live-checked).
- Experimental CLI `export-ics --term-start --periods --out [--year --term]`: RFC 5545 export with user-supplied period times; not covered by semver.

### Changed

- Zhengfang V9 adapter is disabled unless `CAMPUS_EDU_ALLOW_UNVERIFIED=1` (it has never been live-verified). **Migration:** zfsoft users set this variable.

## [0.1.0] - 2026-10-16

### Added

- Live-verified Qiangzhi adapter on one Qiangzhi school (2026-10-16): `#timetable` parser, `教师` font title, exam empty-row handling.
- Primary adapter switched to **Qiangzhi (jsxsd)**; example school config `schools/example-qiangzhi.yaml`.
- Zhengfang V9 adapter retained as secondary / unverified.
- Initial read-only MCP server using the official MCP SDK 2.3.0 (`MCPServer`, stdio only).
- MCP tools: `get_timetable(year?, term?)`, `get_exams(year?, term?)`, `get_grades(year?, term?, include_scores=false)`, `session_status()`.
- Grade tool privacy defaults: by default returns only course name, credits, course nature, and pass/fail status; scores and grade points are returned only when `include_scores=true`.
- `privacy_notice` attached to every tool result.
- Student ID, name, and ranking are never included in tool results.
- CLI commands:
  - `campus-edu-mcp configure --base-url URL [--min-interval 2]`
  - `campus-edu-mcp import-session --cookie-file FILE | --from-env (CAMPUS_EDU_COOKIE)`
  - `campus-edu-mcp session-status`
  - `campus-edu-mcp clear-session`
  - `campus-edu-mcp serve` (default)
- Exit codes `0`, `1`, `2`, `3`.
- Browser session cookie import from request header string, Netscape `cookies.txt`, or JSON array.
- Initial adapter for Zhengfang Educational Administration V9 (new Zhengfang, commonly under `/jwglxt/`).
- Mock server for fictional Zhengfang V9 endpoints (`uv run python -m mock_server --port 8765`).
- Static adapter guard script (`scripts/check_adapters.py`) that forbids adapters from making network requests directly.
- Fixture validation script (`scripts/check_fixtures.py`) enforcing fictional student IDs (`2099` prefix) and the fixed student name `测试学生`.

### Known limitations

- Qiangzhi timetable and grades verified live read-only on one school (2026-10-16); exam path returned empty placeholder that day — parsing with non-empty exam data is unverified.
- Zhengfang V9 adapter is retained but **not** live-verified.
- Not published to PyPI; install from a local clone / GitHub Release source archive.
- Tool results may be sent to cloud model providers when used with hosted AI clients (see `privacy_notice`).

### Security

- Read-only guard at the `httpx` transport layer:
  - Allowlist validation of method + path + parameters.
  - Fixed-value enum parameters must match registered values exactly.
  - Free-parameter values must match registered regex patterns.
  - Unregistered parameters are rejected before any request is sent.
  - Automatic redirects are disabled; each redirect hop is re-validated against the allowlist.
  - Redirects to the login page are treated as session expiration.
  - Default rate limit of at most 1 request per 2 seconds.
- Cookie storage:
  - Cookies are encrypted with Fernet.
  - Encryption key is stored in the system keyring.
  - If keyring is unavailable, cookies are not written to disk; use `CAMPUS_EDU_COOKIE_FILE` to load a cookie file at each startup.
- Cookies do not pass through the MCP protocol or model context.
- No account/password login and no CAPTCHA recognition.
- No write operations supported; PRs for course grabbing, course selection/drop, or proxy-filling teaching evaluations will not be accepted.

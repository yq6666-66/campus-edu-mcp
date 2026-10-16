# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-10-16

### Added

- `get_empty_classrooms(week, weekday, periods?, campus?, min_capacity?, year?, term?, limit=50)` (Qiangzhi): `GET kbxx/jsjy_query` reads the time-mode/term defaults, then `POST kbxx/jsjy_query2` (`typewhere=jszq`, single week + single weekday) returns the room-occupancy grid; empty cell = free. Live-verified read-only on one Qiangzhi school (2026-10-16).
- Guard: only those two requests are whitelisted with strict params; the borrowing/ajax endpoints on the same page (`jsjy_processAjax`, `jsjy_rqAjax`, `kxjsgl.do`, `initJc`, any add/save) stay blocked, with guard tests.
- `campus-edu-mcp doctor [--online]`: Python, config, https, rate limit, vendor gate, keyring, session sources (presence only) and, with `--online`, one read-only session check.

### Changed

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

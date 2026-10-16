# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

### Added

- Primary adapter switched to **Qiangzhi (jsxsd)** after confirming one Qiangzhi school uses 强智; school config `schools/example-qiangzhi.yaml` (`last_verified: pending`).
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

- Qiangzhi exam path (`xsks/xsksap_list`) and a Qiangzhi school post-login entry are not live-verified; timetable/grades paths are based on multi-school public docs.
- Not yet validated against a real school deployment; endpoint paths and field names are based on public descriptions of zfsoft V9 and fictional fixtures.
- Not published to PyPI; install from a local clone.

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

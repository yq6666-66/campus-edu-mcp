# 贡献指南

感谢你考虑为 `campus-edu-mcp` 贡献代码。本项目是一个只读 MCP 服务，当前只适配正方教务 V9，且尚未在真实学校环境完成 live 验证。请先阅读以下内容，确保你的贡献符合项目定位和质量要求。

## 开发环境

- Python `>=3.11`
- 使用 `uv` 管理依赖
- 仓库尚无远程地址，请使用 `<repo-url>` 占位克隆

```bash
git clone <repo-url>
cd campus-edu-mcp
uv sync
```

## 检查命令

提交前请确保以下命令全部通过：

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
uv run python scripts/check_adapters.py
uv run python scripts/check_fixtures.py
```

测试覆盖率要求：

- 核心模块覆盖率 `>=80%`
- 整体覆盖率 `>=70%`

另有本地 mock 服务可用于开发调试：

```bash
uv run python -m mock_server --port 8765
```

`mock_server` 提供虚构的正方 V9 接口，不会访问真实学校系统。

## 提交规范

- 使用 Conventional Commits 格式编写提交信息。
- 分支命名使用 `feat/*` 或 `fix/*`。
- 合并方式为 squash 合并。

示例：

```
feat: add term filter to get_grades
fix: reject redirect to login page in session guard
```

## 新增适配器要求

本项目当前只包含正方教务 V9 适配器。新增适配器必须满足以下全部条件，否则 PR 将不予合并：

1. 必须实现 `adapters/base.py` 中定义的适配器协议。
2. 必须在适配器中明确声明白名单：允许访问的方法、路径、参数。固定值枚举参数必须列出所有允许值；自由参数必须提供正则表达式。
3. 必须附带脱敏的 fixture 数据，且 fixture 不得出现真实学号或姓名。学号只能使用 `2099` 开头的虚构号码，学生姓名只能是 `测试学生`。
4. 必须通过 `scripts/check_adapters.py` 静态检查。该脚本使用 AST 禁止适配器自行发起网络请求：禁止 `import requests`、`urllib.request`、`http.client`、`aiohttp`、`socket`，禁止直接创建 `httpx.Client` 等客户端。
5. 必须通过只读守卫相关测试、覆盖率要求，以及上述全部 `ruff`、`mypy`、`pytest` 检查。

## 禁止写操作 PR

本项目不接受任何写操作相关的 PR，包括但不限于：

- 抢课
- 选课、退课
- 评教代填
- 修改成绩、修改课表
- 任何非只读接口调用

只读守卫的存在就是为了防止写操作。任何绕过或弱化只读守卫的 PR 都会被拒绝。

## 环境变量

项目使用以下环境变量（开发时请勿在测试或提交中写入真实 Cookie）：

- `CAMPUS_EDU_BASE_URL`
- `CAMPUS_EDU_DATA_DIR`
- `CAMPUS_EDU_MIN_INTERVAL`
- `CAMPUS_EDU_COOKIE_FILE`
- `CAMPUS_EDU_COOKIE`（仅用于 `import-session --from-env`）

Cookie 在本地使用 Fernet 加密，密钥存储在系统 keyring 中。keyring 不可用时不落盘。请勿在代码、日志、测试或 fixture 中输出真实 Cookie。

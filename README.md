# campus-edu-mcp

> 只读的高校教务 MCP 服务：让 AI 回答「我明天几点上课」「下周有什么考试」「上学期挂科了吗」。
> **非官方项目，只能查询你本人的账号，永远不做选课、退课、评教等任何写操作。**

当前版本 v1.1.0（本地，未发布）。API 稳定性与弃用策略见 [docs/api-stability.md](docs/api-stability.md)，从 0.1.0 升级见 [docs/migration.md](docs/migration.md)。**默认适配强智教务（jsxsd）**；正方 V9 适配器仍保留但未实测。

示例学校配置见 `schools/example-qiangzhi.yaml`（请改成你自己学校的 `base_url`）。
强智适配器已在**一所强智校**做过只读 live 验证（课表 / 成绩，2026-10-16）；考试路径因校而异，有实际考试数据时的解析尚未验证。正方 V9 未做 live 实测。

## 功能

厂商用 `--vendor qiangzhi|zfsoft_v9` 选择（默认 `qiangzhi`）。

| MCP 工具 | 说明 |
|---|---|
| `get_timetable(year?, term?)` | 本人课表 |
| `get_exams(year?, term?)` | 本人考试安排（时间、地点、座位号） |
| `get_grades(year?, term?, include_scores=false)` | 成绩。**默认只返回课程、学分、课程性质、是否通过**；`include_scores=true` 才返回分数和绩点 |
| `get_terms()` | 列出教务系统可选学期（已在一所强智校只读实测） |
| `get_empty_classrooms(week, weekday, periods?, campus?, min_capacity?, year?, term?, limit=50)` | 某教学周某天的空闲教室（只读查询教室占用网格，不会提交借用申请；已在一所强智校只读实测） |
| `session_status()` | 会话是否已导入、是否仍有效（不返回任何 Cookie） |

`year` 是学年起始年（2025 表示 2025-2026 学年），`term` 为 1/2/3，不填则按日期推断当前学期。
每个数据工具结果带 `meta`（`status`: verified / stale / pending）。正方 V9 默认禁用，需 `CAMPUS_EDU_ALLOW_UNVERIFIED=1`。实验性登录（**未经 live 实测**，仅强智、仅 CLI）：`campus-edu-mcp login --username 学号`，验证码图片保存在本地由你肉眼输入，密码只在终端 getpass 输入、不保存、不经过 MCP；需要系统 keyring。失败时请继续用 `import-session`。学校登记表：`campus-edu-mcp schools`（`last_verified` 超过 183 天显示 stale）。实验性 Streamable HTTP：`CAMPUS_EDU_HTTP_TOKEN=<≥32 位随机串> campus-edu-mcp serve --transport http --port 8848`，只监听 127.0.0.1，每个请求需 `Authorization: Bearer <token>`，Host/Origin 仅限本机。厂商探测：`campus-edu-mcp detect-vendor --base-url https://jw.example.edu.cn/`（只 GET 公开路径）。兼容性见 [docs/supported-vendors.md](docs/supported-vendors.md)。自检：`campus-edu-mcp doctor [--online]`（只报告有/无，不输出 Cookie）。实验性 CLI：`campus-edu-mcp export-ics --term-start YYYY-MM-DD --periods 作息.json --out kb.ics`（作息时间需自己提供；时间为不带时区的本地时间）。

课表 / 考试 / 成绩结果都**不含学号、姓名、排名**，并附带 `privacy_notice`（`session_status` 不含该字段）。

## ⚠️ 隐私：云端模型会收到查询结果

stdio 只说明 MCP 服务和客户端在本机通信。**如果你的 AI 客户端用的是云端模型（Codex、ChatGPT、Claude 等），
工具返回的课表、成绩会作为对话内容发送给模型服务商。** 本项目无法阻止这一点，只能尽量少返回数据。
请自行评估后再使用 `get_grades(include_scores=true)`。

## 快速开始（Windows PowerShell）

需要 Python ≥ 3.11 和 [uv](https://docs.astral.sh/uv/)。

```powershell
git clone <repo-url> campus-edu-mcp   # 目前仓库只在本地，可直接解压源码包
cd campus-edu-mcp
uv sync

# 1. 配置教务地址（换成你学校的）
uv run campus-edu-mcp configure --base-url https://jw.example.edu.cn/jsxsd/ --vendor qiangzhi --school example-qiangzhi

# 2. 在浏览器里登录教务系统，按 F12 → 网络 → 任一请求 → 复制 Cookie 请求头，
#    保存为 cookie.txt（也支持 cookies.txt 和浏览器扩展导出的 JSON）
uv run campus-edu-mcp import-session --cookie-file .\cookie.txt
Remove-Item .\cookie.txt              # 已加密保存，原文件可以删掉

# 3. 检查会话
uv run campus-edu-mcp session-status
```

macOS / Linux 命令相同，把路径写成 `./cookie.txt` 即可。

### 接入 MCP 客户端

```json
{
  "mcpServers": {
    "campus-edu": {
      "command": "uv",
      "args": ["--directory", "C:\\path\\to\\campus-edu-mcp", "run", "campus-edu-mcp"]
    }
  }
}
```

Codex CLI 可以用：`codex mcp add campus-edu -- uv --directory C:\path\to\campus-edu-mcp run campus-edu-mcp`
（命令格式以你所用 Codex 版本的文档为准）。仓库里的 `SKILL.md` 可作为 Skill 提供给 AI。

会话过期后，工具会提示重新导入；重复第 2 步即可。**不要把 Cookie 发给 AI。**

> Windows：会话加密文件写在 `%APPDATA%\campus-edu-mcp\`。多用户共享同一 Windows 账号时，请自行评估本机权限；本项目不额外配置 NTFS ACL。

### 没有账号也能试：mock 教务

```powershell
uv run python -m mock_server --port 8765     # 终端 1：默认虚构强智 jsxsd
# 终端 2
uv run campus-edu-mcp configure --base-url http://127.0.0.1:8765/jsxsd/ --vendor qiangzhi --min-interval 0
Set-Content mock-cookie.txt "JSESSIONID=FAKE-MOCK-SESSION"
uv run campus-edu-mcp import-session --cookie-file .\mock-cookie.txt
uv run campus-edu-mcp session-status
```

## 安全设计

- **只读守卫**（`guard.py`）在 httpx transport 层检查每个出站请求：方法 + 路径 + 参数白名单，
  固定参数（如 `doType=query`、`gnmkdm`）必须精确匹配，其余参数要匹配正则，未登记的参数直接拒绝；
  关闭自动重定向，每一跳重新检查，跳到登录页视为会话失效；默认每 2 秒最多 1 次请求。
- **静态检查**（`scripts/check_adapters.py`）用 AST 禁止适配器自己联网。
- **Cookie** 只能通过命令行导入，用 Fernet 加密，密钥存系统 keyring；keyring 不可用时不落盘，
  改用环境变量 `CAMPUS_EDU_COOKIE_FILE` 指向 Cookie 文件（写在 MCP 客户端配置的 env 里）。
- **日志脱敏**：Cookie、token、学号、URL 中的敏感参数统一打码。
- **不支持**账号密码登录（计划 v0.2），**不做**任何验证码识别，不接入打码平台。

详见 [docs/compliance.md](docs/compliance.md) 与 [SECURITY.md](SECURITY.md)。

## 环境变量

见 `.env.example`：`CAMPUS_EDU_BASE_URL`、`CAMPUS_EDU_COOKIE_FILE`、`CAMPUS_EDU_DATA_DIR`、
`CAMPUS_EDU_MIN_INTERVAL`、`CAMPUS_EDU_COOKIE`（仅 `import-session --from-env` 使用）。

## 开发

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest                                   # 整体覆盖率 ≥70%
uv run python scripts/check_core_coverage.py    # 核心模块 ≥80%
uv run python scripts/check_adapters.py
uv run python scripts/check_fixtures.py
```

贡献指南见 [CONTRIBUTING.md](CONTRIBUTING.md)，适配器规范见 [docs/adapter-spec.md](docs/adapter-spec.md)。
**不接受抢课、选退课、评教代填等任何写操作相关的 PR。**

## 免责声明

本项目与任何学校、正方公司无关。仅供本人查询自己的数据、学习研究使用；自动化访问可能违反学校规定，
请自行确认，后果自负。学校提出要求时，我们会配合移除相关支持。

## 许可证

MIT

# API 稳定性与弃用策略（1.0）

自 1.0.0 起本项目遵循[语义化版本](https://semver.org/lang/zh-CN/)。下面列出**稳定**与**实验性**的范围。

## 稳定（破坏性变更只会出现在下一个主版本）

| 类别 | 内容 |
|---|---|
| MCP 工具 | `get_timetable`、`get_exams`、`get_grades`、`get_terms`、`get_empty_classrooms`、`session_status`：工具名、参数名与类型、默认值、只读注解 |
| 工具结果 | 现有字段名及含义（`tests/snapshots/api-v1.json` 冻结）；`privacy_notice` 与 `meta` 一直存在（`session_status` 除外） |
| 隐私默认值 | `get_grades` 默认不返回分数 / 绩点；任何结果都不含学号、姓名、排名 |
| CLI | `serve`（stdio）、`configure`、`import-session`、`session-status`、`clear-session`、`doctor`、`schools` 的子命令与参数；退出码 0/1/2/3 |
| 环境变量 | `CAMPUS_EDU_BASE_URL`、`CAMPUS_EDU_VENDOR`、`CAMPUS_EDU_SCHOOL`、`CAMPUS_EDU_MIN_INTERVAL`、`CAMPUS_EDU_COOKIE`、`CAMPUS_EDU_COOKIE_FILE`、`CAMPUS_EDU_DATA_DIR`、`CAMPUS_EDU_ALLOW_UNVERIFIED`、`CAMPUS_EDU_SCHOOLS_DIR` |
| 本地存储 | 会话文件格式 v1（`{"v":1,"host","cookies"}`，Fernet + keyring）；新版本必须能读取旧格式 |

**兼容的变更**（次版本即可）：新增工具、新增可选参数、结果中新增字段、`meta.status` 取值随实测更新、新增厂商适配器。
调用方应忽略不认识的字段。

## 实验性（不受语义化版本约束，可能在次版本中改变或移除）

- `campus-edu-mcp login`（账号密码登录，**未经 live 实测**）
- `campus-edu-mcp export-ics`
- `serve --transport http`（Streamable HTTP）与 `CAMPUS_EDU_HTTP_TOKEN`
- 正方 V9 适配器（需 `CAMPUS_EDU_ALLOW_UNVERIFIED=1`）
- Python 内部模块（`campus_edu_mcp.*`）不是公开 API；只有 MCP 工具与 CLI 是

## 弃用流程

1. 在某个次版本中标记弃用：CHANGELOG 的 `Deprecated` 小节、README，以及（若是工具字段）在结果中保留旧字段并新增替代字段。
2. 至少保留一个次版本、且不少于 90 天。
3. 只在下一个主版本中移除，并在 `docs/migration.md` 写明迁移方法。

只读守卫的收紧（拦截更多请求）**不视为**破坏性变更：安全优先。

## 「已验证」的含义

`meta.status` 只说明本项目在**至少一所**真实学校做过只读实测（`verified`）、实测已超过 183 天（`stale`），或仅在 fixture / mock 上验证（`pending`）。它不保证你的学校兼容。

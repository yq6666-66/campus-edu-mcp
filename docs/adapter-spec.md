# campus-edu-mcp 适配器规范

- 版本：v0.1.0（Unreleased）
- 许可证：MIT
- 运行环境：Python >= 3.11，使用 uv 管理

本文档定义 campus-edu-mcp 的教务系统适配器（Adapter）协议、白名单规则、会话失效判定、fixture 与测试要求。当前项目仅针对正方 V9（新正方，路径常见 `/jwglxt/`）的只读数据接口；真实学校环境联调（live 验证）尚未完成。

## 1. 定位与约束

适配器负责把某个教务系统的页面/接口数据映射为 MCP 工具返回的数据结构。适配器自身只做解析和映射，不能发出任何网络请求。所有 HTTP 请求必须通过 `GuardedClient` 发送。

- `GuardedClient` 是 campus-edu-mcp 提供的只读守卫客户端。
- 它在 httpx transport 层工作，只放行白名单登记的 `方法 + 路径 + 参数`。
- 未登记参数、固定参数枚举不匹配、自由参数不匹配正则的请求都会被拒绝。
- 自动重定向关闭；每一跳都会重新检查白名单。
- 任何一跳重定向到登录页时，视为会话失效。
- 默认请求频率为每 2 秒最多 1 次。

## 2. Adapter 协议（`src/campus_edu_mcp/adapters/base.py`）

| 成员 | 签名 | 说明 |
| --- | --- | --- |
| `vendor` | `ClassVar[str]` | 厂商标识，如 `zfsoft_v9`，与配置中的 `vendor` 对应 |
| `rules` | `ClassVar[Sequence[Rule]]` | 该适配器需要的全部白名单规则 |
| `__init__` | `(self, client: GuardedClient)` | 只能通过注入的 client 访问网络 |
| `check_session` | `(self) -> bool` | 会话有效返回 True；失效返回 False（内部可捕获 `SessionExpired`） |
| `timetable` | `(self, term: Term) -> list[Course]` | 指定学期课表 |
| `exams` | `(self, term: Term) -> list[Exam]` | 指定学期考试安排 |
| `grades` | `(self, term: Term \| None) -> list[ScoreDetail]` | 完整成绩；`None` 表示全部学期 |

数据模型都在 `models.py`（pydantic，`extra="forbid"`）：

- `Term(year: int, term: int)`：`year` 为学年起始年（2025 表示 2025-2026 学年），`term` 为 1/2/3。到厂商参数的映射（如正方的 `xqm` 3/12/16）放在适配器内部。
- `Course`、`Exam`：没有学号、姓名字段，模型层就无法携带这些信息。
- `ScoreDetail` 继承 `GradeSummary`。**裁剪由工具层负责**：默认只输出 `GradeSummary`（course/year/term/credit/nature/passed），`include_scores=true` 时才输出 `score`、`grade_point`；`privacy_notice` 也由工具层附加。适配器只要如实填充 `ScoreDetail` 即可。

## 3. 白名单规则 Rule（`guard.py`）

```python
@dataclass(frozen=True)
class Rule:
    method: str  # "GET" / "POST"
    path: str  # 相对 base_url 的路径，不以 / 开头，不含查询串
    fixed: Mapping[str, frozenset[str]] = {}  # 固定参数：必须出现，取值必须在枚举内
    free: Mapping[str, str] = {}  # 自由参数：可选，取值必须整体匹配正则
    description: str = ""
```

- 查询串和 `application/x-www-form-urlencoded` 表单参数**合并校验**，其他类型的请求体一律拒绝。
- 未出现在 `fixed`/`free` 中的参数一律拒绝；同名参数取值不同时拒绝。
- 主机、协议、端口必须与 base_url 一致，路径必须在 base path 之下。

正方 V9 成绩接口（真实代码见 `adapters/zfsoft_v9.py`）：

```python
Rule(
    "POST",
    "cjcx/cjcx_cxXsgrcj.html",
    fixed={"doType": frozenset({"query"}), "gnmkdm": frozenset({"N305005"})},
    free={"xnm": r"(20\d{2})?", "xqm": r"(3|12|16)?", "queryModel.showCount": r"[1-9]\d{0,3}"},
    description="个人成绩查询",
)
```

## 4. 会话失效判定

- 重定向到登录页（路径含 `login_slogin`、`/cas/login`、`/login`）时，`GuardedClient` 直接抛 `SessionExpired`，**不会去请求登录页**。
- 返回 200 但内容是登录页（如正方的 `<h5>用户登录</h5>`），或 HTTP 401/403 时，适配器应抛 `SessionExpired`。
- 被 guard 拒绝时抛 `GuardViolation`；适配器不得捕获后改用其他请求重试。
- 工具层捕获 `SessionExpired` 后，提示用户在终端运行 `campus-edu-mcp import-session` 重新导入。

## 5. fixture 要求

所有适配器相关的 HTML/JSON fixture 必须满足：

- 数据完全虚构，结构参照目标系统公开的接口形态（不得复制其他项目受版权或 copyleft 约束的代码或数据）。
- fixture 不得出现真实学号、姓名；学号只能使用 `2099` 开头的虚构号；学生姓名只能是“测试学生”。
- 不得包含真实 Cookie、真实学校地址、联系电话、邮箱等。
- 成绩 fixture 中至少包含一门不及格课程，以及等级制成绩（如“优秀”“不及格”）。
- 必须可以通过 `uv run python scripts/check_fixtures.py` 检查。

## 6. 测试要求

每个适配器至少要包含以下测试：

1. 对每一条 `Rule`：
   - 至少一个放行用例：请求的方法、路径、`fixed`、`free` 与规则完全匹配，能被 `GuardedClient` 放行。
   - 至少一个参数不符用例：例如未登记参数、`fixed` 枚举值错误、`free` 不匹配、路径或方法不符；这些请求必须被拒绝。
2. 会话失效用例：模拟重定向到登录页或返回登录页内容，断言抛出 `SessionExpired`。
3. 结果映射用例：使用虚构 fixture 验证 `timetable`、`exams`、`grades` 的字段映射和隐私约束（不返回学号、姓名、排名）。
4. 网络隔离检查：运行 `uv run python scripts/check_adapters.py`，确认适配器没有直接 `import requests`、`urllib.request`、`http.client`、`aiohttp`、`socket`，也没有直接创建 `httpx.Client` 等。

本地开发命令：

```text
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run python scripts/check_adapters.py
uv run python scripts/check_fixtures.py
uv run python -m mock_server --port 8765
```

核心模块覆盖率要求 >= 80%，整体覆盖率要求 >= 70%。

## 7. 提交清单

新增或修改适配器时，Pull Request 应包含：

- [ ] 在 `service.ADAPTERS` 中注册；适配器实现 `vendor`、`rules`、`__init__` 等协议成员，所有网络访问均通过 `GuardedClient`。
- [ ] 每条规则提供 `method`、`path`、`fixed`、`free`、`description`。
- [ ] 会话失效场景处理：登录页跳转/特征触发 `SessionExpired`。
- [ ] 虚构 fixture：符合真实学号/姓名禁止规则。
- [ ] 放行与参数不符被拒测试。
- [ ] 通过 `ruff`、`mypy`、`pytest`、`check_adapters.py`、`check_fixtures.py`。
- [ ] 使用 Conventional Commits 提交说明，分支命名符合 `feat/*` 或 `fix/*`。
- [ ] 不包含任何写操作：不接受抢课、选退课、评教代填等写操作相关 PR。

项目当前版本：v0.1.0（Unreleased）。真实学校环境联调（live 验证）待完成，新增适配器应明确标注其验证状态。

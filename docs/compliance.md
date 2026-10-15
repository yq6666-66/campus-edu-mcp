# 合规与只读说明

## 1. 定位
campus-edu-mcp 只读取**用户本人**在教务系统中可以看到的课表、考试安排和成绩。
项目**永远不实现**选课、退课、抢课、评教代填、修改个人信息等任何写操作，也不接受此类 PR。

## 2. 技术保证
| 措施 | 位置 |
|---|---|
| 方法 + 路径 + 参数白名单，未登记即拒绝 | `src/campus_edu_mcp/guard.py` |
| 关闭自动重定向，逐跳复查；跳登录页 = 会话失效 | `GuardedClient._request` |
| 适配器禁止自行联网（AST 静态检查） | `scripts/check_adapters.py` |
| 请求频率限制（默认 2 秒 1 次） | `GuardedClient._throttle` |
| 写接口被拒的测试 | `tests/test_guard.py`、`tests/test_e2e_stdio.py`（mock 写接口命中数必须为 0） |

## 3. 登录与凭据
- 只支持导入浏览器已登录的 Cookie，经命令行从文件或环境变量读取，**不经过 MCP 与模型**。
- 不保存密码；不做验证码识别；不接入任何打码平台。
- Cookie 用 Fernet 加密，密钥在系统 keyring；keyring 不可用时不落盘。

## 4. 隐私
- 只在本机运行，项目没有任何云端服务、遥测或统计。
- **但使用云端模型时，工具结果会发送给模型服务商**，README、SKILL.md、工具描述和每次响应的 `privacy_notice` 都写明了这一点。
- 默认不返回学号、姓名、排名；成绩默认只返回是否通过与学分。
- 日志统一经过 `redact()`，覆盖 Cookie、token、学号、URL 参数。
- fixture 全部虚构，CI 用 `scripts/check_fixtures.py` 正则检查。

## 5. 使用规范
- 只访问本人账号，不代他人查询。
- 遵守学校规定；如学校明确禁止自动化访问，请停止使用。
- 学校提出要求时，维护者会移除对应学校的支持说明。

## 6. 发布节奏
小范围试用（本人和自愿的同学）通过、完成合规评估后，再决定是否公开发布 GitHub Release / PyPI。

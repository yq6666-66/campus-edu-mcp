# 如何贡献脱敏 HAR（树维新 EAMS 等）

本项目只接受**脱敏后**的网络记录，用于把已公开、只读的业务路径登记进守卫白名单并编写虚构 fixture。不要提交未脱敏的原始 HAR。

## 推荐步骤

1. 在桌面浏览器登录教务（你自己的账号），打开开发者工具 → Network。
2. 依次打开：课表、成绩、考试安排（只浏览，不要提交选课/评教/改密）。
3. 导出 HAR（或复制相关 XHR/Fetch）。
4. **删除或替换**下列内容后再发给维护者 / 开 Issue 附件：
   - 请求与响应头里的 `Cookie`、`Set-Cookie`、`Authorization` 的**值**（可保留头名）
   - 学号、姓名、身份证、手机号、邮箱
   - 分数、绩点、排名、班级名、教师真名（可改成 `2099000001`、`测试学生`、`测试老师A`）
   - 完整学校域名（写成 `jw.example.edu.cn`）
5. **可以保留**：
   - 路径与方法（如 `GET /student/for-std/course-table/get-data`）
   - 查询参数**名**与虚构值（`semesterId`、`dataId`）
   - JSON **字段名**与脱敏后的结构样例
   - 状态码、`Content-Type`

## 树维新 EAMS 特别有用的请求（均需已登录）

公开资料中常见、但本仓库 **v1.1 尚未登记** 的路径（前缀可能是 `/student` 或 `/eams5-student`）：

- `GET …/for-std/course-table`（常 302，Location 含 studentId）
- `GET …/for-std/course-table/get-data`
- `POST …/ws/schedule-table/datum`（若响应为课表 JSON）
- `GET …/for-std/grade/sheet/info/{id}`
- `GET …/for-std/exam-arrange/info/{id}`

请不要贡献选课、评教提交、改密等写操作请求。

## 许可证与安全

贡献即视为同意以 MIT 许可用于本项目的测试与文档。维护者可能再编辑一版虚构 fixture 后才合入。切勿在 HAR 里留下真实 Cookie。

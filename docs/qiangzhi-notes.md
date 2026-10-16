# 强智教务（jsxsd）公开资料笔记

调研日期：2026-10-16。**下列为公开资料与一次只读实测的归纳；各校部署可能不同。**

## 某强智校公开观察（仅未登录 GET，域名已脱敏）

| 项 | 结果 |
|---|---|
| 登录 URL | `https://jw.example.edu.cn/Logon.do?method=logon` |
| 版权 | 页面常见「强智科技」版权字样 |
| 验证码 | `/verifycode.servlet`（根路径）；jsxsd 下为 `/jsxsd/verifycode.servlet` |
| 登录加密字段 | `encoded`、`scode`、`sxh`、`RANDOMCODE`（页面脚本可见） |
| 会话探测 URL | `/Logon.do?method=logon&flag=sess` |
| jsxsd 入口 | `https://jw.example.edu.cn/jsxsd/` 返回另一套登录页，表单 action 为 `/jsxsd/xk/LoginToXk` |
| 登录成功跳转（根路径脚本） | `index.htmlx`（**未核实**登录后是否再进 jsxsd） |

## 公开端点（多校 jsxsd 部署的常见路径）

| 用途 | 路径 | 方法 | 常见参数 | 证据强度 |
|---|---|---|---|---|
| 课表 | `/jsxsd/xskb/xskb_list.do` | GET/POST | `xnxq01id=YYYY-YYYY-N`，偶见 `Ves632DSdyV` | **高**：多个 MIT 项目与公开笔记 |
| 成绩 | `/jsxsd/kscj/cjcx_list`（有的带 `.do`） | GET/POST | `kksj`、`kcxz`、`kcmc`、`xsfs=all`；表格 `#dataList` | **高**：多篇公开博客 / Apifox |
| 考试安排 | `/jsxsd/xsks/xsksap_list`（或 `.do`） | GET/POST | `xnxqid` 或 `xnxq01id` | **低**：名称来自社区惯例，**表头因校而异，需自测** |

另有移动端 JSON 风格 `app.do?method=getKbcxAzc|getCjcx|getKscx`（需 token），本 MVP **不使用**。

## HTML 结构（课表）

学期理论课表常见 `#kbtable`，单元格内 `.kbcontent`（忽略 `.kbcontent1` 占位），课程块用一长串 `-` 分隔；
教师 / 周次 / 教室分别在 `font[title="老师"]`、`font[title="周次(节次)"]`、`font[title="教室"]`。
解析器为自行实现，未复制 GPL（Dawn-Course）或其它项目代码。

## 许可证注意

调研时浏览了 MIT 项目 `inannan423/classCrawl`、`tangjiafu430-bot/xiaoai-kebiao-importer` 的路径与结构描述，
以及 GPL-3.0 的 Dawn-Course（**只看路径名，未使用其代码**）。

## 只读 live 验证（2026-10-16，一所强智校）

- 会话 Cookie 有效时，`GET xskb/xskb_list.do` 返回 `#timetable`。
- `POST kscj/cjcx_list`（`xsfs=all`）返回 `#dataList` 成绩表。
- `POST xsks/xsksap_list`（`xnxqid=YYYY-YYYY-N`）可达；无考试时表体为提示行。
- 未使用 `app.do` JSON 接口。

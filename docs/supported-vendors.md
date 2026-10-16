# 支持的教务系统厂商

主机名（如 `jwglxt`、`jwxt`）**不等于**厂商。必须以路径和页面脚本指纹为准。

## 状态

| 状态 | 含义 |
|---|---|
| verified | 至少在一所真实学校做过只读实测（见结果里的 `meta`） |
| unverified | 有适配器骨架或实现，但未 live 实测；默认禁用，需 `CAMPUS_EDU_ALLOW_UNVERIFIED=1` |
| detect-only | 仅 `detect-vendor` 会报告，无业务适配器 |

## 兼容性表

| 厂商 | vendor id | 状态 | 公开入口指纹（示例） | 本项目能力 |
|---|---|---|---|---|
| 强智 jsxsd | `qiangzhi` | **verified** | `/jsxsd/`、`LoginToXk`、`verifycode.servlet`、`#timetable` | 课表、成绩、学期、空闲教室、会话检查；考试解析仅验证过空列表 |
| 正方 V9 | `zfsoft_v9` | unverified | `/jwglxt/xtgl/login_slogin.html`、`gnmkdm=N…` | 适配器可用但未 live 实测；需门控 |
| 树维新 EAMS（EAMS5） | `supwisdom_eams5` | unverified（骨架） | `/student/` 或 `/eams5-student/`、`CONTEXT_PATH`、`eams-ui`、`GET login-salt` | Cookie 导入 + 公开探测；课表/成绩/考试**待脱敏 HAR** |
| 树维旧 EAMS | （无） | detect-only | `/eams/`、`*.action`、`homeExt.action` | 仅探测 |
| 青果 KINGOSOFT | （无） | detect-only | `/jwweb/`、`SetKingoEncrypt`、`cas/logon.action` | 仅探测 |
| URP / 清元 | （无） | detect-only | `j_spring_security_check`、`loginAction.do` | 仅探测 |
| 金智 Wisedu | （无） | detect-only | `/authserver/login`、`pwdDefaultEncryptSalt` | 仅探测（常为统一认证，业务路径因校而异） |

## 探测

```bash
campus-edu-mcp detect-vendor --base-url https://jw.example.edu.cn/ --json
```

只发送公开 GET，不带 Cookie，默认每 2 秒最多 1 个请求。结果里的 `winner` / `confidence` 是启发式，不是认证。

## 贡献

若你的学校是树维新 EAMS 且已能用浏览器登录，请按 [har-contribution.md](har-contribution.md) 提供脱敏 HAR，以便把 `for-std/*` 等只读路径安全地加入白名单。

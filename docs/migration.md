# 迁移说明：0.1.0 → 1.0.0

## 需要你动手的变化

- **正方 V9 默认禁用**（0.2.0）：如果你用 `vendor=zfsoft_v9`，需要设置 `CAMPUS_EDU_ALLOW_UNVERIFIED=1`，否则工具会返回配置错误。该适配器从未做过 live 实测。
- **会话过期判定更准确**（0.2.0）：部分强智学校在会话过期时返回 HTTP 200 的 JSON（`{"flag1":2,"msgContent":"请先登录系统"}`）。0.1.0 会把它当成正常页面；现在会提示重新导入会话。

- **`get_grades` 的 `term`**（1.0.0）：不传 year/term（全部学期）时，`term` 从字符串 `"全部学期"` 改为 `null`，与其它工具统一。依赖该字符串的调用方请改判 `null`。

## 只需要知道的变化（兼容）

- `get_empty_classrooms` 的结果自 1.0.0 起也带 `privacy_notice`。
- 每个数据工具的结果新增 `meta` 字段（`vendor`、`endpoint`、`status`、`last_verified`）。忽略它也不影响使用。
- 新增工具：`get_terms`（学期列表）、`get_empty_classrooms`（空闲教室，只读）。
- 新增命令：`doctor`、`schools`；实验性 `login`、`export-ics`、`serve --transport http`。
- 同一学校的请求在整个进程内共享限速（默认每 2 秒最多 1 个请求），并发调用会排队。

## 没有变化

- 会话存储格式仍是 v1，升级无需重新导入 Cookie。
- 现有工具的参数和结果字段保持不变；`get_grades` 默认仍不返回分数。

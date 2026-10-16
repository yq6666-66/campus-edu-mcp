---
name: campus-edu
description: 通过只读的 campus-edu-mcp 查询用户本人的课表、考试安排和成绩（强智教务（jsxsd；可选正方 V9））。
---

# 校园教务助手（只读）

## 何时使用
用户问到自己的课表（「明天几点上课」「这周有什么课」）、考试（「下周考什么、在哪考」）或成绩（「挂科了吗」「这学期学分多少」）时。

## 工具
- `get_timetable(year?, term?)`：课表。`weekday` 1=周一；`sessions` 是节次；`weeks` 是上课周。
- `get_exams(year?, term?)`：考试安排。
- `get_grades(year?, term?, include_scores=false)`：成绩，默认只有是否通过和学分。
- `session_status()`：检查会话。

`year` 是学年**起始年**（2025-2026 学年填 2025），`term` 1=第一学期 2=第二学期 3=小学期；不确定就不填。

## 规则
1. **只读**：这些工具不能选课、退课、评教，用户要求这类操作时直接说明做不到。
2. **分数按需**：只有用户明确想知道具体分数或绩点时，才传 `include_scores=true`。问「挂科了吗」用默认值即可（看 `passed` 和 `failed_count`）。
3. **不要索要凭据**：会话失效（`SessionExpired` / `SessionMissing`）时，告诉用户在自己的终端运行
   `campus-edu-mcp import-session --cookie-file <文件>`，**绝不要让用户把 Cookie 或密码发到对话里**。
4. **隐私提示**：首次展示成绩时，转述一次 `privacy_notice`（数据可能已发送给云端模型服务商）。
5. 回答「明天」「这周」时，结合当前日期与 `weeks`、`weekday` 推算；不确定第几周时先问用户。

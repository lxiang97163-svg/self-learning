# tutor — 工作流（Phase 0–6）

> 基于 StudyVault 的自适应测验 + 概念级掌握度追踪。

---

## 触发时机

用户说"quiz me"、"测我"、"学习"、"퀴즈"、或直接 `/tutor`。

---

## 6 个阶段

### Phase 0：检测语言
从用户消息判断语言 `{LANG}`，所有输出和文件内容用 `{LANG}`。

### Phase 1：发现 Vault
```
Glob **/StudyVault/  →  列出各区域目录
Glob **/StudyVault/*dashboard*  →  找 Dashboard
```
- Dashboard 存在 → 读取
- 不存在 → 用模板新建
- StudyVault 不存在 → 报错停止，提示先用 `/tutor-setup`

### Phase 2：询问 Session 类型（必须 AskUserQuestion）

根据 Dashboard 当前状态，动态生成选项：

| 条件 | 选项 |
|------|------|
| 有 ⬜ 区域 | 诊断测验（覆盖未测试区域）|
| 有 🟥/🟨 区域 | 专攻弱项（指明最弱区域名）|
| 总是有 | 自选区域 |
| 全部 🟩/🟦 | 困难模式复习 |

**用户必须选完才能继续。**

### Phase 3：出题

1. 读目标区域的 Markdown 文件
2. 如果是打弱项：还要读 `concepts/{area}.md`，找到 🔴 概念，**换角度出题**（不重复原题）
3. 严格按照 [[03-tutor/Quiz-Rules]] 出 4 道题

### Phase 4：呈现测验（AskUserQuestion）
- 4 题，每题 4 选项，单选
- Header 格式：`Q1. Topic`（最多 12 字符）
- 选项描述：只说"是什么"，绝不暗示对错

### Phase 5：批改 + 解释
1. 展示结果表（题目 / 正确答案 / 你的答案 / 结果）
2. 错题给出简洁解释
3. 把每道题映射到对应区域

### Phase 6：更新文件（必须执行）

更新 `concepts/{area}.md`：
- 新概念 → 新增表格行
- 旧 🔴 概念答对 → 状态改 🟢，保留错误笔记
- 旧 🟢 概念答错 → 状态改回 🔴，更新错误笔记

更新 Dashboard：
- 从 concepts 文件重新计算各区域数据
- 更新进度徽章

---

## 关键约束

- Phase 2 的 AskUserQuestion **不能跳过**
- 出题前**必须读** `references/quiz-rules.md`
- 批改后**必须更新**两个文件：concepts/{area}.md + Dashboard

## Related Notes

- [[03-tutor/Quiz-Rules]]
- [[03-tutor/Tracking-System]]
- [[01-Architecture/System-Overview]]

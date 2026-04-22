# 进度追踪系统

---

## 两层文件结构

```
StudyVault/
├── *dashboard*.md       ← 汇总层：各区域聚合数字
└── concepts/
    └── {area}.md        ← 概念层：每道题的记录
```

**原则**：Dashboard 永远精简（只有数字），concepts 文件承载细节（随概念数线性增长，有界）。

---

## 进度徽章含义

| 徽章 | 名称 | 正确率 |
|------|------|--------|
| ⬜ | 未测试 | 无数据 |
| 🟥 | 弱 | 0–39% |
| 🟨 | 一般 | 40–69% |
| 🟩 | 好 | 70–89% |
| 🟦 | 已掌握 | 90–100% |

---

## Concepts 文件格式

### 概念追踪表

```markdown
| Concept | Attempts | Correct | Last Tested | Status |
|---------|----------|---------|-------------|--------|
| Phase 0 语言检测 | 2 | 1 | 2026-04-22 | 🔴 |
| Zero-Hint Policy | 3 | 3 | 2026-04-22 | 🟢 |
```

Status 用 🟢（本轮答对）/ 🔴（本轮答错）追踪**当前状态**，Dashboard 用百分比追踪**累计水平**。

### 错误笔记格式

```markdown
### Error Notes

**Phase 0 语言检测**
- Confusion: 以为是从系统设置读语言
- Key point: 从用户的当前消息内容检测语言
```

---

## 更新规则

| 情况 | 操作 |
|------|------|
| 新概念，答对 | 新增行，Status = 🟢 |
| 新概念，答错 | 新增行，Status = 🔴，写错误笔记 |
| 旧 🔴 概念，答对 | attempts+1，correct+1，Status → 🟢，保留错误笔记 |
| 旧 🟢 概念，答错 | attempts+1，Status → 🔴，更新错误笔记 |

---

## Dashboard 计算方式

Dashboard 的数据从 concepts 文件聚合而来，不独立存储：

```
某区域正确率 = 该区域所有概念 correct 之和 / attempts 之和
```

---

## "出师"的标准

Dashboard 所有区域都达到 🟦（正确率 ≥90%）。

## Related Notes

- [[03-tutor/Overview]]
- [[03-tutor/Quiz-Rules]]
- [[00-Dashboard/Learning-Dashboard]]

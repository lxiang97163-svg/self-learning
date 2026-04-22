# tutor-setup — 概述

---

## 触发时机

用户说"帮我学 X"、"把这个文档转成学习材料"、或者直接 `/tutor-setup`。

## 自动检测模式

```python
if CWD 存在 package.json / go.mod / Cargo.toml / pom.xml 等项目标记:
    → Codebase Mode（代码库模式）
else:
    → Document Mode（文档模式）
```

> **关键约束**：先向用户确认检测到的模式，再继续。

## 两种模式对比

| 维度 | Document Mode | Codebase Mode |
|------|--------------|---------------|
| 输入 | PDF / MD / HTML / EPUB / URL | 源代码仓库 |
| 目标读者 | 学知识的人 | 新进开发者 |
| 核心产出 | 概念笔记 + 练习题 | 模块笔记 + 上手练习 |
| 阶段数 | D1–D9 | C1–C9 |
| 关键规则 | PDF 必须用 pdftotext 转换 | 不能跨 CWD 访问 |

## 共同约束

- **CWD 边界**：所有读写必须在 CWD 内，外部路径需先复制进来
- **语言匹配**：笔记语言跟源材料一致（中文材料→中文笔记）；Tag 永远英文

## Related Notes

- [[02-tutor-setup/Document-Mode]]
- [[02-tutor-setup/Codebase-Mode]]
- [[01-Architecture/System-Overview]]

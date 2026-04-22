# tutor-setup — Document Mode（D1–D9）

> 把 PDF、文本、网页等知识材料转成 Obsidian StudyVault。

---

## 9 个阶段速览

| 阶段 | 名称 | 核心动作 |
|------|------|---------|
| D1 | Source Discovery | 扫描 CWD，找到所有文档；PDF 用 pdftotext 转文本 |
| D2 | Content Analysis | 分析主题层级、依赖关系，建完整 topic checklist |
| D3 | Tag Standard | 定义 tag 词汇表（英文 kebab-case），写注册表 |
| D4 | Vault Structure | 建 StudyVault/ 目录，按主题分组（每组 3–5 概念）|
| D5 | Dashboard Creation | 建 MOC、Quick Reference、Exam Traps |
| D6 | Concept Notes | 每个概念写一篇笔记（含 YAML frontmatter）|
| D7 | Practice Questions | 每个主题文件夹 ≥8 道题，答案用折叠 callout |
| D8 | Interlinking | 所有笔记互相 [[wiki-link]] 连接 |
| D9 | Self-Review | 对照 quality-checklist.md 自检，不通过就改 |

---

## 关键规则详解

### D1：PDF 处理（绝对不能用 Read 直接读 PDF）

```bash
# 正确做法
pdftotext "source.pdf" "/tmp/source.txt"
# 然后 Read /tmp/source.txt
```

> [!warning] 为什么？
> Read 工具读 PDF 会把每页渲染成图片，消耗 10–50 倍 token。必须先用 CLI 转文本。

### D2：Equal Depth Rule（所有主题等深）

哪怕原材料只用一句话提到某个子主题，也必须给它一篇完整的概念笔记，补充教科书级别的知识。

### D2：Classification Completeness

当原材料写"有 3 种 X"，每种 X 都必须有独立笔记。扫描关键词："types of"、"N 种"、"categories"。

### D6：Concept Note 必须有的内容

```yaml
---
source_pdf: 来源文件名（必须和 D1 映射匹配，不能猜）
part: 章节
keywords: [关键词1, 关键词2]
---
```

内容格式首选：比较表 > ASCII 图 > prose（叙述文字）

### D7：题型分布要求

- ≥60% 主动回忆题
- ≥20% 应用题
- ≥2 道分析题（per 文件）

答案格式：`> [!answer]- 查看答案` 折叠 callout

---

## 常见陷阱

| 陷阱 | 正确做法 |
|------|---------|
| 直接 Read PDF | pdftotext 转文本再 Read |
| 从文件名猜内容 | 读封面+目录+中间几页，建立实际映射 |
| 某主题只有一句话就跳过 | Equal Depth Rule：补全它 |
| Tag 用中文 | Tag 永远英文 kebab-case |

## Related Notes

- [[02-tutor-setup/Overview]]
- [[02-tutor-setup/Codebase-Mode]]
- [[02-tutor-setup/Exercises]]

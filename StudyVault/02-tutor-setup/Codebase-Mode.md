# tutor-setup — Codebase Mode（C1–C9）

> 把源代码仓库转成新开发者上手的 StudyVault。

---

## 9 个阶段速览

| 阶段 | 名称 | 核心动作 |
|------|------|---------|
| C1 | Project Exploration | Glob 扫文件树，识别技术栈，读 README + 入口文件 |
| C2 | Architecture Analysis | 识别架构模式，追踪请求流，画模块依赖 |
| C3 | Tag Standard | 定义 `#arch-*` / `#module-*` / `#pattern-*` / `#api-*` 等 tag |
| C4 | Vault Structure | 建 00-Dashboard + 01-Architecture + 各模块目录 + Exercises |
| C5 | Dashboard | MOC（模块地图+API 列表+Getting Started+上手路径）+ Quick Reference |
| C6 | Module Notes | 每个模块一篇笔记（Purpose + Key Files + 内部流程 + 依赖）|
| C7 | Onboarding Exercises | 代码阅读 + 配置 + 调试 + 扩展练习，每个主要模块 ≥5 道 |
| C8 | Interlinking | 模块笔记互连，架构笔记引用具体实现，练习引用对应模块 |
| C9 | Self-Review | 对照 quality-checklist.md 自检 |

---

## 与 Document Mode 的关键区别

| 维度 | Document Mode | Codebase Mode |
|------|--------------|---------------|
| 入口文件 | PDF/MD/HTML | README / package.json / main.* |
| 笔记单位 | 概念 | 模块/域 |
| 练习类型 | 主动回忆题 | 代码阅读/配置/调试/扩展 |
| 核心图表 | 概念关系图 | 请求流 ASCII 图 + 模块依赖图 |

---

## C6：Module Note 必须有的字段

```yaml
---
module: 模块名
path: src/module-name/
keywords: [keyword1, keyword2]
---
```

正文必须包含：
- **Purpose**：这个模块干什么（1–3 句）
- **Key Files**：重要文件表格
- **Public Interface**：对外暴露的函数/类/端点
- **Internal Flow**：数据流 ASCII 图
- **Dependencies**：依赖谁 + 谁依赖它
- **Testing**：怎么跑这个模块的测试

---

## C7：练习类型

```
代码阅读题："当 X 发生时，追踪它经过哪些文件？"
配置题：    "如果要修改 Y，需要改哪里？"
调试题：    "如果报错 Z，你先去看哪里？"
扩展题：    "如果要新增功能 W，架构上怎么加？"
```

所有答案用 `> [!answer]- 查看答案` 折叠 callout。

---

## 常见陷阱

| 陷阱 | 正确做法 |
|------|---------|
| 光读 README 就开始写笔记 | C1 必须读入口文件 + 几个核心模块文件 |
| 模块笔记没有 ASCII 流程图 | Internal Flow 是必须项 |
| 练习只有"读代码"一种 | 4 种类型都要有 |
| 跨 CWD 访问文件 | 让用户把目标仓库复制到 CWD 内 |

## Related Notes

- [[02-tutor-setup/Overview]]
- [[02-tutor-setup/Document-Mode]]
- [[02-tutor-setup/Exercises]]

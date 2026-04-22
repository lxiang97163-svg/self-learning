# tutor-setup 练习题

---

## 练习 1：判断模式

你在一个目录里运行 `/tutor-setup`，CWD 包含以下文件：
```
README.md
notes.md
lecture-slides.pdf
```

**tutor-setup 会用哪种模式？**

> [!answer]- 查看答案
> **Document Mode**。
> 没有 package.json、go.mod、Cargo.toml 等项目标记文件，所以触发 Document Mode。
> README.md 不是项目标记，也没有源代码文件。

---

## 练习 2：判断模式

CWD 包含：
```
src/main.py
pyproject.toml
tests/
README.md
```

**tutor-setup 会用哪种模式？**

> [!answer]- 查看答案
> **Codebase Mode**。
> `pyproject.toml` 是项目标记文件，触发 Codebase Mode。

---

## 练习 3：PDF 处理

你要为一本 300 页的 PDF 教材生成 StudyVault。正确的操作流程是？

> [!answer]- 查看答案
> 1. 用 Bash 工具运行：`pdftotext "教材.pdf" "/tmp/教材.txt"`
> 2. 用 Read 工具读取 `/tmp/教材.txt`
> 3. 绝对不要用 Read 工具直接读 PDF 文件
>
> 原因：直接 Read PDF 会把每页渲染成图片，消耗 10–50 倍 token。

---

## 练习 4：Equal Depth Rule

原材料在某一章节只用了一句话提到"增量编译"：
> "本工具支持增量编译以加速构建。"

你应该怎么处理这个主题？

> [!answer]- 查看答案
> 必须给"增量编译"写一篇完整的概念笔记，并补充教科书级别的知识（定义、原理、与全量编译的区别等）。
> Equal Depth Rule：原材料的覆盖深度不影响笔记的深度。

---

## 练习 5：Module Note 缺失项

下面这篇 Module Note 缺少什么必须项？

```markdown
---
module: auth
path: src/auth/
---

# Auth 模块

**Purpose**: 处理用户认证和授权。

**Key Files**:
| 文件 | 描述 |
|------|------|
| middleware.ts | 认证中间件 |
| jwt.ts | JWT 工具函数 |
```

> [!answer]- 查看答案
> 缺少：
> 1. YAML frontmatter 里的 `keywords` 字段（必须有）
> 2. **Public Interface**：对外暴露的函数/端点
> 3. **Internal Flow**：数据流 ASCII 图
> 4. **Dependencies**：依赖谁 + 谁依赖它
> 5. **Testing**：如何运行这个模块的测试
> 6. **Related Notes** 链接

---

## Related Notes

- [[02-tutor-setup/Document-Mode]]
- [[02-tutor-setup/Codebase-Mode]]

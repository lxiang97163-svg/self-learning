# tutor 工作流练习题

---

## 练习 1：Session 类型选择

Dashboard 当前状态：
```
tutor-setup 核心概念   🟥 (30%)
Document Mode         ⬜
Codebase Mode         🟩 (75%)
tutor 工作流           🟨 (55%)
Quiz 出题规则          ⬜
进度追踪系统           🟦 (92%)
```

tutor 的 Phase 2 会给出哪些选项？

> [!answer]- 查看答案
> 1. **诊断测验** — 覆盖 Document Mode 和 Quiz 出题规则（⬜ 未测试区域）
> 2. **专攻弱项** — 重点攻 tutor-setup 核心概念（最弱：🟥 30%）
> 3. **自选区域** — 用户自己选
> （不含困难模式，因为不是全部 🟩/🟦）

---

## 练习 2：概念文件更新规则

用户在测验中遇到了"Zero-Hint Policy"这个概念：
- 第一次：答错
- 第二次：答对
- 第三次：又答错

最终这个概念的 Status 应该是什么？错误笔记应该保留几条？

> [!answer]- 查看答案
> - **Status = 🔴**（最后一次答错，改回 🔴）
> - **Attempts = 3，Correct = 1**
> - **错误笔记**：第一次和第三次各有一条（共 2 条），学习历史都保留
>
> Dashboard 对应区域的正确率 = 1/3 ≈ 33% → 🟥

---

## 练习 3：Phase 3 打弱项

用户选择"专攻弱项"，目标区域是"Quiz 出题规则"，concepts 文件里显示"Zero-Hint Policy"是 🔴 。

你能直接用上次让用户答错的那道题吗？

> [!answer]- 查看答案
> **不能。** 打 🔴 概念必须换角度出题，不能重复原题。
>
> 正确做法：从不同情境或角度测同一个知识点。
> 例如原题问"哪个描述有提示"，新题可以出"给你 4 个选项描述，哪个违反了 Zero-Hint Policy"。

---

## 练习 4：Phase 1 边界情况

用户直接输入 `/tutor`，但项目里没有 StudyVault 目录。

tutor 应该怎么做？

> [!answer]- 查看答案
> **报错并停止。** 告知用户"没有找到 StudyVault"，提示先用 `/tutor-setup` 生成学习材料。
>
> tutor 不创建 StudyVault，它依赖 tutor-setup 的输出。

---

## 练习 5：Dashboard 计算

某区域的 concepts 文件包含：

| Concept | Attempts | Correct |
|---------|----------|---------|
| Phase 0 检测语言 | 3 | 3 |
| Phase 2 Session类型 | 4 | 2 |
| Phase 6 更新文件 | 2 | 0 |

这个区域在 Dashboard 里的徽章是什么？

> [!answer]- 查看答案
> 总 Correct = 3+2+0 = 5
> 总 Attempts = 3+4+2 = 9
> 正确率 = 5/9 ≈ 56% → **🟨 一般（40–69%）**

---

## Related Notes

- [[03-tutor/Overview]]
- [[03-tutor/Quiz-Rules]]
- [[03-tutor/Tracking-System]]

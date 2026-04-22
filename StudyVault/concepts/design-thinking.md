---
name: design-thinking
description: frontend-design 动手前的思维框架
type: concept
source: teach_lx_source/SKILL.md
keywords: [design-thinking, aesthetic-direction, differentiation, purpose]
---

# 设计思维流程

#design-thinking #frontend-design

---

## 是什么

在写任何一行代码之前，先回答 4 个问题。这个过程叫"设计思维"——它保证你的实现有**明确的审美方向**，而不是随手堆砌组件。

---

## 4 个核心问题

```
Purpose       → 这个界面解决什么问题？谁在用？
Tone          → 选一个明确的风格极端
Constraints   → 框架限制？性能目标？无障碍要求？
Differentiation → 用户会记住什么？
```

### Purpose（目的与受众）

> [!important] 不同的受众 → 完全不同的设计语言
> 
> - B2B 工具 → 信息密度高，功能优先
> - 消费者品牌 → 情感共鸣，记忆点
> - 创意作品集 → 大胆展示个性

### Tone（风格方向）

> [!tip] 挑一个极端，不要居中
> 
> 模糊方向如"简洁大气"是失败的起点。要选具体的：
> 
> | 方向 | 关键特征 |
> |------|---------|
> | brutally minimal | 极度留白，无装饰，字体说话 |
> | maximalist chaos | 高密度，叠层，视觉噪点 |
> | retro-futuristic | 复古像素感 + 科技元素混搭 |
> | organic/natural | 圆润，自然色调，流动感 |
> | luxury/refined | 高对比，精选字体，微妙细节 |
> | editorial/magazine | 排版主导，大标题，非标准布局 |
> | brutalist/raw | 原始感，未加工，故意"丑" |
> | art deco/geometric | 几何图形，对称，装饰细节 |

### Constraints（技术限制）

- 框架（HTML/CSS/JS? React? Vue?）
- 性能预算（动效复杂度、包体积）
- 无障碍（对比度、键盘导航）

### Differentiation（记忆锚点）

> [!warning] 这是最重要的问题
> 
> 问自己：**用户离开后，会记住什么？**
> 
> 答案必须具体，比如：
> - "进入时标题的粒子爆炸效果"
> - "悬停时卡片的液态变形"
> - "整体像一本1920年代的杂志"

---

## 执行原则

> [!important] 有意图地执行，不是用力气堆效果
> 
> - 极致极繁（maximalist）→ 需要大量动画和层叠代码
> - 克制极简（minimalist）→ 需要精确的间距、字体和微妙细节
> - **优雅 = 把方向执行到位**，不是哪种方向更高级

---

## 相关笔记

- [[anti-patterns]] — 确认方向后，对照反模式清单检查
- [[typography]] — Tone 决定了字体选择方向
- [[color-theme]] — Tone 决定了配色策略

---
name: motion
description: frontend-design 动效策略、高影响时机与实现方式
type: concept
source: teach_lx_source/SKILL.md
keywords: [motion, animation, css-animation, motion-library, staggered-reveal]
---

# 动效与动画

#motion-animation #frontend-design

---

## 是什么

动效的价值不在于"有没有"，在于**放在哪里**。
一个精心设计的加载动画比满屏乱动的微交互更有价值。

---

## 高影响时机（优先顺序）

```
1. 页面加载 → staggered reveal（交错出现）  ← 最高投入产出比
2. Hover 状态 → 出人意料的反馈
3. 滚动触发 → 内容进入视口时出现
4. 状态切换 → 按钮、表单的交互反馈
```

### 交错出现（Staggered Reveal）

> [!tip] 一次精心编排的页面加载 > 十个散落的微交互
> 
> 原理：多个元素依次出现，用 `animation-delay` 制造节奏感

```css
/* CSS-only 交错出现 */
.hero-title    { animation: fadeUp 0.6s ease both; }
.hero-subtitle { animation: fadeUp 0.6s ease both; animation-delay: 0.1s; }
.hero-cta      { animation: fadeUp 0.6s ease both; animation-delay: 0.2s; }

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(20px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

---

## 实现方式

### CSS-only（优先选择）

- 适用于：过渡、简单出现/消失、hover 反馈
- 优点：无依赖、性能好、易于维护

### Motion 库（React 项目）

- 适用于：复杂序列动画、手势交互、页面切换
- 安装：`npm install motion`

```jsx
import { motion } from 'motion/react'

<motion.div
  initial={{ opacity: 0, y: 20 }}
  animate={{ opacity: 1, y: 0 }}
  transition={{ duration: 0.5, delay: 0.1 }}
>
  内容
</motion.div>
```

---

## 性能原则

> [!important] 只动 compositor-safe 属性
> 
> | ✅ 安全（不触发重排） | ❌ 避免（触发重排） |
> |---|---|
> | transform | width / height |
> | opacity | top / left |
> | filter（谨慎） | margin / padding |
> | clip-path | font-size |

---

## 常见踩坑

> [!warning] Trap: 动效过多反而变成背景噪音
> 
> 如果每个元素都在动，用户的注意力无处落脚。
> 克制地选 1-2 个高价值时机。

> [!warning] Trap: 动效太快或太慢
> 
> - 太快（<150ms）：用户感知不到
> - 太慢（>800ms）：用户觉得卡顿
> - 甜点区间：**300-600ms**，ease-out 或 ease-in-out

---

## 相关笔记

- [[design-thinking]] — Tone 决定动效风格（极简 vs 华丽）
- [[visual-details]] — 动效配合背景效果产生层次感
- [[spatial-composition]] — 动效要服务于布局意图，不是独立存在

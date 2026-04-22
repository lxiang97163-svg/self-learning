---
name: typography
description: frontend-design 字体选择与配对策略
type: concept
source: teach_lx_source/SKILL.md
keywords: [typography, font-pairing, display-font, body-font]
---

# 排版与字体

#typography #frontend-design

---

## 是什么

字体选择是前端设计中**最容易区分平庸与卓越**的单一决定。
差的字体让好的布局看起来像模板；好的字体让简单的页面有灵魂。

---

## 配对策略

```
一个展示字体 (display font)   → 用于标题、大号文字
一个正文字体 (body font)      → 用于正文、说明文字
两者必须形成明显对比
```

> [!tip] 对比的维度
> 
> - 有衬线 (serif) + 无衬线 (sans-serif)
> - 极粗 + 极细
> - 几何感 + 手写感
> - 古典 + 现代

---

## 禁用字体清单

> [!warning] 以下字体已被过度使用，使用即"AI slop"信号
> 
> - **Inter** — 最滥用的无衬线，千篇一律
> - **Roboto** — Material Design 感，缺乏个性
> - **Arial** — 系统默认，无任何设计意图
> - **system-ui / -apple-system** — 同上
> - **Space Grotesk** — 短暂流行后已过时

---

## 推荐方向举例

| 风格方向 | 展示字体建议 | 正文字体建议 |
|----------|-------------|------------|
| editorial | Playfair Display, Cormorant | Libre Baskerville |
| brutalist | Anton, Oswald | DM Mono |
| luxury | Didact Gothic, Bodoni Moda | Crimson Text |
| retro-futuristic | Syne, Orbitron | IBM Plex Mono |
| organic | Lora, Playfair | Source Serif |

> [!important] 不要照抄上表
> 每个项目都要做独立的字体决定，表格只是启发方向，不是答案。

---

## 加载策略

- 从 Google Fonts 或 Bunny Fonts 引入
- 只加载用到的字重（subset）
- 使用 `font-display: swap` 避免 FOIT

```css
/* 示例：只加载需要的字重 */
@import url('https://fonts.googleapis.com/css2?family=Cormorant:wght@300;600&display=swap');
```

---

## 常见踩坑

> [!warning] Trap: 字重不够大胆
> 
> 标题用 400 字重不如用 800，对比才能建立层次。
> 展示字体的价值在于**用大**——小了就浪费了个性。

> [!warning] Trap: 字体太多
> 
> 超过 2 种字体通常会打架而不是配合。坚守 2 种配对原则。

---

## 相关笔记

- [[design-thinking]] — Tone 方向决定字体风格
- [[color-theme]] — 字体颜色是色彩系统的一部分
- [[anti-patterns]] — 禁用字体的完整背景

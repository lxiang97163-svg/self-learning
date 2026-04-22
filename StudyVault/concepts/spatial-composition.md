---
name: spatial-composition
description: frontend-design 空间构图、布局语言与打破网格
type: concept
source: teach_lx_source/SKILL.md
keywords: [spatial-composition, layout, asymmetry, grid-breaking, negative-space]
---

# 空间构图与布局

#spatial-composition #frontend-design

---

## 是什么

空间构图决定界面的**视觉重力**——用户的眼睛被什么吸引，又流向哪里。
标准的居中+等间距布局是"安全"的，也是"平庸"的。

---

## 核心工具

### 非对称（Asymmetry）

> [!tip] 不平衡 = 张力 = 有趣
> 
> - 左侧大标题 + 右侧留白
> - 图片出血到边缘，文字不对称分布
> - 不同列宽的网格

### 重叠（Overlap）

- 元素叠压产生深度感
- 文字压在图片上
- 卡片之间互相叠压

### 对角线流向（Diagonal Flow）

- 用倾斜的分割线或背景带引导视线方向
- 对角线比水平线更有动感

### 打破网格（Grid-Breaking）

- 某个关键元素故意超出网格边界
- 少量突破 > 整体混乱
- 通常只用于 hero 区域的 1-2 个元素

---

## 密度两极

> [!important] 选一个极端，不要居中
> 
> | 极端 A | 极端 B |
> |--------|--------|
> | 极度负空间 | 极致密排 |
> | 文字在大片留白中 | 信息紧密堆叠 |
> | 奢侈品牌感 | 杂志/仪表盘感 |
> 
> **居中的密度 = 既不惊艳也不实用**

---

## 实现技巧

```css
/* 非均等网格 */
.layout {
  display: grid;
  grid-template-columns: 2fr 1fr;  /* 不等宽 */
}

/* 元素溢出容器（打破网格） */
.hero-image {
  margin-right: -4rem;  /* 向右溢出 */
}

/* 对角线背景分割 */
.section {
  clip-path: polygon(0 0, 100% 0, 100% 85%, 0 100%);
}
```

---

## 常见踩坑

> [!warning] Trap: 所有间距相同
> 
> 等间距 = 没有层次。不同区块之间的间距应该故意不同，
> 用密集和留白的对比建立节奏。

> [!warning] Trap: 居中居中居中
> 
> 所有东西都居中是最安全也最无聊的选择。
> 除非你在做极简风，否则引入左对齐或不对称。

---

## 相关笔记

- [[design-thinking]] — Tone 方向（editorial vs minimal）决定构图语言
- [[visual-details]] — 背景和纹理加强空间感
- [[motion]] — 进入动效要配合构图方向

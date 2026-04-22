---
name: visual-details
description: frontend-design 背景效果、纹理与氛围营造
type: concept
source: teach_lx_source/SKILL.md
keywords: [visual-details, background, texture, gradient-mesh, noise, atmosphere]
---

# 背景与视觉细节

#visual-details #frontend-design

---

## 是什么

纯色背景是最低成本的选择，也是最平淡的选择。
视觉细节（纹理、渐变、噪点）是让界面**有深度、有氛围**的关键。

---

## 效果工具箱

### 渐变网格（Gradient Mesh）

```css
/* 多色径向渐变叠加，模拟网格渐变 */
background:
  radial-gradient(ellipse at 20% 50%, rgba(120, 80, 255, 0.3) 0%, transparent 50%),
  radial-gradient(ellipse at 80% 20%, rgba(255, 120, 50, 0.2) 0%, transparent 50%),
  #0a0a0a;
```

### 噪点纹理（Noise / Grain）

```css
/* SVG 噪点作为伪元素叠加 */
.page::before {
  content: '';
  position: fixed;
  inset: 0;
  background-image: url("data:image/svg+xml,...");  /* SVG noise */
  opacity: 0.04;
  pointer-events: none;
  z-index: 999;
}
```

> [!tip] 噪点的作用
> 
> 在纯色或渐变上叠一层微弱噪点（opacity: 0.03~0.08），
> 会让页面从"屏幕感"变为"印刷感"，提升质感。

### 几何图案（Geometric Pattern）

```css
/* CSS 重复渐变制造网格 */
background-image:
  linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px),
  linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px);
background-size: 60px 60px;
```

### 分层透明度（Layered Transparencies）

- 多个半透明层叠加产生深度
- `backdrop-filter: blur()` + 半透明面板 = 毛玻璃效果

### 戏剧性阴影（Dramatic Shadows）

```css
/* 不用灰色阴影，用带颜色的阴影 */
box-shadow: 0 25px 60px rgba(200, 100, 50, 0.3);
```

### 自定义光标（Custom Cursor）

```css
body { cursor: none; }
/* 用 JS + div 实现自定义跟随光标 */
```

> [!warning] 自定义光标使用条件
> 
> 只在视觉方向非常强烈的展示页/作品集使用。功能性应用不适合。

---

## 组合原则

> [!important] 效果服务于 Tone，不是独立展示
> 
> - 极简风 → 最多一种细节（细线、微噪点）
> - 奢华风 → 渐变网格 + 噪点叠加
> - 未来风 → 几何网格 + 发光效果
> - 朴素风 → 纸张纹理 + 自然色调渐变

---

## 常见踩坑

> [!warning] Trap: 纯色背景 + 无任何纹理
> 
> 即使只加一层 opacity: 0.04 的噪点，也能显著提升质感。
> 纯色背景在截图中看起来"廉价"。

> [!warning] Trap: 效果太重喧宾夺主
> 
> 背景效果是**环境**，不是主角。保持低调（低不透明度），
> 让内容在前景突出。

---

## 相关笔记

- [[color-theme]] — 背景渐变使用 CSS 变量中的颜色
- [[spatial-composition]] — 背景效果强化空间层次
- [[anti-patterns]] — 避免"AI slop"背景（如：简单的浅紫渐变 blob）

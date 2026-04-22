---
name: color-theme
description: frontend-design 色彩系统与 CSS 变量策略
type: concept
source: teach_lx_source/SKILL.md
keywords: [color, css-variables, palette, accent, theme]
---

# 色彩与主题

#color-theme #frontend-design

---

## 是什么

色彩系统决定整个界面的情绪和层次感。
用 CSS 变量统一管理，保证一致性，也方便未来切换主题。

---

## 基础结构

```css
:root {
  /* 背景层次 */
  --color-bg:        /* 主背景 */;
  --color-surface:   /* 卡片/面板背景，略浅或略深于 bg */;

  /* 文字层次 */
  --color-text:      /* 主文字，高对比 */;
  --color-text-muted: /* 次要文字，低一级 */;

  /* 点缀色 */
  --color-accent:    /* 主 accent，用于 CTA、高亮、边框 */;
  --color-accent-2:  /* 可选第二 accent，谨慎使用 */;
}
```

---

## 配色策略

> [!important] 主色调主导原则
> 
> **一个主色调 (dominant) + 1-2 个锐利 accent = 有力量的配色**
> 
> vs.
> 
> 5-6 种颜色均匀分布 = 视觉噪音，缺乏重心

### 深色主题 vs 浅色主题

| 不要默认深色！ | 选择标准 |
|--------------|---------|
| 产品方向是什么？ | luxury/editorial → 常用浅色 |
| 内容以文字为主？ | 浅色可读性更好 |
| 科技/游戏/沉浸感？ | 深色更合适 |

> [!warning] Trap: 自动选深色主题
> 
> 深色不等于高级，浅色不等于简单。根据风格方向决定，不要有惯性。

---

## 常见踩坑

> [!warning] Trap: 紫色渐变 + 白底
> 
> 这是最被滥用的"AI 默认配色"。凡是出现紫色系渐变，都要停下来重新决策。

> [!warning] Trap: 硬编码颜色值
> 
> 代码里出现 `color: #6b21a8` 就是信号——应该用 CSS 变量，方便统一修改。

---

## 示例：深色奢华主题

```css
:root {
  --color-bg: #0a0a0a;
  --color-surface: #141414;
  --color-text: #f5f0e8;
  --color-text-muted: #6b6560;
  --color-accent: #c9a96e;   /* 金色 */
}
```

## 示例：浅色编辑风主题

```css
:root {
  --color-bg: #fafaf7;
  --color-surface: #ffffff;
  --color-text: #1a1a1a;
  --color-text-muted: #888;
  --color-accent: #c0392b;   /* 杂志红 */
}
```

---

## 相关笔记

- [[design-thinking]] — Tone 决定冷暖/深浅方向
- [[visual-details]] — 背景不只是纯色，颜色要配合纹理/渐变
- [[anti-patterns]] — 禁用配色模式

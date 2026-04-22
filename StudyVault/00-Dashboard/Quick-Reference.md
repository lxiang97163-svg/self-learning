# Quick Reference — frontend-design

---

## 设计前的 4 个问题 → [[concepts/design-thinking]]

| 问题 | 关键词 |
|------|--------|
| Purpose — 解决什么问题？谁用？ | 受众、场景、任务 |
| Tone — 风格方向？ | 选一个极端，见下方风格列表 |
| Constraints — 技术限制？ | 框架、性能、无障碍 |
| Differentiation — 让人记住的一点是什么？ | 记忆锚点 |

---

## 可选风格方向 → [[concepts/design-thinking]]

brutally minimal · maximalist chaos · retro-futuristic · organic/natural ·
luxury/refined · playful/toy-like · editorial/magazine · brutalist/raw ·
art deco/geometric · soft/pastel · industrial/utilitarian

---

## 排版铁律 → [[concepts/typography]]

- ✅ 展示字体（display）+ 正文字体（body）各一，形成对比
- ✅ 选有个性、不常见的字体
- ❌ 禁用：Inter · Roboto · Arial · system-ui · Space Grotesk

---

## 色彩策略 → [[concepts/color-theme]]

```css
:root {
  --color-bg: /* 主色调 */;
  --color-text: /* 高对比文字 */;
  --color-accent: /* 锐利点缀，1-2个 */;
}
```

- 主色调主导 + 1-2 个锐利 accent，胜过平均分布的多色方案

---

## 动效优先级 → [[concepts/motion]]

1. **最高价值**：页面加载时的交错出现（staggered reveal + animation-delay）
2. **次优**：hover 状态让人"意外"的反馈
3. **基础**：CSS-only 优先；React 用 Motion 库

---

## 空间构图要素 → [[concepts/spatial-composition]]

- 非对称 · 重叠 · 对角线流向 · 打破网格的元素
- 两个极端都可：极宽松负空间 OR 极致密排

---

## 背景效果清单 → [[concepts/visual-details]]

渐变网格 · 噪点纹理 · 几何图案 · 分层透明度 ·
戏剧性阴影 · 装饰性边框 · 自定义光标 · 颗粒感覆盖

---

## 反模式速查 → [[concepts/anti-patterns]]

| 禁用 | 原因 |
|------|------|
| 紫色渐变 + 白底 | 最滥用的"AI风" |
| Inter / Space Grotesk | 过度使用，无个性 |
| 均匀分布的多色方案 | 缺乏视觉层次 |
| 千篇一律的卡片网格 | 模板感 |
| 纯色背景，无任何纹理/层次 | 平淡 |

# yt-dlp 使用规则（YouTube 元数据与字幕）

> **yt-dlp**：开源命令行工具，用于从 YouTube 等平台获取视频/音频/字幕与元数据。仓库：[yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp)（原 youtube-dl 的活跃分支）。

**合规**：仅用于个人学习、本地归档；尊重版权与平台条款，勿将下载内容用于未授权商用或再分发。

---

## 一、安装

| 环境 | 命令 |
|------|------|
| pip | `pip install -U yt-dlp` |
| Windows（winget） | `winget install yt-dlp` |
| 升级 | 同上，加 `-U` 或重装 |

验证：`yt-dlp --version`

---

## 二、频道视频清单（ID / 标题 / 时长）

与本地 `outputs/DanKoe_视频列表.txt` 同类格式时，可用 `--print` 模板输出为纯文本：

```bash
yt-dlp --flat-playlist --print "%(id)s | %(title)s | %(duration)s" "https://www.youtube.com/@频道handle/videos"
```

说明：

- `--flat-playlist`：只展开列表、不逐个解析单条详情，**拉清单更快**；若个别条目缺 `duration`，可去掉该参数（会更慢）或单独对单视频再查。
- 输出重定向到文件：`... > DanKoe_视频列表.txt`

---

## 三、字幕（不下载视频）

**先看某视频有哪些字幕：**

```bash
yt-dlp --list-subs "https://www.youtube.com/watch?v=VIDEO_ID"
```

**只下载字幕（含自动字幕备选）：**

```bash
yt-dlp --skip-download --write-subs --write-auto-subs --sub-langs "en.*,zh-Hans,zh-Hant" "视频URL"
```

| 参数 | 含义 |
|------|------|
| `--skip-download` | 不下载视频/音频 |
| `--write-subs` | 下载创作者上传的字幕 |
| `--write-auto-subs` | 无人工字幕时使用自动字幕 |
| `--sub-langs` | 语言筛选，可按需改为 `en` 等 |

格式默认多为 `.vtt`；需要 `.srt` 时可加：`--convert-subs srt`（具体以当前版本文档为准）。

---

## 四、其他常用场景

| 需求 | 思路 |
|------|------|
| 只下音频 | `--extract-audio --audio-format mp3`（需本机有 ffmpeg 时体验更好） |
| 限制画质 | `-f "bestvideo[height<=1080]+bestaudio/best"` |
| 播放列表范围 | `--playlist-items 1-20` 或 `1,3,5-10` |
| Cookie 登录 | `--cookies-from-browser chrome`（仅当公开视频因地区/年龄需登录时） |

---

## 五、故障与限制

- **无字幕**：视频本身未开字幕或地区不可用，工具无法凭空生成。
- **429 / 限流**：降低频率、稍后重试；避免短时间大批量请求同一频道。
- **参数变更**：大版本升级后个别选项可能调整，以 `yt-dlp --help` 与 [官方 Wiki](https://github.com/yt-dlp/yt-dlp/wiki) 为准。

---

## 六、与本学习体系的衔接

- 频道订阅与 RSS 仍见：`创作者内容源索引.md`、`采集可行性评估.md`。
- 需要**全文稿精读**某期视频时：用本节「字幕」流程拉取后，再写入 `daily/每日学习_YYYYMMDD.md`。

---

*文档随 yt-dlp 版本实践迭代 | 2026-03-30*

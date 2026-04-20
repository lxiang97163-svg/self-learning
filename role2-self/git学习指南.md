# Git 学习指南（整合版）1

本文档根据学习过程整理，并随本仓库实际用法更新，便于复习与查阅。

---

## 一、Git 是什么，为什么要先配置

Git 是**分布式版本控制系统**：在本地记录每次提交（快照），并可与 GitHub 等远程仓库同步，用于协作、备份与历史追溯。

**`user.name` 与 `user.email` 的作用**

| 配置项 | 作用 |
|--------|------|
| `git config --global user.name "你的名字"` | 写入**每一次 commit 的作者名**，会显示在日志与 GitHub 提交记录里。 |
| `git config --global user.email "你的邮箱"` | 写入**每一次 commit 的作者邮箱**；GitHub 常用来把提交关联到你的账号（需与 GitHub 里登记的邮箱一致或已验证）。 |

二者都不是登录密码，而是**元数据**：告诉别人「这次提交是谁写的」。SSH 密钥才是连接 GitHub 时的身份验证方式。

---

## 二、环境准备：SSH 与远程通信

### 2.1 生成 SSH 密钥对

```text
ssh-keygen -t rsa -C "lxiang97@163.com"
```

- 在 `用户目录\.ssh\` 下生成**公钥**（`.pub`）与**私钥**（保密，勿上传）。
- 把 **公钥** 全文复制到 GitHub：**Settings → SSH and GPG keys → New SSH key**。

### 2.2 查看公钥（PowerShell）

```text
cd $HOME\.ssh
Get-Content $HOME\.ssh\id_rsa.pub
```

### 2.3 测试与 GitHub 的 SSH 连接

```text
ssh -T git@github.com
```

首次会问是否信任主机指纹，输入 `yes`；成功时 GitHub 会回复欢迎信息（可能显示你的用户名）。

---

## 三、仓库与远程：`clone` 与 `origin`

在 GitHub 上新建仓库、勾选 `.gitignore`/`README` 等，都是在**远程**完成的。本地用：

```text
git clone git@github.com:lxiang97163-svg/self-learning.git
```

- `clone` 会下载仓库并自动添加名为 **`origin`** 的远程，指向该 URL。
- 若曾连过别的仓库，可用 `git remote -v` 查看当前远程；不对则用：

```text
git remote set-url origin https://github.com/lxiang97163-svg/self-learning.git
```

HTTPS 与 SSH 两种 URL 二选一即可。

---

## 四、本仓库要达成的效果（个人 · 单仓库 · 三分方向）

**目标一句话**：一个仓库装个人相关内容；按时间段**只专注一个方向**（股票 / 自学 / 网站），换方向前**先提交**，避免不同方向的改动搅在一起；**偶尔把三条线合并进 `master`**，作为整仓库快照。

| 概念 | 作用 |
|------|------|
| **三条分支** `role1-stock` / `role2-self` / `role3-vpnWeb` | 三条**主题时间线**，各自记该方向的提交历史。 |
| **三个文件夹**（仓库根目录下同名目录） | **物理上**分开放文件，便于「当前身份只动对应目录」；分支不会自动隐藏其它文件夹，目录划分靠习惯与自律。 |
| **`master`** | **全项目快照**线：隔一段时间把三条 `role*` 合并进来，再 `push`，得到「当前整仓库状态」。 |

**本地与 GitHub 各需要几个分支？**

- 要完整实现上述效果：**本地 4 条**（`master` + 三条 `role*`）；**远程也建议 4 条**（都至少 `push` 过一次），便于备份与换电脑。
- **不必在网页上先「新建分支」**：本地已有分支时，第一次执行 `git push -u origin 分支名`，远程**会自动出现**同名分支；与在 GitHub 网页上点「新建分支」是两条路，**结果都是远程多一条分支**。

**与已删除的 `dev` 说明**：本仓库已收敛为 **`master` + 三条 `role*`**，不再使用 `dev` 作为集成线；个人场景下多一条 `dev` 往往只是多一次合并与记忆负担。

---

## 五、分支关系：别和「文件夹层级」搞混

- 分支没有强制的「父子目录」关系，都是**指向某次提交的指针**；「先后创建」不等于自动层级。
- **三个文件夹 ≠ 三个远程分支**：文件夹是磁盘上的目录；分支是 Git 里的历史线。二者配合使用：分支管**提交**，文件夹管**文件放哪**。

查看分支：

```text
git branch          # 本地分支
git branch -a       # 本地 + 远程跟踪分支
```

---

## 六、目录结构（本仓库）

仓库根目录示例：

- `role1-stock/` — 股票相关，对应分支 `role1-stock`
- `role2-self/` — 自学 / 笔记（含本 `git学习指南.md`），对应分支 `role2-self`
- `role3-vpnWeb/` — 网站 / VPN 相关，对应分支 `role3-vpnWeb`
- 根目录可保留公共文件：`README.md`、`.gitignore`、`LICENSE` 等

空目录可用 `.gitkeep` 占位以便 Git 跟踪。

**PowerShell 建目录与占位示例**：

```powershell
cd "E:\李响git工作空间\self-learning"
New-Item -ItemType Directory -Force -Path "role1-stock", "role2-self", "role3-vpnWeb"
New-Item -ItemType File -Force -Path "role1-stock\.gitkeep"
```

---

## 七、切换身份前：避免把半成品带到另一分支

1. `git status` 看是否有未提交修改。  
2. 若有：要么 **`git add` + `git commit`**，要么 **`git stash push -m "说明"`**（临时搁置，换分支后再 `git stash pop`）。  
3. 再 **`git switch role1-stock`**（或其它 `role*`）。  
4. 开始干活前（建议）：**`git pull`**（已 `-u` 跟踪时一条即可）或 `git pull origin role1-stock`。

---

## 八、日常开发（在某一 `role*` 上）

```text
git switch role1-stock
git pull
# 只编辑 role1-stock/ 下（及你约定可改的根目录公共文件）
git status
git add role1-stock
git commit -m "说明"
git push
```

换身份时重复第七节，再 `git switch` 到另一条 `role*`。

---

## 九、合并到 `master`（全项目快照）

在三条线上各自有提交后，需要「汇总快照」时：

```text
git switch master
git pull origin master
git merge role1-stock
git merge role2-self
git merge role3-vpnWeb
git push origin master
```

有冲突则按提示编辑文件 → `git add` → `git commit` → 再 `push`。合并顺序一般可任意；若同一文件多方向都改过，可能冲突，需手动取舍。

`git merge --no-ff -m "说明" 某分支` 可选：想保留「合并节点」时用。

---

## 十、推送被拒绝、pull 与 Vim：常见问题

**`! [rejected] ... (non-fast-forward)`**  
含义：远程分支上有你本地没有的提交（例如在网页改过 README、或另一台机器推过）。**不要**直接强推，除非确定要以本地覆盖远程。

**稳妥做法**：

```text
git pull origin master
```

若弹出 Vim 让你写「合并说明」，**Esc** → 输入 **`:wq`** → 回车，保存退出即完成合并；然后再：

```text
git push origin master
```

**类比**：GitHub 是网上备份，本地是电脑；两边都改过同一分支时，要先 **pull 合并** 再 **push**，不能无脑覆盖。

---

## 十一、撤销与回退

| 场景 | 做法 |
|------|------|
| 改了工作区，**还没** `git add` | `git restore 文件路径` |
| 已 `git add`，想取消暂存 | `git restore --staged 文件路径` |
| 已 `commit`，想改历史/指针 | `git reset`（多种模式，见下） |

**`git reset` 常见模式**

- `git reset --soft HEAD~1`：撤销最近一次 commit，**改动仍在暂存区**。
- `git reset --mixed HEAD~1`（默认）：撤销最近一次 commit，改动回**工作区、未暂存**。
- `git reset --hard <SHA>`：工作区、暂存区都与该提交一致；**未指向的提交可能「看不见」**（可用 `git reflog` 找回）。

回退后若远程已领先，普通 `push` 可能被拒；需与团队约定后使用 **`git push --force-with-lease origin master`**（个人仓库也要谨慎）。

---

## 十二、附录：第二天早上以 role1 身份开工（从头到尾）

假设前一天已收工，今早只做股票方向：

```powershell
cd "E:\李响git工作空间\self-learning"
git status
git switch role1-stock
git pull
# …编辑 role1-stock/…
git status
git add role1-stock
git commit -m "说明今天改了什么"
git push
```

下午换 **role2**：先保证 role1 已提交（并已 `push` 若需备份），再 `git switch role2-self` → `git pull` → 只改 `role2-self/` → `add` → `commit` → `push`。role3 同理。

---

## 十三、命令速查大表（背诵用）

下表合并常用命令；`-x` 为短选项，`--xx` 为长选项，需结合具体命令理解。

| 命令 / 片段 | 含义说明 |
|-------------|----------|
| `git config --global user.name "名"` | 设置**全局**用户名。 |
| `git config --global user.email "邮箱"` | 设置**全局**邮箱。 |
| `git config user.name "名"` | **仅当前仓库**覆盖（不加 `--global`）。 |
| `ssh-keygen -t rsa -C "邮箱"` | 生成 SSH 密钥；`-t rsa` 指定类型；`-C` 为注释。 |
| `Get-Content 路径` | PowerShell 读文件（如公钥）。 |
| `ssh -T git@github.com` | 测试 SSH；`-T` 不分配终端。 |
| `git clone <url>` | 克隆远程仓库。 |
| `git remote -v` | 查看远程 URL（verbose）。 |
| `git remote set-url origin <url>` | 修改 `origin` 地址。 |
| `git status` | 分支与暂存区、工作区变更。 |
| `git switch 分支名` | 切换分支。 |
| `git switch -c 新分支` | 创建并切换；`-c` = create。 |
| `git branch` / `git branch -a` | 本地分支；`-a` = 含远程跟踪。 |
| `git add .` / `git add 路径` | 加入暂存区；可指定目录只提交该方向。 |
| `git add -A` | 暂存所有变更（含删除）。 |
| `git commit -m "说明"` | 提交；`-m` = message。 |
| `git commit --amend` | 修改最近一次提交（改历史）。 |
| `git merge 分支名` | 将指定分支合并进**当前**分支。 |
| `git merge --no-ff -m "说明" 分支名` | 保留合并提交；`--no-ff` = 禁止快进。 |
| `git push origin 分支` | 推送到远程。 |
| `git push -u origin 分支` | `-u` = 设置上游，之后可简写 `git push`。 |
| `git push --force-with-lease origin 分支` | 需改写远程历史时用，比 `--force` 稍安全。 |
| `git pull` | 拉取当前分支跟踪的远程并合并。 |
| `git pull origin master` | 明确拉取 `origin` 的 `master`。 |
| `git fetch origin` | 只下载，不自动合并。 |
| `git restore 文件` | 丢弃工作区修改（未 add）。 |
| `git restore --staged 文件` | 取消暂存。 |
| `git reset --soft/--mixed/--hard` | 回退提交并影响暂存区/工作区，见上文。 |
| `git log --oneline` | 简洁日志。 |
| `git stash` / `git stash push -m` | 临时搁置改动。 |
| `git reflog` | HEAD 历史，用于找回提交。 |

**常见单字母选项对照（易混）**

| 选项 | 常见含义（需结合命令） |
|------|------------------------|
| `-a` | `git branch -a`：all |
| `-c` | `git switch -c`：create |
| `-m` | message |
| `-u` | upstream（`git push -u`） |
| `-v` | verbose（如 `remote -v`） |
| `-T` | `ssh -T` |
| `-t` | `ssh-keygen -t`：类型 |
| `-C` | ssh-keygen 注释 |
| `--no-ff` | 禁止快进合并 |

---

*文档随本仓库用法更新；协作项目以团队规范为准。*

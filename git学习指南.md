# Git 学习指南（整合版）

本文档根据你的学习流水账整理，并补充常见用法与注意事项，便于复习与查阅。

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

你在 GitHub 上新建仓库、勾选 `.gitignore`/`README`、把默认分支改为 `main`、再建 `dev` 等，都是在**远程**完成的。本地用：

```text
git clone git@github.com:lxiang97163-svg/self-learning.git
```

- `clone` 会下载仓库并自动添加名为 **`origin`** 的远程，指向该 URL。
- 若曾连过别的仓库，可用 `git remote -v` 查看当前远程；不对则用：

```text
git remote set-url origin https://github.com/lxiang97163-svg/self-learning.git
```

HTTPS 与 SSH 两种 URL 二选一即可，与团队约定保持一致。

---

## 四、分支：层级关系怎么理解

- **没有强制的「父子目录」关系**：`dev`、`role1-stock` 在数据结构上都是**指向某次提交的指针**，只是命名习惯不同。
- 常见约定：
  - **`main`**：相对稳定、可发布或长期基线。
  - **`dev`**：日常集成分支（你的「测试环境」集成点）。
  - **`role1-stock` 等**：个人或专题功能分支，开发完再合并进 `dev`。

你执行 `git switch -c dev` 是从**当前 HEAD** 新建并切到 `dev`；再 `git switch -c role1-stock` 是从当时所在分支的最新提交**再分出**一支。所以「先后创建」不代表自动层级，**合并关系**才体现协作结构（例如把 `role1-stock` 合并进 `dev`）。

查看分支：

```text
git branch          # 本地分支
git branch -a       # 本地 + 远程跟踪分支
```

---

## 五、日常开发流程（与你操作一致）

1. 在功能分支上改代码（如 `role1-stock`）。
2. `git status` 查看变更。
3. `git add .` 将改动加入**暂存区**（索引）。
4. `git commit -m "说明"` 生成一次提交。
5. 合并到 `dev`：

```text
git switch dev
git merge --no-ff -m "测试1" role1-stock
```

- `--no-ff`：即使能快进合并，也**保留一个合并提交**，历史上能清楚看到「这是一次从功能分支合入」。

6. 推送到 GitHub：

```text
git push -u origin dev
```

- **`-u`（`--set-upstream`）**：把本地 `dev` 与 `origin/dev` 绑定；之后在该分支上可直接 `git push` / `git pull`，不必每次写远程与分支名。
7. 在 **GitHub 网页** 上从 `dev` 向 `main`（或其它分支）发起 **Pull Request（PR）**，用于 Code Review 与合并策略，而不是替代 `git merge` 的必须步骤（小团队也可在本地合并再 push，看规范）。

---

## 六、三重身份：`role1-stock` / `role2-self` / `role3-vpnWeb`

下面把「三重身份」落实为**三条长期功能分支**，各自开发一块内容，最后都汇入 `dev`（再按你们流程进 `main`）。

### 6.1 分支命名建议

| 身份 | 建议分支名 | 负责内容（示例） |
|------|------------|------------------|
| 身份一 | `role1-stock` | 股票相关 |
| 身份二 | `role2-self` | 自学/个人笔记相关 |
| 身份三 | `role3-vpnWeb` | VPN/Web 相关 |

若分支尚未创建，在最新 `dev`（或 `main`）上建：

```text
git switch dev
git pull origin dev
git switch -c role2-self
git push -u origin role2-self
```

对 `role3-vpnWeb` 同理。

### 6.2 每次「切换身份」时推荐执行的命令

**目标**：干净地从一个分支换到另一个，避免把 A 的半成品带到 B。

1. 看当前状态：

```text
git status
```

2. 若有未提交修改，任选其一：
   - **小改动、想保留在同一分支**：先 `git add` + `git commit`；
   - **暂时不想提交、但要换分支**：`git stash push -m "wip role1-stock"`（详见命令表）。

3. 切换分支：

```text
git switch role1-stock
# 或
git switch role2-self
git switch role3-vpnWeb
```

4. 若刚才用了 `stash`，回到该分支后再：`git stash pop`（或 `git stash list` 后选择性恢复）。

5. 开始开发前（可选，保持与远程同步）：

```text
git pull origin role1-stock
```

### 6.3 各身份开发完成后合并到 `dev`

```text
git switch dev
git pull origin dev
git merge --no-ff -m "合并 role1-stock：说明" role1-stock
git push origin dev
```

其它两个分支同样把 `role1-stock` 换成对应分支名即可。

### 6.4 与「三个 GitHub 账号」的区别

若你指的是**三个不同的 GitHub 登录身份**（三套账号），则需要在**不同仓库目录**或**不同 remote** 上配置不同的 `user.name` / `user.email`（不用 `--global`，在仓库内 `git config user.name "..."`），并使用不同 SSH 密钥与 `~/.ssh/config` 里 `Host` 别名。你当前流水账描述的是**同一仓库内三分支**，按上面分支切换即可。

---

## 七、撤销与回退

| 场景 | 做法 |
|------|------|
| 改了工作区文件，**还没** `git add` | `git restore 文件路径`（或旧写法 `git checkout -- 文件`） |
| 已 `git add`，想取消暂存 | `git restore --staged 文件路径` |
| 已 `commit`，想改历史/指针 | `git reset`（多种模式，见下） |

**`git reset` 常见模式**

- `git reset --soft HEAD~1`：撤销最近一次 commit，**改动仍在暂存区**。
- `git reset --mixed HEAD~1`（默认）：撤销最近一次 commit，改动回**工作区、未暂存**。
- `git reset --hard <某次提交的 SHA>`：把工作区、暂存区都调成该提交的样子，**之后未指向的提交可能「看不见」**（仍可通过 `git reflog` 找回一段时间）。

**回退后 `git push -u origin dev` 是什么意思**

- 若你只是**本地多提交了几次**，回退后历史比远程「短」，普通 `git push` 可能被拒绝，因为远程已有「较新」的提交。
- 此时需要**改写远程历史**（团队需约定）：

```text
git push --force-with-lease origin dev
```

`--force-with-lease` 比 `--force` 更安全：若远程有人新推送，会拒绝覆盖，避免误删他人提交。**公共分支上强推要格外谨慎**。

---

## 八、实用习惯（补充）

- 提交信息用中文或英文均可，建议**动词开头、简短说明**，如：`fix: 修复登录超时`。
- 合并前在 `dev` 上 `git pull`，减少冲突。
- 大改前新建分支，避免直接在 `main` 上开发。
- 不确定时先看：`git status`、`git log --oneline -10`。

---

## 九、命令速查大表（背诵用）

下表合并**你提到的命令**与**常用相关命令**；`-x` 为短选项，`--xx` 为长选项，多数可成对记忆。

| 命令 / 片段 | 含义说明 |
|-------------|----------|
| `git config --global user.name "名"` | 设置**全局**用户名（所有仓库默认）。`--global` 存在用户主目录配置文件中。 |
| `git config --global user.email "邮箱"` | 设置**全局**邮箱。 |
| `git config user.name "名"` | **仅当前仓库**覆盖全局用户名（不加 `--global`）。 |
| `ssh-keygen -t rsa -C "邮箱"` | 生成 SSH 密钥；`-t rsa` 指定算法类型；`-C` 是注释（comment），常用邮箱标识密钥。 |
| `cd $HOME\.ssh` | 进入用户 `.ssh` 目录（PowerShell）。 |
| `Get-Content 路径` | PowerShell 读取文件内容（如公钥）。 |
| `ssh -T git@github.com` | 测试 SSH；`-T` 禁用伪终端，用于检测认证是否成功。 |
| `git clone <url>` | 克隆远程仓库到当前目录下新文件夹。 |
| `git remote -v` | 列出远程名与 fetch/push 的 URL（verbose）。 |
| `git remote set-url origin <url>` | 修改名为 `origin` 的远程地址。 |
| `git status` | 显示分支、暂存区与工作区变更。 |
| `git switch 分支名` | 切换到已有分支（Git 2.23+ 推荐）。 |
| `git switch -c 新分支` | 创建并切换到**新**分支；`-c` = create。 |
| `git branch` | 列出本地分支，当前分支前有 `*`。 |
| `git branch -a` | `-a` = all，含远程跟踪分支。 |
| `git branch -r` | 仅远程分支列表。 |
| `git add .` | 把当前目录下变更加入暂存区；`.` 表示当前目录。 |
| `git add -A` | 暂存**所有**变更（含删除）；与 `add .` 在多数场景类似，细节略有差异（子模块等）。 |
| `git add -p` | 按**块**（patch）挑选要暂存的部分，`-p` = patch。 |
| `git commit -m "说明"` | 提交暂存区；`-m` = message，提交说明。 |
| `git commit --amend` | 修改**最近一次**提交（可改说明或补文件），会改历史。 |
| `git merge 分支名` | 把指定分支合并进**当前**分支。 |
| `git merge --no-ff -m "说明" 分支名` | `--no-ff` = no fast-forward，保留合并提交；`-m` 为合并提交的说明。 |
| `git push origin 分支` | 把本地分支推送到远程 `origin` 上同名分支。 |
| `git push -u origin dev` | `-u` = `--set-upstream`，推送并设置上游跟踪分支。 |
| `git push --force-with-lease origin dev` | 强制推送，但若远程有新提交则失败；比 `--force` 更安全。 |
| `git pull` | 相当于 `fetch` + `merge`（默认策略），拉取当前分支跟踪的远程更新。 |
| `git pull origin dev` | 明确从 `origin` 拉取 `dev` 并与当前分支合并。 |
| `git fetch origin` | 只下载远程更新，**不**自动合并到当前分支。 |
| `git restore 文件` | 丢弃工作区对该文件的修改（未 add 时）；危险操作前确认。 |
| `git restore --staged 文件` | 把文件从暂存区移出，保留工作区修改。 |
| `git reset` | 移动当前分支指针，配合模式影响暂存区/工作区。 |
| `git reset --soft HEAD~1` | 回退 1 个提交，`HEAD~1` 表示前一个提交；改动留在暂存区。 |
| `git reset --mixed HEAD~1` | 回退 1 个提交，改动回工作区（默认）。 |
| `git reset --hard <SHA>` | **硬**回退到某提交，工作区与暂存区都与该提交一致。 |
| `git log --oneline` | 单行显示提交历史；`--oneline` 简写哈希与标题。 |
| `git log -n 5` | 只显示最近 5 条；`-n` 指定条数。 |
| `git diff` | 工作区 vs 暂存区。 |
| `git diff --staged` | 暂存区 vs 最近一次提交。 |
| `git stash` | 临时保存工作区（与可选暂存区）改动，便于切分支。 |
| `git stash push -m "说明"` | 带说明地 stash；`-m` = message。 |
| `git stash list` | 列出所有 stash。 |
| `git stash pop` | 应用并删除最近一条 stash。 |
| `git stash apply` | 应用 stash 但不删除。 |
| `git reflog` | 记录 HEAD 移动历史，找回「丢失」的提交很有用。 |
| `git clone --depth 1 <url>` | 浅克隆，只取最近一层历史；`--depth` 指定深度。 |
| `git tag v1.0` | 给当前提交打轻量标签；常用于发版。 |
| `git tag -a v1.0 -m "说明"` | `-a` 创建附注标签（annotated），带说明。 |

**常见单字母选项对照（易混）**

| 选项 | 常见含义（需结合具体命令） |
|------|----------------------------|
| `-a` | `git branch -a`：all；`git tag -a`：annotated |
| `-c` | `git switch -c`：create branch |
| `-m` | message（commit / merge / tag） |
| `-u` | upstream（`git push -u`） |
| `-v` | verbose（如 `remote -v`） |
| `-T` | `ssh -T`：不分配终端 |
| `-t` | `ssh-keygen -t rsa`：指定密钥**类型**（type） |
| `-C` | comment（注释），如 ssh-keygen 里标识密钥 |
| `-f` | force（多种命令中有「强制」含义，如 `push -f`） |
| `--no-ff` | 禁止快进合并，保留合并节点 |

---

## 十、与你原文的对应说明

- 「GitHub **网页**上出现 notice」：多为权限、分支保护或建议开 PR，按页面提示操作即可。
- 「`dev` 测试通过后再在网页点 Pull Request」：即远程协作里用 PR 做审查与合并；本地 `merge` 与网页 PR 是同一业务的不同环节，团队选一种主流程即可。

---

*文档生成用于自学整理；实际项目以团队 Git 规范为准。*
